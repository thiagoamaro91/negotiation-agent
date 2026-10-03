"""tools/fairprice.py: the one fair price rule La Celestina and the concierge share. Pure functions, no I/O."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import fairprice as fp  # noqa: E402


def sale(eid, ref, frm, to, price, venue="v02", persona=None, qty=1):
    """A settlement event in the feed's shape: qty copies of one card from frm to to."""
    return {"id": eid, "tick": eid, "type": "settlement", "scope": "public", "actor": "",
            "payload": {"settlement": eid, "tick": eid, "kind": "trade", "venue": venue, "persona": persona,
                        "price": price, "items": [{"id": 100 * eid + k, "kind": "card", "ref": ref, "frm": frm, "to": to}
                                                  for k in range(qty)]}}


def newest_first(events, ref):
    return fp.cash_trades(events).get(ref, [])[::-1]


class CashTrades(unittest.TestCase):
    def test_sides_dealer_split_and_skips(self):
        rows = fp.cash_trades([
            sale(1, "SAL-01", "t02", "t05", 9),
            sale(2, "SAL-01", "t13", "abuela", 6, venue=None, persona="abuela"),   # a team sells to a dealer
            sale(3, "SAL-01", "abuela", "t09", 12, venue=None, persona="abuela"),  # a dealer sells to a team
            sale(4, "SAL-01", "t13", "chato", 3, venue=None),                      # no persona: still a dealer
            sale(5, "SAL-01", "t02", "t05", 20, qty=2),                            # 2 copies: 10 each
            {"id": 6, "type": "settlement", "payload": {"price": 8, "items": [      # a bundle of two cards: skipped
                {"kind": "card", "ref": "SAL-01", "frm": "t01", "to": "t02"},
                {"kind": "card", "ref": "SAL-02", "frm": "t01", "to": "t02"}]}},
            sale(7, "SAL-01", "t02", "t05", 0),                                    # no cash: skipped
            {"id": 8, "type": "gift.given", "payload": {"team": "t05", "cards": ["SAL-01"]}},
        ])["SAL-01"]
        self.assertEqual([(r["side"], r["price"], r["qty"]) for r in rows],
                         [("team", 9, 1), ("dealer_buys", 6, 1), ("dealer_sells", 12, 1), ("dealer_buys", 3, 1),
                          ("team", 10, 2)])
        self.assertEqual(rows[3]["dealer"], "chato")


class FairPrice(unittest.TestCase):
    def test_median_of_the_last_five_team_trades(self):
        ev = [sale(i, "LAV-01", "t01", "t02", p) for i, p in enumerate([5, 6, 7, 8, 9, 30], 1)]
        f = fp.fair_price(newest_first(ev, "LAV-01"))
        self.assertEqual((f["price"], f["n"], f["basis"]), (8, 5, "teams"))   # 30, 9, 8, 7, 6
        self.assertEqual(f["text"], "about 8 P (last team-to-team trades: 30, 9, 8, 7, 6)")
        self.assertEqual(f["range"], {"low": 6, "median": 8, "high": 9, "trades": 6})  # 25th-75th of all six

    def test_a_team_selling_to_a_dealer_is_the_dealers_buy_price_not_a_fair_price(self):
        ev = [sale(1, "SAL-01", "t02", "t05", 9), sale(2, "SAL-01", "t04", "t06", 7),
              sale(3, "SAL-01", "t13", "abuela", 1, venue=None, persona="abuela"),
              sale(4, "SAL-01", "t14", "abuela", 1, venue=None, persona="abuela")]
        f = fp.fair_price(newest_first(ev, "SAL-01"))
        self.assertEqual((f["price"], f["n"], f["basis"]), (8, 2, "teams"))
        self.assertEqual(f["range"], {"low": 8, "median": 8, "high": 8, "trades": 2})  # 7.5 -> 8, 8, 8.5 -> 8

    def test_fewer_than_two_team_trades_fall_back_to_dealer_prices_and_say_whose(self):
        ev = [sale(1, "SAL-01", "t02", "t05", 9),
              sale(2, "SAL-01", "t13", "abuela", 6, venue=None, persona="abuela"),
              sale(3, "SAL-01", "abuela", "t09", 12, venue=None, persona="abuela")]
        f = fp.fair_price(newest_first(ev, "SAL-01"))
        self.assertEqual((f["price"], f["n"], f["basis"]), (6, 1, "dealer_buys"))
        self.assertEqual(f["text"], "Abuela pays about 6 P for it; Abuela sells it for about 12 P (no team-to-team trades yet)")
        self.assertEqual(f["range"], {"low": 9, "median": 9, "high": 9, "trades": 1})  # team trades only
        only_dealer = fp.fair_price(newest_first(ev[2:], "SAL-01"))
        self.assertEqual((only_dealer["price"], only_dealer["basis"], only_dealer["range"]), (12, "dealer_sells", None))
        one = fp.fair_price(newest_first(ev[:1], "SAL-01"))
        self.assertEqual((one["price"], one["n"], one["text"]), (9, 1, "about 9 P (one team-to-team trade)"))
        self.assertEqual(fp.fair_price([]), {"price": None, "n": 0, "basis": None, "text": None, "range": None})

    def test_price_range_matches_the_concierge(self):
        self.assertEqual(fp.price_range([10, 12, 14, 16]), {"low": 12, "median": 13, "high": 14, "trades": 4})
        self.assertEqual(fp.price_range([7]), {"low": 7, "median": 7, "high": 7, "trades": 1})
        self.assertIsNone(fp.price_range([]))

    def test_pure_and_keyless(self):
        src = (ROOT / "tools" / "fairprice.py").read_text(encoding="utf-8")
        for banned in ("import urllib", "import socket", "open(", "BAZAAR_KEY", ".env", "/api/", "logs/"):
            self.assertNotIn(banned, src, banned)


if __name__ == "__main__":
    unittest.main()
