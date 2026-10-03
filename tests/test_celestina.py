"""La Celestina: the consolidated book, matches, holders, prices, attribution, and what may leave on the public side.
Run: python3 -m unittest discover tests"""
import json
import re
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import celestina as cel  # noqa: E402


# ---------------------------------------------------------------- fixtures in the game's real payload shapes

def card(aid, ref, rarity="common"):
    return {"id": aid, "kind": "card", "ref": ref, "serial": aid, "rarity": rarity, "set": ref[:3], "print_run": 300}


def ask(ref, price, aid):
    return {"cash": 0, "assets": [card(aid, ref)], "types": []}, {"cash": price, "assets": [], "types": []}


def bid(ref, price):
    return {"cash": price, "assets": [], "types": []}, {"cash": 0, "assets": [], "types": [f"card:{ref}"]}


def swap(give_ref, want_ref, aid):
    return {"cash": 0, "assets": [card(aid, give_ref)], "types": []}, {"cash": 0, "assets": [], "types": [f"card:{want_ref}"]}


def offer(oid, maker, venue, sides, to=None, tick=10):
    give, want = sides
    return {"id": oid, "maker": maker, "to": to, "venue": venue, "thread": None, "status": "open", "give": give,
            "want": want, "expires_tick": tick + 30, "created_tick": tick, "final": False}


def listed(eid, team, o):
    """An offer.listed event as the feed shows it: the real team as actor and maker, same offer id as the book."""
    return {"id": eid, "tick": o["created_tick"], "t": 1.0, "type": "offer.listed", "scope": "public", "actor": team,
            "payload": {"venue": o["venue"], "offer": {**o, "maker": team}}}


def settle(eid, items, price, venue="rastro", persona=None, tick=5):
    return {"id": eid, "tick": tick, "t": 0.5, "type": "settlement", "scope": "public", "actor": "",
            "payload": {"settlement": eid, "tick": tick, "kind": "trade", "parties": sorted({i["frm"] for i in items} | {i["to"] for i in items}),
                        "venue": venue, "persona": persona, "fee": 0, "price": price,
                        "items": [{**card(i["id"], i["ref"]), "frm": i["frm"], "to": i["to"], "name": "x"} for i in items]}}


def item(aid, ref, frm, to):
    return {"id": aid, "ref": ref, "frm": frm, "to": to}


VENUES = {"venues": [
    {"venue": "rastro", "name": "El Rastro", "owner": "world", "owner_name": "The house", "status": "open", "fee_bps": 500,
     "fee_per_card": 1, "rules": {}, "starter": False, "house": True, "trades": 15},
    {"venue": "v02", "name": "El Duende · zero fee", "owner": "t12", "owner_name": "Team 12", "status": "open", "fee_bps": 0,
     "fee_per_card": 0, "rules": {"mechanism": "board"}, "starter": False, "house": False, "trades": 2},
    {"venue": "v09", "name": "Puesto de Team 3", "owner": "t03", "owner_name": "Team 3", "status": "closed", "fee_bps": 300,
     "fee_per_card": 0, "rules": {"mechanism": "auto"}, "starter": True, "house": False, "trades": 0},
    {"venue": "v20", "name": "La Celestina · finds your missing card", "owner": "t03", "owner_name": "Team 3",
     "status": "open", "fee_bps": 0, "fee_per_card": 0, "rules": {"mechanism": "board"}, "starter": False, "house": False,
     "trades": 0},
]}
CATALOG = {"rarities": {}, "sets": [{"id": "LAV", "name": "Lavapiés", "released": True, "cards": [
    {"id": f"LAV-{i:02d}", "name": f"Card {i}", "rarity": "common" if i < 6 else "uncommon", "book": 10, "print_run": 300,
     "minted": 20} for i in range(1, 11)]}]}
LEADERBOARD = {"tick": 50, "teams": [{"team": f"t{i:02d}", "name": f"Team {i}", "score": 30 - i, "rank": i, "album_filled": 20,
                                      "album_slots": 50, "pages_complete": 1, "venue": f"v{i:02d}"} for i in range(1, 19)]}
