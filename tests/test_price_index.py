"""Dealer closes and the team price index (tools/price_index.py). Run: python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import price_index as pi  # noqa: E402

CAT = {"sets": [{"id": "LAV", "cards": [{"id": "LAV-01", "rarity": "common"}, {"id": "LAV-06", "rarity": "uncommon"},
                                         {"id": "LAV-09", "rarity": "rare"}, {"id": "LAV-10", "rarity": "rare"}]},
                {"id": "SAL", "cards": [{"id": "SAL-01", "rarity": "common"}, {"id": "SAL-09", "rarity": "rare"}]}],
       "packs": [{"id": "sobre_barrio"}]}
RARITY, KIND_OF, KIND_OF_TOPIC = pi.card_kinds(CAT)


class Feed:
    """A tiny public feed: dealer conversations and settlements in the server's shapes."""

    def __init__(self):
        self.events, self.thread, self.id = [], 0, 0

    def add(self, tick, kind, payload, t=None):
        self.id += 1
        self.events.append({"id": self.id, "tick": tick, "t": t if t is not None else tick / 60, "type": kind,
                            "payload": payload})

    def dealer_buy(self, tick, team, dealer, ref, asks, bids, price):
        """A team buys `ref` from `dealer`: the dealer asks `asks`, the team bids `bids`, they settle at `price`."""
        self.thread += 1
        th = self.thread
        self.add(tick, "thread.opened", {"thread": th, "kind": "persona", "team": team, "with": dealer,
                                         "topic": {"buy": {"card": ref}}})
        for i, (a, b) in enumerate(zip(asks, bids)):
            self.add(tick + i, "thread.message", {"thread": th, "kind": "persona", "sender": team, "team": team, "with": dealer,
                                                  "offer": {"give": {"cash": b}, "want": {"types": [f"card:{ref}"]}}})
            self.add(tick + i, "thread.message", {"thread": th, "kind": "persona", "sender": dealer, "team": team, "with": dealer,
                                                  "offer": {"give": {"types": [f"card:{ref}"]}, "want": {"cash": a}}})
        self.add(tick + len(asks), "settlement", {"persona": dealer, "price": price, "items": [
            {"id": 1000 + th, "kind": "card", "ref": ref, "frm": dealer, "to": team}]})

    def team_trade(self, tick, ref, price, t=None, venue="rastro"):
        self.add(tick, "settlement", {"persona": None, "price": price, "venue": venue, "fee": 1, "items": [
            {"id": 2000 + tick, "kind": "card", "ref": ref, "frm": "t01", "to": "t02"}]}, t)


