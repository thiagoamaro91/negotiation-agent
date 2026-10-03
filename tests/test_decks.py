"""Every team's deck from public asset ids (tools/decks.py). Run: python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import decks  # noqa: E402

CAT = {"sets": [{"id": "LAV", "cards": [{"id": "LAV-01", "name": "Uno"}, {"id": "LAV-06", "name": "La Tabacalera"},
                                        {"id": "LAV-09", "name": "Nueve"}]}],
       "packs": [{"id": "sobre_barrio", "slots": [{}, {}, {}]}, {"id": "sobre_plata", "slots": [{}, {}, {}, {}, {}]}]}
N = decks.STARTER


def ev(tick, kind, **payload):
    return {"tick": tick, "type": kind, "payload": payload}


def listed(tick, maker, *assets):
    return ev(tick, "offer.listed", offer={"maker": maker, "give": {"assets": [
        {"id": i, "kind": "card", "ref": r} for i, r in assets]}})


def settled(tick, frm, to, aid, ref):
    return ev(tick, "settlement", items=[{"id": aid, "kind": "card", "ref": ref, "frm": frm, "to": to}])


JOINED = [ev(0, "team.joined", team="t02"), ev(0, "team.joined", team="t01")]   # join order, not team number


class Decks(unittest.TestCase):
    def test_starter_blocks_follow_the_join_order(self):
        d = decks.build(JOINED, CAT)
        self.assertEqual(d["t02"]["ids"], list(range(1, N + 1)))
        self.assertEqual(d["t01"]["ids"], list(range(N + 1, 2 * N + 1)))
        self.assertEqual((d["t02"]["total"], d["t02"]["unknown_ids"], d["t02"]["known"]), (N, N, {}))

    def test_listings_name_cards_and_settlements_move_them(self):
        d = decks.build(JOINED + [listed(5, "t02", (3, "LAV-01")), settled(6, "t02", "t01", 3, "LAV-01"),
                                  settled(7, "abuela", "t02", 900, "LAV-09")], CAT)
        self.assertEqual(d["t02"]["known"], {"LAV-09": 1})
        self.assertEqual(d["t02"]["total"], N)          # one out, one in
        self.assertEqual(d["t01"]["known"], {"LAV-01": 1})
        self.assertEqual(d["t01"]["total"], N + 1)

    def test_a_pack_with_its_best_card_shown_places_the_whole_block(self):
        d = decks.build(JOINED + [ev(9, "pack.opened", team="t01", pack="sobre_plata",
                                     best={"id": 829, "ref": "LAV-09"})], CAT)
        self.assertEqual(d["t01"]["ids"][-5:], [825, 826, 827, 828, 829])
        self.assertEqual((d["t01"]["known"], d["t01"]["unplaced"], d["t01"]["total"]), ({"LAV-09": 1}, 0, N + 5))

    def test_a_pack_without_its_best_is_counted_once_even_after_its_cards_show_up(self):
        d = decks.build(JOINED + [ev(9, "pack.opened", team="t01", pack="sobre_barrio"),
                                  listed(12, "t01", (500, "LAV-01")), settled(14, "t01", "t02", 501, "LAV-01")], CAT)
        self.assertEqual((d["t01"]["unplaced"], d["t01"]["total"]), (1, N + 2))   # 3 pulled, 1 sold, 1 still unseen
        self.assertEqual(d["t02"]["total"], N + 1)

    def test_a_gift_and_a_workshop_card_are_the_same_copy_when_their_id_shows_up(self):
        d = decks.build(JOINED + [ev(3, "gift.given", team="t02", cards=["LAV-01"]),
                                  ev(4, "taller.crafted", team="t02", card="La Tabacalera"),
                                  listed(6, "t02", (777, "LAV-06"))], CAT)
        self.assertEqual(d["t02"]["floating"], {"LAV-01": 1})
        self.assertEqual(d["t02"]["known"], {"LAV-06": 1})
        self.assertEqual((d["t02"]["burned"], d["t02"]["total"]), (3, N + 1 + 1 - 3))

    def test_upto_stops_at_a_tick(self):
        d = decks.build(JOINED + [settled(50, "abuela", "t02", 900, "LAV-09")], CAT, upto=49)
        self.assertEqual(d["t02"]["total"], N)

    def test_check_against_a_real_deck(self):
        d = decks.build(JOINED + [listed(5, "t02", (3, "LAV-01"))], CAT)["t02"]
        real = [{"id": i, "kind": "card", "ref": "LAV-01" if i == 3 else "LAV-06"} for i in range(2, N + 1)] + \
               [{"id": 99, "kind": "card", "ref": "LAV-09"}]
        c = decks.check(d, real)
        self.assertEqual((c["real"], c["rebuilt"], c["ids_right"], c["ids_missed"], c["ids_wrong"]), (N, N, N - 1, 1, 1))
        self.assertEqual((c["named"], c["names_right"], c["missed"]), (1, 1, [99]))


class CensusTopUp(unittest.TestCase):
    """`decks.py moved`: the ids a tools/census.py top-up must re-read since a full walk."""
    SNAP = {"meta": {"tick_start": 100, "tick_end": 160},
            "cards": [{"id": i, "owner": "t02" if i <= 15 else "t01", "rarity": "common" if i % 2 else "rare"}
                      for i in range(1, 31)],
            "packs": [{"id": 31, "owner": "t02"}]}

    def test_settlements_packs_new_mints_our_burns_and_crafters_commons(self):
        events = JOINED + [settled(99, "t02", "t01", 3, "LAV-01"),            # before the census: not again
                           settled(120, "t02", "t01", 5, "LAV-01"),
                           ev(125, "settlement", items=[{"id": 31, "kind": "pack", "frm": "t02", "to": "t01"}]),
                           ev(130, "pack.opened", team="t02", pack="sobre_barrio", best={"id": 40, "ref": "LAV-09"}),
                           listed(140, "t02", (45, "LAV-01")),
                           ev(150, "taller.crafted", team="t01", card="La Tabacalera")]
        convs = [{"tick": 155, "burned": [{"id": 7, "ref": "LAV-01"}], "got": [{"id": 44, "ref": "LAV-06"}]},
                 {"tick": 90, "burned": [{"id": 8, "ref": "LAV-01"}], "got": []}]
        ids, info = decks.moved(events, self.SNAP, margin=2, conversions=convs)
        t01_commons = [i for i in range(16, 31) if i % 2]
        # counted mints: barrio pack 3 + craft 1 + new settled ids 0 (5 and 31 are below the census max) = 4 -> 35;
        # the feed's highest is 45 (the listing): new ids 32..45+2
        expected = sorted({5, 31, 7, 44} | set(range(32, 48)) | set(t01_commons))
        self.assertEqual(ids, expected)
        self.assertNotIn(3, ids)
        self.assertNotIn(8, ids)
        self.assertEqual((info["since"], info["census_max_id"], info["feed_max_id"], info["crafters"]), (100, 31, 45, ["t01"]))

    def test_a_pack_best_card_above_everything_else_raises_the_range(self):
        events = JOINED + [ev(130, "pack.opened", team="t02", pack="sobre_plata", best={"id": 90, "ref": "LAV-09"})]
        ids, info = decks.moved(events, self.SNAP, margin=0)
        self.assertEqual((ids[-1], info["feed_max_id"]), (90, 90))

    def test_unseen_mints_beyond_the_margin_are_counted(self):
        # Codex: nine five-card packs with no best card mint 45 ids; a fixed margin of 40 would stop short
        events = JOINED + [ev(130 + k, "pack.opened", team="t02", pack="sobre_plata") for k in range(9)] \
            + [ev(140, "gift.given", team="t01", cards=["LAV-01", "LAV-02"])]
        ids, info = decks.moved(events, self.SNAP, margin=0)
        self.assertEqual((info["mints_counted"], ids[-1]), (47, 31 + 47))
        self.assertEqual(ids, list(range(32, 79)))

    def test_since_overrides_the_census_tick_and_a_tickless_census_needs_it(self):
        events = JOINED + [settled(120, "t02", "t01", 5, "LAV-01")]
        self.assertNotIn(5, decks.moved(events, self.SNAP, since=130, margin=0)[0])
        with self.assertRaises(ValueError):
            decks.moved(events, {"meta": {}, "cards": []}, margin=0)

    def test_the_command_writes_ids_only(self):
        import json
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            feed = Path(d) / "feed.jsonl"
            feed.write_text("".join(json.dumps(e) + "\n" for e in JOINED + [settled(120, "t02", "t01", 5, "LAV-01")]))
            base, out = Path(d) / "snap.json", Path(d) / "moved.txt"
            base.write_text(json.dumps(self.SNAP))
            def offline(*a, **k):
                raise AssertionError("moved must not touch the network")

            with mock.patch.object(decks.vi, "FEED", Path(d)), mock.patch.object(decks.vi, "catalog", offline), \
                    mock.patch.object(decks.vi, "public", offline), mock.patch.object(decks.vi, "PUBLIC", Path(d)), \
                    mock.patch.object(decks.vi, "CONVERSIONS", Path(d) / "none.json"):
                decks.cmd_moved(["--base", str(base), "--margin", "0", "--out", str(out)])
            self.assertEqual(out.read_text(), "5\n")


class BrainDeckCheck(unittest.TestCase):
    def test_the_brain_checks_the_rebuild_on_our_relayed_account_at_its_tick(self):
        import brain
        events = JOINED + [settled(50, "abuela", "t02", 900, "LAV-09")]
        real = [{"id": i, "kind": "card", "ref": "LAV-01"} for i in range(1, N + 1)]
        orig = brain.vi.US
        brain.vi.US = "t02"
        try:
            c = brain.deck_vs_real(events, CAT, {"me": {"tick": 49, "assets": real}})
        finally:
            brain.vi.US = orig
        self.assertEqual((c["tick"], c["real"], c["rebuilt"], c["ids_wrong"]), (49, N, N, 0))


if __name__ == "__main__":
    unittest.main()