CLOCK = {"tick": 50, "tick_seconds": 30.0, "paused": False, "round_name": "Saturday", "doors": "open", "today_name": "Saturday"}


def market():
    """A small market: t15 bids LAV-09 at 30 on v02, t10 asks it at 25 on El Rastro (a stranded cross); t15 bids
    LAV-04 at 5 (t18 asks 9: a near miss; t17 holds 3 known copies: a spare); mirror swap LAV-01 <-> LAV-02 between
    t05 and t06; a bid for LAV-05 at 9 sits on our venue v20 (t07 holds 2 copies)."""
    o = {
        "b9": offer(101, "ma55bf699", "v02", bid("LAV-09", 30)),
        "a9": offer(102, "m41383bb2", "rastro", ask("LAV-09", 25, 501)),
        "b4": offer(103, "ma55bf699", "v02", bid("LAV-04", 5)),
        "a4": offer(104, "mcd38ffd5", "rastro", ask("LAV-04", 9, 502)),
        "s1": offer(105, "mdadbc40c", "rastro", swap("LAV-01", "LAV-02", 503)),
        "s2": offer(106, "m3950d43b", "v02", swap("LAV-02", "LAV-01", 504)),
        "b5": offer(107, "m5e679080", "v20", bid("LAV-05", 9)),
        "a5d": offer(108, "m12bf08dd", "rastro", ask("LAV-05", 3, 505), to="t14"),  # addressed to t14 only
    }
    teams = {"b9": "t15", "a9": "t10", "b4": "t15", "a4": "t18", "s1": "t05", "s2": "t06", "b5": "t08", "a5d": "t16"}
    events = [{"id": 1, "tick": 0, "type": "team.joined", "payload": {"team": "t03", "name": "Team 3"}, "actor": ""}]
    events += [settle(10 + i, [item(600 + i, "LAV-04", "abuela", "t17")], 9, venue=None, persona="abuela") for i in range(3)]
    events += [settle(20, [item(610, "LAV-05", "t01", "t07"), item(611, "LAV-05", "t01", "t07")], 16, venue="v02")]
    eid = 100
    for k, team in teams.items():
        if k != "a4":  # t18's ask was listed before the feed window: attributed by pseudonym (see the historical book)
            events.append(listed(eid, team, o[k]))
            eid += 1
    books = {"rastro": [o[k] for k in ("a9", "a4", "s1", "a5d")], "v02": [o[k] for k in ("b9", "b4", "s2")], "v20": [o["b5"]]}
    history = [{"id": 90, "maker": "mcd38ffd5"}]
    events.append(listed(eid, "t18", offer(90, "mcd38ffd5", "rastro", ask("LAV-03", 9, 590))))
    return books, events, history


def snapshot():
    books, events, history = market()
    return cel.build(VENUES, books, events, CATALOG, LEADERBOARD, CLOCK, history)


# ---------------------------------------------------------------- tests

class Shapes(unittest.TestCase):
    def test_ask_bid_swap_and_other(self):
        self.assertEqual(cel.shape(offer(1, "m", "rastro", ask("LAV-01", 8, 9)))["kind"], "ask")
        self.assertEqual(cel.shape(offer(1, "m", "rastro", ask("LAV-01", 8, 9)))["price"], 8)
        b = cel.shape(offer(1, "m", "rastro", bid("LAV-09", 15)))
        self.assertEqual((b["kind"], b["ref"], b["price"]), ("bid", "LAV-09", 15))
        s = cel.shape(offer(1, "m", "rastro", swap("LAV-01", "LAV-02", 9)))
        self.assertEqual((s["kind"], s["ref"], s["want_ref"]), ("swap", "LAV-01", "LAV-02"))
        bundle = ({"cash": 0, "assets": [card(1, "LAV-01"), card(2, "LAV-02")], "types": []}, {"cash": 20, "assets": [], "types": []})
        o = cel.shape(offer(1, "m", "rastro", bundle))
        self.assertEqual(o["kind"], "other")
        self.assertEqual(o["refs"], ["LAV-01", "LAV-02"])
        pack = ({"cash": 0, "assets": [{"id": 5, "kind": "pack", "ref": "sobre_barrio"}], "types": []}, {"cash": 20, "assets": [], "types": []})
        self.assertEqual(cel.shape(offer(1, "m", "rastro", pack))["kind"], "other")
        cash_and_card = ({"cash": 5, "assets": [card(1, "LAV-01")], "types": []}, {"cash": 0, "assets": [], "types": ["card:LAV-02"]})
        self.assertEqual(cel.shape(offer(1, "m", "rastro", cash_and_card))["kind"], "other")


