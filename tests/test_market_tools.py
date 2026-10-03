"""tools/make_floors.py and tools/market_replay.py: floors from our values, boards rebuilt from the feed.

    python3 -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import make_floors  # noqa: E402
import market_desk as md  # noqa: E402
import market_replay  # noqa: E402
from test_market_desk import AFFINITY, CAT, card  # noqa: E402


def trade(tick, ref, price, frm="t05", to="t07", rarity="common"):
    return {"id": 10_000 + tick * 10 + price, "tick": tick, "type": "settlement",
            "payload": {"kind": "trade", "parties": [frm, to], "venue": "rastro", "fee": 2, "price": price,
                        "items": [{"id": 900 + tick, "kind": "card", "ref": ref, "set": ref[:3], "rarity": rarity,
                                   "frm": frm, "to": to}]}}


class Floors(unittest.TestCase):
    def build(self, holdings, board=(), events=(), **kw):
        valuer = md.Valuer(CAT, AFFINITY, {r: len(v) for r, v in holdings.items()})
        tape = md.Tape().ingest(list(events))
        args = {"margin_min": 3, "margin_frac": 0.10, "sell_sets": (), "protect": ("LAV",), **kw}
        return [r["entry"] for r in make_floors.build(holdings, valuer, tape, list(board), **args)]

    def test_spares_keep_the_lowest_serial(self):
        h = {"LAV-08": [card(500, "LAV-08", 13), card(382, "LAV-08", 10)], "LAV-04": [card(33, "LAV-04", 1)]}
        rows = self.build(h)
        self.assertEqual([(r["asset_id"], r["card"]) for r in rows], [(500, "LAV-08")])
        self.assertEqual(rows[0]["floor"], 13)          # 40 x 0.25 = 10, + max(3, 1) = 13

    def test_floor_uses_the_second_copy_value_for_every_spare(self):
        h = {"SAL-03": [card(1, "SAL-03", 1), card(2, "SAL-03", 2), card(3, "SAL-03", 3)]}
        rows = self.build(h)
        self.assertEqual(sorted(r["asset_id"] for r in rows), [2, 3])
        self.assertTrue(all(r["floor"] == 7 for r in rows))   # 13 x 0.25 = 3.25 + 3 = 6.25 -> 7

    def test_start_from_observed_prices_and_under_the_cheapest_ask(self):
        h = {"LAV-08": [card(382, "LAV-08", 10), card(500, "LAV-08", 13)]}
        ev = [trade(t, "LAV-08", p, rarity="uncommon") for t, p in ((10, 22), (11, 26), (12, 30))]
        self.assertEqual(self.build(h, events=ev)[0]["start_ask"], 26)
        ask = {"id": 5, "maker": "m9", "to": None, "thread": None, "status": "open",
               "give": {"assets": [card(77, "LAV-08", 40)]}, "want": {"cash": 24}}
        self.assertEqual(self.build(h, board=[ask], events=ev)[0]["start_ask"], 23)
        ask["want"]["cash"] = 12                           # undercutting would go under the floor: keep the median
        self.assertEqual(self.build(h, board=[ask], events=ev)[0]["start_ask"], 26)

    def test_sell_sets_and_protected_pages(self):
        h = {"MAL-08": [card(44, "MAL-08", 1)], "LAV-07": [card(364, "LAV-07", 7)]}
        self.assertEqual(self.build(h), [])
        rows = self.build(h, sell_sets=("MAL", "LAV"), protect=("LAV",))
        self.assertEqual([(r["card"], r.get("allow_last_copy"), r["floor"]) for r in rows], [("MAL-08", True, 21)])

    def test_render_matches_the_seller_loader(self):
        import json
        import tempfile
        import rastro_seller
        entries = [{"asset_id": 500, "card": "LAV-08", "start_ask": 26, "floor": 13}]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write(make_floors.render("note", "rastro", entries))
        self.assertEqual(json.loads(Path(f.name).read_text())["cards"], entries)
        self.assertEqual(rastro_seller.load_config(Path(f.name))[0]["floor"], 13)
        Path(f.name).unlink()


class Replay(unittest.TestCase):
    def test_board_rebuild(self):
        def listed(oid, tick, ref, price, maker, exp, aid):
            return {"id": oid, "tick": tick, "type": "offer.listed", "actor": maker, "payload": {"venue": "rastro", "offer": {
                "id": oid, "maker": maker, "to": None, "venue": "rastro", "thread": None, "status": "open",
                "give": {"cash": 0, "assets": [card(aid, ref, 3)], "types": []},
                "want": {"cash": price, "assets": [], "types": []}, "expires_tick": exp, "created_tick": tick}}}
        ev = [listed(1, 5, "SAL-05", 9, "t07", 15, 101),        # expires at 15
              listed(2, 5, "SAL-04", 9, "t07", 40, 102),        # cancelled at 8
              listed(3, 6, "LAT-05", 8, "t15", 40, 103),        # sold at 12
              {"id": 50, "tick": 8, "type": "offer.cancelled", "payload": {"offer": 2, "venue": "rastro"}},
              {"id": 60, "tick": 12, "type": "settlement", "payload": {
                  "kind": "trade", "parties": ["t15", "t06"], "venue": "rastro", "fee": 2, "price": 8,
                  "items": [{"id": 103, "kind": "card", "ref": "LAT-05", "frm": "t15", "to": "t06"}]}}]
        rb = market_replay.rebuild(ev)
        ids = lambda t: sorted(o["id"] for offs in market_replay.board_at(rb, t, set()).values() for o in offs)  # noqa: E731
        self.assertEqual(ids(5), [1, 2])
        self.assertEqual(ids(7), [1, 2, 3])
        self.assertEqual(ids(8), [1, 3])
        self.assertEqual(ids(12), [1])
        self.assertEqual(ids(15), [])
        self.assertEqual(rb["taken"][3], {"tick": 12, "by": "t06"})


if __name__ == "__main__":
    unittest.main()