class DealerCloses(unittest.TestCase):
    def feed(self):
        f = Feed()
        f.dealer_buy(10, "t04", "chato", "LAV-09", [97, 90, 85, 82], [47, 60, 70, 82], 82)
        f.dealer_buy(20, "t05", "chato", "LAV-10", [97, 93], [60, 93], 93)
        f.dealer_buy(30, "t06", "chato", "SAL-09", [97, 92, 90], [70, 80, 90], 90)
        f.dealer_buy(40, "t07", "chato", "LAV-09", [17], [17], 17)  # a welcome price: opens low, closes at its opening
        return f

    def test_every_settlement_finds_the_opening_of_its_conversation(self):
        deals = pi.dealer_deals(self.feed().events, KIND_OF)
        self.assertEqual([(d["price"], d["opening"]) for d in deals], [(82, 97), (93, 97), (90, 97), (17, 17)])

    def test_measured_range_leaves_out_welcome_deals(self):
        row = pi.dealer_prices(self.feed().events, KIND_OF, KIND_OF_TOPIC)["chato/sells/rare"]
        self.assertEqual((row["opening"], row["low"], row["median"], row["high"], row["n"]), (97, 82, 90, 93, 3))
        self.assertEqual(row["source"], "measured")

    def test_taking_his_ask_is_not_a_negotiated_close(self):
        f = self.feed()
        f.dealer_buy(50, "t08", "chato", "LAV-10", [97], [97], 97)
        row = pi.dealer_prices(f.events, KIND_OF, KIND_OF_TOPIC)["chato/sells/rare"]
        self.assertEqual((row["low"], row["high"], row["n"]), (82, 93, 3))

    def test_a_conversation_that_opened_far_from_his_usual_opening_is_another_regime(self):
        f = self.feed()
        f.dealer_buy(50, "t08", "chato", "LAV-10", [60, 58], [40, 58], 58)  # opened at 60, not ~97
        row = pi.dealer_prices(f.events, KIND_OF, KIND_OF_TOPIC)["chato/sells/rare"]
        self.assertEqual((row["low"], row["n"]), (82, 3))

    def test_too_few_closes_fall_back_to_fridays_range(self):
        f = Feed()
        f.dealer_buy(10, "t04", "chato", "LAV-09", [97, 88], [60, 88], 88)
        row = pi.dealer_prices(f.events, KIND_OF, KIND_OF_TOPIC)["chato/sells/rare"]
        self.assertEqual(row["source"], "fallback")
        self.assertEqual((row["low"], row["median"], row["high"], row["opening"]), (82, 91, 93, 97))

    def test_a_dealer_with_no_closes_shows_its_list_price_flagged(self):
        dealers = {"personas": [{"id": "duque", "menu": {"sells": [{"rarity": "epic", "list_price": 300, "opening_ask": 380}]}}]}
        row = pi.dealer_prices([], KIND_OF, KIND_OF_TOPIC, dealers)["duque/sells/epic"]
        self.assertEqual((row["source"], row["median"], row["opening"]), ("list", 300, 380))


class LadderShare(unittest.TestCase):
    BUY = {"side": "sells", "opening": 97, "low": 82, "median": 91, "high": 93}
    SELL = {"side": "buys", "opening": 5, "low": 6, "median": 6, "high": 6}

    def test_a_buy_captures_the_share_between_his_opening_and_the_lowest_close(self):
        self.assertEqual(pi.ladder_share(self.BUY, 84), 0.87)   # analysis-friday: "84 captures nearly all"
        self.assertEqual(pi.ladder_share(self.BUY, 93), 0.27)   # "93 captures about a quarter"
        self.assertEqual(pi.ladder_share(self.BUY, 97), 0.0)
        self.assertEqual(pi.ladder_share(self.BUY, 80), 1.0)    # clipped

    def test_a_sale_is_mirrored(self):
        self.assertEqual(pi.ladder_share(self.SELL, 6), 1.0)
        self.assertEqual(pi.ladder_share(self.SELL, 5), 0.0)


class TeamIndex(unittest.TestCase):
    def test_median_and_range_per_rarity_set_and_recent_window(self):
        f = Feed()
        f.team_trade(10, "LAV-01", 8, t=0.2)
        f.team_trade(20, "LAV-01", 12, t=0.3)
        f.team_trade(150, "SAL-01", 9, t=2.5)
        f.team_trade(155, "LAV-09", 70, t=2.6)
        f.dealer_buy(156, "t04", "chato", "LAV-10", [97, 90], [60, 90], 90)  # a dealer deal is not a team trade
        f.add(157, "settlement", {"persona": None, "price": 5, "items": [  # a swap both ways is not a price
            {"id": 1, "kind": "card", "ref": "LAV-01", "frm": "t01", "to": "t02"},
            {"id": 2, "kind": "card", "ref": "SAL-01", "frm": "t02", "to": "t01"}]}, t=2.62)
        ix = pi.team_index(f.events, RARITY, recent_hours=2.0)
        self.assertEqual(ix["trades"], 4)
        self.assertEqual(ix["all"]["rarity"]["common"], {"n": 3, "median": 9, "low": 8, "high": 12})
        self.assertEqual(ix["all"]["set"]["LAV"]["n"], 3)
        self.assertEqual(ix["all"]["set_rarity"]["LAV rare"]["median"], 70)
        self.assertEqual(ix["recent"]["rarity"]["common"], {"n": 1, "median": 9, "low": 9, "high": 9})
        self.assertNotIn("uncommon", ix["all"]["rarity"])


if __name__ == "__main__":
    unittest.main()