class Attribution(unittest.TestCase):
    def test_listing_pseudonym_asset_trail_and_unknown(self):
        o_listed = offer(1, "ma55bf699", "v02", bid("LAV-09", 15))
        o_same_pseudo = offer(2, "ma55bf699", "v02", bid("LAV-10", 14))
        o_trail = offer(3, "mzzzz0001", "rastro", ask("LAV-01", 8, 77))
        o_unknown = offer(4, "mzzzz0002", "rastro", bid("LAV-02", 3))
        events = [listed(1, "t15", o_listed), settle(2, [item(77, "LAV-01", "abuela", "t09")], 9, venue=None, persona="abuela")]
        offer_team = cel.offer_teams(events)
        self.assertEqual(offer_team, {1: "t15"})
        pseudo = cel.resolve(cel.learn_pseudonyms([o_listed, o_same_pseudo, o_trail, o_unknown], offer_team))
        owners = cel.asset_owners(events)
        got = [cel.attribute(o, offer_team, pseudo, owners) for o in (o_listed, o_same_pseudo, o_trail, o_unknown)]
        self.assertEqual(got, [("t15", "listing"), ("t15", "pseudonym"), ("t09", "asset trail"), (None, "unknown")])

    def test_a_pseudonym_seen_behind_two_teams_is_not_trusted(self):
        a, b = offer(1, "mdup", "rastro", bid("LAV-01", 3)), offer(2, "mdup", "rastro", bid("LAV-02", 3))
        sets = cel.learn_pseudonyms([a, b], {1: "t01", 2: "t02"})
        self.assertEqual(cel.resolve(sets), {})

    def test_asset_trail_ignores_a_card_last_seen_with_a_dealer(self):
        o = offer(3, "mzzzz0001", "rastro", ask("LAV-01", 8, 77))
        owners = cel.asset_owners([settle(2, [item(77, "LAV-01", "t09", "abuela")], 5, venue=None, persona="abuela")])
        self.assertEqual(cel.attribute(o, {}, {}, owners), (None, "unknown"))

    def test_market_fixture_attributes_every_offer(self):
        snap = snapshot()
        self.assertEqual(snap["attribution"], {"listing": 7, "pseudonym": 1})
        row = next(r for r in snap["cards"]["LAV-04"]["offers"] if r["kind"] == "ask")
        self.assertEqual((row["team"], row["how"]), ("t18", "pseudonym"))


class Book(unittest.TestCase):
    def test_best_prices_across_venues_skip_addressed_offers(self):
        books, events, history = market()
        snap = cel.build(VENUES, books, events, CATALOG, LEADERBOARD, CLOCK, history)
        c9, c5 = snap["cards"]["LAV-09"], snap["cards"]["LAV-05"]
        self.assertEqual(c9["best_ask"], {"price": 25, "venue": "rastro"})
        self.assertEqual(c9["best_bid"], {"price": 30, "venue": "v02"})
        self.assertIsNone(c5["best_ask"])  # the 3 P ask is addressed to t14: shown, not a public best
        self.assertEqual(len([r for r in c5["offers"] if r["kind"] == "ask"]), 1)
        rows = cel.consolidate(cel.venue_rows(VENUES), {"rastro": [offer(1, "m1", "rastro", ask("LAV-01", 9, 1)),
                                                                   offer(2, "m2", "rastro", ask("LAV-01", 7, 2))],
                                                        "v02": [offer(3, "m3", "v02", ask("LAV-01", 8, 3))]}, {}, {}, {})
        self.assertEqual([r["price"] for r in cel.card_book(rows)["LAV-01"]["asks"]], [7, 8, 9])

    def test_our_venue_is_the_open_non_starter_one(self):
        self.assertEqual(cel.our_venue(cel.venue_rows(VENUES))["venue"], "v20")
        only_starter = {"venues": [v for v in VENUES["venues"] if v["venue"] != "v20"]}
        self.assertIsNone(cel.our_venue(cel.venue_rows(only_starter)))


class Matches(unittest.TestCase):
    def test_crossing_pair_on_different_venues_is_stranded_and_first(self):
        m = snapshot()["matches"]
        self.assertEqual(m[0]["kind"], "cross")
        self.assertEqual((m[0]["ref"], m[0]["buy"]["team"], m[0]["sell"]["team"]), ("LAV-09", "t15", "t10"))
        self.assertTrue(m[0]["stranded"])
        self.assertEqual(m[0]["gap"], -5)

    def test_same_venue_cross_is_not_stranded_and_same_maker_never_crosses(self):
        rows = cel.consolidate(cel.venue_rows(VENUES), {"v02": [offer(1, "ma", "v02", bid("LAV-01", 10)),
                                                                offer(2, "mb", "v02", ask("LAV-01", 8, 1)),
                                                                offer(3, "ma", "v02", ask("LAV-02", 1, 2)),
                                                                offer(4, "ma", "v02", bid("LAV-02", 5))]}, {}, {}, {})
        m = cel.find_matches(rows, {})
        self.assertEqual([(x["kind"], x["ref"], x["stranded"]) for x in m], [("cross", "LAV-01", False)])

    def test_each_offer_crosses_once(self):
        rows = cel.consolidate(cel.venue_rows(VENUES), {"v02": [offer(1, "ma", "v02", bid("LAV-01", 10)),
                                                                offer(2, "mb", "v02", ask("LAV-01", 8, 1)),
                                                                offer(3, "mc", "v02", ask("LAV-01", 9, 2))]}, {}, {}, {})
        crosses = [x for x in cel.find_matches(rows, {}) if x["kind"] == "cross"]
        self.assertEqual(len(crosses), 1)
        self.assertEqual(crosses[0]["sell"]["offer"], 2)  # the biggest surplus wins

    def test_latent_near_miss_and_known_spare(self):
        m = [x for x in snapshot()["matches"] if x["ref"] == "LAV-04"]
        kinds = {x["kind"]: x for x in m}
        self.assertEqual(kinds["near"]["sell"]["team"], "t18")
        self.assertEqual(kinds["near"]["gap"], 4)
        self.assertEqual((kinds["spare"]["sell"]["team"], kinds["spare"]["sell"]["copies"]), ("t17", 3))

    def test_a_lowball_bid_is_not_a_near_miss(self):
        rows = cel.consolidate(cel.venue_rows(VENUES), {"rastro": [offer(1, "ma", "rastro", bid("LAV-02", 1)),
                                                                   offer(2, "mb", "rastro", ask("LAV-02", 9, 1)),
                                                                   offer(3, "mc", "rastro", bid("LAV-03", 5)),
                                                                   offer(4, "md", "rastro", ask("LAV-03", 10, 2))]}, {}, {}, {})
        self.assertEqual([(m["kind"], m["ref"]) for m in cel.find_matches(rows, {})], [("near", "LAV-03")])

    def test_drafts_never_target_us(self):
        rows = cel.consolidate(cel.venue_rows(VENUES), {"v20": [offer(1, "ma", "v20", bid("LAV-02", 8))],
                                                        "rastro": [offer(2, "mb", "rastro", ask("LAV-02", 9, 1))]},
                               {1: "t09", 2: cel.US}, {}, {})
        anns = cel.announcements(cel.find_matches(rows, {}, "v20"), [], {}, "v20")
        self.assertTrue(anns)
        self.assertNotIn(cel.US, {t for a in anns for t in a["targets"]})

    def test_one_known_copy_is_only_a_weak_lead_and_the_bidder_is_never_its_own_match(self):
        rows = cel.consolidate(cel.venue_rows(VENUES), {"v02": [offer(1, "ma", "v02", bid("LAV-07", 20))]}, {1: "t04"}, {}, {})
        hold = {"LAV-07": {"t04": {"copies": 5, "net": 5}, "t09": {"copies": 1, "net": 1}}}
        m = cel.find_matches(rows, hold)
        self.assertEqual([(x["kind"], x["sell"]["team"]) for x in m], [("holder", "t09")])

    def test_mirror_swaps(self):
        m = [x for x in snapshot()["matches"] if x["kind"] == "mirror"]
        self.assertEqual(len(m), 1)
        self.assertEqual({m[0]["buy"]["team"], m[0]["sell"]["team"]}, {"t05", "t06"})
        self.assertEqual({m[0]["ref"], m[0]["want_ref"]}, {"LAV-01", "LAV-02"})

    def test_ranking_crossing_then_mirror_then_near_then_spare(self):
        order = [x["kind"] for x in snapshot()["matches"]]
        firsts = [order.index(k) for k in ("cross", "mirror", "near", "spare")]
        self.assertEqual(firsts, sorted(firsts))


class Holders(unittest.TestCase):
    def test_netting_from_settlements_gifts_and_pack_reveals(self):
        events = [
            settle(1, [item(1, "LAV-01", "abuela", "t02")], 9, venue=None, persona="abuela"),
            settle(2, [item(2, "LAV-01", "abuela", "t02")], 9, venue=None, persona="abuela"),
            settle(3, [item(1, "LAV-01", "t02", "t05")], 12),
            {"id": 4, "tick": 6, "type": "gift.given", "payload": {"team": "t07", "cards": ["LAV-01"]}},
            {"id": 5, "tick": 7, "type": "pack.opened", "payload": {"team": "t08", "best": {**card(9, "LAV-01"), "name": "x"}}},
            settle(6, [item(50, "LAV-01", "t11", "abuela")], 5, venue=None, persona="abuela"),  # a starting copy sold
        ]
        h = cel.holders(events)["LAV-01"]
        self.assertEqual(h["t02"], {"copies": 1, "net": 1})
        self.assertEqual(h["t05"], {"copies": 1, "net": 1})
        self.assertEqual(h["t07"], {"copies": 1, "net": 1})
        self.assertEqual(h["t08"], {"copies": 1, "net": 1})
        self.assertEqual(h["t11"], {"copies": 0, "net": -1})

    def test_asset_trail_proves_a_copy_the_net_hides(self):
        events = [settle(1, [item(1, "LAV-02", "abuela", "t04")], 9, venue=None, persona="abuela"),
                  settle(2, [item(99, "LAV-02", "t04", "t06")], 9)]  # t04 sold a different (starting) copy
        h = cel.holders(events)["LAV-02"]
        self.assertEqual(h["t04"], {"copies": 1, "net": 0})

    def test_a_listed_card_counts_as_held(self):
        rows = cel.consolidate(cel.venue_rows(VENUES), {"rastro": [offer(1, "m", "rastro", ask("LAV-03", 9, 42))]}, {1: "t13"}, {}, {})
        self.assertEqual(cel.holders([], rows)["LAV-03"]["t13"]["copies"], 1)


class Prices(unittest.TestCase):
    def test_recent_prices_per_card_and_reference(self):
        events = [settle(i, [item(i, "LAV-01", "t01", "t02")], p) for i, p in enumerate([5, 6, 7, 8, 9, 30], 1)]
        events.append(settle(10, [item(20, "LAV-01", "t03", "t04"), item(21, "LAV-01", "t03", "t04")], 20))
        events.append(settle(11, [item(22, "LAV-01", "t03", "t04"), item(23, "LAV-02", "t03", "t04")], 20))  # a bundle
        r = cel.recent_prices(events)["LAV-01"]
        self.assertEqual([x["price"] for x in r], [10, 30, 9, 8, 7, 6, 5])
        self.assertEqual(r[0]["qty"], 2)
        self.assertEqual(cel.reference_price(r), {"price": 9, "n": 5})
        self.assertNotIn("LAV-02", cel.recent_prices(events))
        self.assertEqual(cel.reference_price([]), {"price": None, "n": 0})


class Snapshots(unittest.TestCase):
    def test_private_snapshot_keys(self):
        snap = snapshot()
        for k in ("scope", "tick", "our_venue", "venues", "cards", "matches", "teams", "demand", "market", "attribution",
                  "announcements", "market_test", "sources"):
            self.assertIn(k, snap)
        self.assertEqual(snap["scope"], "private")
        self.assertEqual(snap["our_venue"]["venue"], "v20")
        t15 = next(t for t in snap["teams"] if t["team"] == "t15")
        self.assertEqual(sorted(b["ref"] for b in t15["bids"]), ["LAV-04", "LAV-09"])
        self.assertTrue(any(f["team"] == "t10" for f in t15["fillers"]))
        json.dumps(snap)

    def test_public_snapshot_keys_and_our_book(self):
        pub = cel.public_view(snapshot())
        self.assertEqual(set(pub), {"scope", "about", "pitch", "generated_at", "tick", "our_venue", "our_book",
                                    "invitations", "matches", "teams", "cards", "demand", "market", "market_test",
                                    "sources"})
        self.assertEqual([(b["kind"], b["ref"], b["price"]) for b in pub["our_book"]], [("bid", "LAV-05", 9)])
        self.assertIn("A bid for LAV-05 (Card 5) at 9 P is waiting on v20", pub["invitations"][0]["text"])
        self.assertEqual(pub["invitations"][0]["accept"]["path"], "/api/offers/107/accept")
        self.assertEqual(pub["invitations"][0]["counter"]["body"]["want"], {"cash": 9})
        d9 = next(d for d in pub["demand"] if d["ref"] == "LAV-09")
        self.assertEqual((d9["bids"], d9["best_bid"], d9["asks"], d9["best_ask"]), (1, 30, 1, 25))

    def test_public_by_team_shows_open_offers_on_every_venue(self):
        pub = cel.public_view(snapshot())
        t15 = next(t for t in pub["teams"] if t["team"] == "t15")
        self.assertEqual(sorted((b["ref"], b["venue"]) for b in t15["bids"]), [("LAV-04", "v02"), ("LAV-09", "v02")])
        self.assertEqual(t15["bids"][0]["source"], "https://bazaar.causaprima.ai/api/venues/v02/offers")
        t18 = next(t for t in pub["teams"] if t["team"] == "t18")
        self.assertEqual([(a["ref"], a["how"]) for a in t18["asks"]], [("LAV-04", "pseudonym")])
        self.assertEqual(t15["album_filled"], 20)

    def test_public_card_is_this_price_fair(self):
        c4 = cel.public_view(snapshot())["cards"]["LAV-04"]
        self.assertEqual(c4["reference"], {"price": 9, "n": 3})
        self.assertEqual([(t["settlement"], t["dealer"]) for t in c4["recent"]], [(12, "abuela"), (11, "abuela"), (10, "abuela")])
        bid4 = next(o for o in c4["offers"] if o["kind"] == "bid")
        self.assertEqual((bid4["verdict"]["ratio"], bid4["verdict"]["flag"]), (0.56, "low"))

    def test_public_snapshot_has_no_holder_map(self):
        snap = snapshot()
        pub = cel.public_view(snap)
        on_ours = {r["id"] for c in snap["cards"].values() for r in c["offers"] if r["venue"] == "v20"}
        self.assertTrue({b["offer"] for b in pub["our_book"]} <= on_ours, "an offer from another venue in our book")
        self.assertTrue({i["offer"] for i in pub["invitations"]} <= on_ours)
        banned = {"holders", "holdings", "copies", "net", "targets", "announcements", "fillers", "frm", "attribution"}

        def keys(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    yield k
                    yield from keys(v)
            elif isinstance(x, list):
                for v in x:
                    yield from keys(v)
        self.assertEqual(banned & set(keys(pub)), set())
        self.assertEqual({m["kind"] for m in pub["matches"]}, {"cross", "mirror", "near"})
        self.assertTrue(any(m["kind"] == "spare" for m in snap["matches"]))  # the private side does have them
        self.assertNotIn("holds", json.dumps(pub))

    def test_public_snapshot_does_not_depend_on_the_holder_map(self):
        snap = snapshot()
        before = json.dumps(cel.public_view(snap), sort_keys=True)
        for c in snap["cards"].values():
            c["holders"] = [{"team": "t17", "copies": 9, "net": 9}]
        for t in snap["teams"]:
            t["holdings"] = [{"ref": "LAV-01", "copies": 9}]
            t["fillers"] = [{"ref": "LAV-01", "team": "t17", "maker": None, "how": "holds 9 known copies"}]
        snap["announcements"] = [{"ref": "LAV-01", "text": "secret", "targets": ["t17"], "basis": "spare"}]
        snap["matches"].append({**snap["matches"][0], "kind": "holder", "why": "t17 holds 9 known copies"})
        self.assertEqual(json.dumps(cel.public_view(snap), sort_keys=True), before)

    def test_card_view_public_and_private(self):
        snap = snapshot()
        pub = cel.card_view(cel.public_view(snap), "LAV-05")
        self.assertEqual([b["ref"] for b in pub["our_book"]], ["LAV-05"])
        self.assertNotIn("holders", pub["card"])
        self.assertIn("holders", cel.card_view(snap, "LAV-05")["card"])
        self.assertEqual([m["kind"] for m in cel.card_view(cel.public_view(snap), "LAV-09")["matches"]], ["cross"])
        self.assertIsNone(cel.card_view(snap, "ZZZ-99"))


class Orders(unittest.TestCase):
    def test_ready_to_post_bodies_for_our_venue(self):
        self.assertEqual(cel.order("bid", "LAV-09", 30, "v20"),
                         {"method": "POST", "path": "/api/offers",
                          "body": {"venue": "v20", "give": {"cash": 30}, "want": {"cards": ["LAV-09"]}, "expires_in_ticks": 120}})
        self.assertEqual(cel.order("ask", "LAV-09", 25.0, "v20", 501)["body"]["give"], {"assets": [501]})
        self.assertEqual(cel.order("ask", "LAV-09", 25.0, "v20", 501)["body"]["want"], {"cash": 25})
        self.assertEqual(cel.order("ask", "LAV-09", 25, "v20")["body"]["give"], {"assets": ["<your LAV-09 asset id>"]})
        self.assertEqual(cel.order("swap", "LAV-01", None, "v20", 503, "LAV-02")["body"]["want"], {"cards": ["LAV-02"]})
        self.assertIsNone(cel.order("bid", "LAV-09", 30, None))

    def test_every_match_comes_with_orders_on_our_venue(self):
        for m in snapshot()["matches"]:
            self.assertEqual({o["body"]["venue"] for o in m["orders"].values()}, {"v20"}, m["kind"])
        cross = snapshot()["matches"][0]
        self.assertEqual(cross["orders"]["seller"]["body"]["give"], {"assets": [501]})  # t10's own copy, from its ask
        self.assertEqual(cross["orders"]["buyer"]["body"]["give"], {"cash": 30})
        near = next(m for m in snapshot()["matches"] if m["kind"] == "near")
        self.assertEqual((near["meet"], near["orders"]["buyer"]["body"]["give"]["cash"]), (7, 7))

    def test_verdicts(self):
        r = {"kind": "ask", "price": 40}
        v = cel.verdict(r, {"price": 9, "n": 5})
        self.assertEqual((v["ratio"], v["flag"]), (4.44, "high"))
        self.assertTrue(v["text"].startswith("4.4x the reference (9 P"))
        self.assertEqual(cel.verdict({"kind": "bid", "price": 9}, {"price": 9, "n": 1})["flag"], "fair")
        self.assertEqual(cel.verdict({"kind": "ask", "price": 5}, {"price": 9, "n": 1})["flag"], "bargain")
        self.assertIsNone(cel.verdict(r, {"price": None, "n": 0}))
        self.assertIsNone(cel.verdict({"kind": "swap", "price": None}, {"price": 9, "n": 1}))


class Announcements(unittest.TestCase):
    def test_drafts_say_only_what_is_on_our_venue(self):
        anns = snapshot()["announcements"]
        self.assertTrue(anns)
        for a in anns:
            self.assertLessEqual(len(a["text"]), cel.ANNOUNCE_MAX)
            self.assertTrue(a["text"].endswith("La Celestina · v20 · Team 3"))
            self.assertIsNone(re.search(r"\bt\d{2}\b", a["text"]))
            self.assertEqual(set(re.findall(r"\bv\d{2}\b", a["text"])), {"v20"})
            self.assertNotIn("rastro", a["text"].lower())
        spare5 = [a for a in anns if a["ref"] == "LAV-05"]
        self.assertTrue(any("A bid at 9 P is waiting on La Celestina (v20)" in a["text"] for a in spare5))
        self.assertIn("t07", spare5[0]["targets"])  # who to nudge stays in the private output

    def test_long_names_are_cut_to_fit(self):
        self.assertEqual(len(cel.sign("x" * 400, "v20")), cel.ANNOUNCE_MAX)

    def test_no_venue_no_drafts(self):
        self.assertEqual(cel.announcements(snapshot()["matches"], [], {}, None), [])


class FeedStoreMerge(unittest.TestCase):
    def test_dedupe_by_id_and_keep_only_used_types(self):
        s = cel.FeedStore(None)
        s.merge([{"id": 2, "type": "settlement"}, {"id": 1, "type": "offer.listed"}, {"id": 2, "type": "settlement", "x": 1},
                 {"id": 3, "type": "thread.message"}, {"type": "settlement"}])
        self.assertEqual([e["id"] for e in s.all()], [1, 2])
        self.assertNotIn("x", s.all()[1])


class Server(unittest.TestCase):
    def setUp(self):
        cel.publish(snapshot())
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), cel.handler("public"))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_public_json_is_public_view_with_cors(self):
        with urllib.request.urlopen(self.base + "/api/celestina.json") as r:
            self.assertEqual(r.headers["Access-Control-Allow-Origin"], "*")
            body = json.loads(r.read())
        self.assertEqual(body["scope"], "public")
        self.assertNotIn("announcements", body)
        self.assertEqual({m["kind"] for m in body["matches"]}, {"cross", "mirror", "near"})
        with urllib.request.urlopen(self.base + "/api/card/LAV-05.json") as r:
            self.assertEqual(json.loads(r.read())["card"]["ref"], "LAV-05")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/api/card/..%2Fetc.json")
        self.assertEqual(cm.exception.code, 404)
        with urllib.request.urlopen(self.base + "/") as r:
            self.assertIn(b"La Celestina", r.read())

    def test_rate_limit(self):
        lim = cel.Limiter(1.0, 3.0)
        self.assertEqual([lim.allow("a", now=0.0) for _ in range(4)], [True, True, True, False])
        self.assertTrue(lim.allow("b", now=0.0))
        self.assertTrue(lim.allow("a", now=1.5))


class PrivacyGuard(unittest.TestCase):
    def test_the_source_never_touches_the_key_or_private_values(self):
        src = (ROOT / "tools" / "celestina.py").read_text(encoding="utf-8")
        for banned in ("BAZAAR_KEY", ".env", "/api/me", "logs/state", "affinity"):
            self.assertNotIn(banned, src, f"tools/celestina.py mentions {banned!r}")

    def test_the_private_side_binds_to_loopback_only(self):
        src = (ROOT / "tools" / "celestina.py").read_text(encoding="utf-8")
        self.assertIn('ThreadingHTTPServer(("127.0.0.1", args.private_port), handler("private"))', src)


if __name__ == "__main__":
    unittest.main()
