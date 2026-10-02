"""Offline tests for agent/memory.py. Run: python3 -m unittest discover -s tests -t . (from the repo root) or python3 tests/test_memory.py"""
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
import memory as M


def msg(sender, price, tick, final=False, status="open", maker=None, text=""):
    o = {"maker": maker or sender, "final": final, "status": status,
         "give": {"cash": 0 if sender == "abuela" else price, "assets": [], "types": []}, "want": {"cash": price if sender == "abuela" else 0, "assets": [], "types": []}}
    return {"sender": sender, "tick": tick, "text": text, "offer": o}


def thread(i, ref, ms, status, reason=None, team="t03"):
    return {"id": i, "with": "abuela", "team": team, "topic": {"buy": {"card": ref}}, "status": status, "messages": ms, "closed_reason": reason}


def sample(i, ref, asks, bids, price, final=None, source="public"):
    return {"source": source, "thread": i, "team": "tX", "item": ref, "kind": M.kind_of(ref), "asks": asks, "bids": bids, "final_ask": final,
            "outcome": "deal" if price else "closed", "price": price, "gift": False, "closed_reason": None}


class T(unittest.TestCase):
    def test_kind_of(self):
        self.assertEqual([M.kind_of(x) for x in ("LAV-03", "MAL-07", "SAL-10", "sobre_barrio", "bad")], ["com", "unc", "rare", "pack", None])

    def test_parse_welcome_and_negotiated(self):
        w = M.sample_from_transcript(thread(1, "LAV-06", [msg("abuela", 17, 1, status="settled")], "deal"), "t03", "own")
        self.assertTrue(M.is_welcome(w)); self.assertEqual((w["price"], w["bids"]), (17, []))
        n = M.sample_from_transcript(thread(2, "LAV-07", [msg("abuela", 29, 1), msg("t03", 11, 1), msg("abuela", 22, 2, final=True, status="settled", text="a little present")], "deal"), "t03", "own")
        self.assertFalse(M.is_welcome(n)); self.assertEqual((n["price"], n["final_ask"], n["bids"], n["gift"]), (22, 22, [11], True))

    def test_non_abuela_and_unknown_items_ignored(self):
        self.assertIsNone(M.sample_from_transcript({**thread(3, "LAV-01", [], "open"), "with": "t05"}, None))
        self.assertIsNone(M.sample_from_transcript(thread(3, "ZZZ", [], "open"), None))

    def test_learns_floor_from_accepted_and_refused_bids(self):
        clean = [sample(1, "LAV-07", [29, 26, 22], [11, 14, 20], 20), sample(2, "LAV-08", [29, 25, 21], [12, 15, 20], 20)]
        a = M.Memory(clean, None).advice("unc")
        self.assertEqual(a["probe"], 19)               # accepted a bid of 20, refused <=15 -> aim one under, above anything refused
        taken_final = [sample(1, "LAV-07", [29, 26, 24, 22], [11, 14, 21], 22, final=22), sample(2, "LAV-08", [29, 26, 24, 22], [12, 15, 22], 22)]
        a = M.Memory(taken_final, None).advice("unc")
        self.assertEqual(a["probe"], 22)               # refused 21 on the way to her final 22: no point probing under it
        self.assertGreaterEqual(a["ceiling"], a["probe"])
        a = M.Memory(clean + taken_final[:1], None).advice("unc")
        self.assertEqual(a["probe"], 22)               # conflicting conversations (limits differ): stay above everything she refused

    def test_taking_her_opening_ask_is_not_welcome_and_not_negotiated(self):
        pack = sample(1, "sobre_barrio", [30], [15], 30)                         # accepted her 30 P opening for a pack
        self.assertFalse(M.is_welcome(pack)); self.assertTrue(M.is_opening(pack))
        m = M.Memory([pack], None)
        self.assertEqual((m.stats["pack"]["n_negotiated"], m.stats["pack"]["welcome"]), (0, 17))   # welcome stays the prior, not 30
        own = sample(2, "LAV-07", [29], [11], 29, source="own")
        self.assertEqual(M.Memory([own], None).grade(own)[0], "bad")
        self.assertEqual(M.Memory([own], None).unlock_progress()["negotiated"], 0)

    def test_welcome_deals_do_not_leak_into_what_others_paid(self):
        welcome = sample(1, "LAT-08", [17, 17, 17], [12, 13], 17)                # a welcome deal with token bids
        pub = [sample(i, "LAV-07", [29, 22], [11, 20], 22) for i in range(2, 4)]
        mine = sample(9, "LAV-07", [29, 26, 22], [11, 14], 22, final=22, source="own")
        g = M.Memory([welcome] + pub + [mine], None).grade(mine)
        self.assertEqual(g[0], "good", g)                                          # others paid 22; the 17 P welcome deal is not a comparison

    def test_welcome_deal_with_token_bid_is_not_floor_evidence(self):
        s = sample(1, "MAL-01", [7, 7], [3, 7], 7)
        self.assertTrue(M.is_welcome(s)); self.assertEqual(M.Memory([s], None).stats["com"]["n_negotiated"], 0)

    def test_grades(self):
        pub = [sample(i, "LAV-08", [29, 22], [11, 20], p) for i, p in ((1, 22), (2, 22), (3, 24))]
        mem = M.Memory(pub, None)
        bad = {**sample(9, "LAT-07", [29, 23], [11, 15], 23, final=23, source="own")}
        good = {**sample(10, "LAT-08", [29, 22], [11, 20], 22, source="own")}
        self.assertEqual(mem.grade(bad)[0], "bad"); self.assertEqual(mem.grade(good)[0], "good")
        self.assertEqual(mem.grade({**sample(11, "LAV-01", [7], [], 7, source="own")})[0], "neutral")
        self.assertEqual(mem.grade({**sample(12, "LAV-01", [29, 26], [11, 12], None, source="own")})[0], "bad")

    def test_feed_reconstruction(self):
        ev = [{"id": 1, "tick": 1, "type": "thread.opened", "payload": {"thread": 5, "team": "t07", "with": "abuela", "topic": {"buy": {"card": "LAT-08"}}}},
              {"id": 2, "tick": 1, "type": "thread.message", "payload": {"thread": 5, "offer": {"maker": "abuela", "final": False, "status": "open", "give": {"cash": 0}, "want": {"cash": 29}}}},
              {"id": 3, "tick": 1, "type": "thread.message", "payload": {"thread": 5, "offer": {"maker": "t07", "final": False, "status": "open", "give": {"cash": 13}, "want": {"cash": 0}}}},
              {"id": 4, "tick": 2, "type": "settlement", "payload": {"persona": "abuela", "parties": ["abuela", "t07"], "price": 25, "items": [{"ref": "LAT-08"}]}}]
        out = M.samples_from_feed(ev)
        self.assertEqual((len(out), out[0]["price"], out[0]["bids"], out[0]["asks"]), (1, 25, [13], [29]))

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            M.MEM = Path(d); m = M.Memory([sample(1, "LAV-07", [29, 22], [11], 22, final=22)], None); m.save()
            self.assertEqual(len(M.Memory.load().samples), 1); self.assertIn("learned", (Path(d) / "lessons.md").read_text().lower())

def sell_msg(sender, price, tick, ref="LAT-07", final=False, status="open"):
    asset = {"id": 253, "kind": "card", "ref": ref, "rarity": "uncommon"}
    if sender == "abuela":
        o = {"maker": "abuela", "final": final, "status": status, "give": {"cash": price, "assets": [], "types": []}, "want": {"cash": 0, "assets": [asset], "types": []}}
    else:
        o = {"maker": sender, "final": final, "status": status, "give": {"cash": 0, "assets": [asset], "types": []}, "want": {"cash": price, "assets": [], "types": []}}
    return {"sender": sender, "tick": tick, "text": "", "offer": o}


def sell_thread(i, ms, status, team="t03"):
    return {"id": i, "with": "abuela", "team": team, "topic": {"sell": {"assets": [253]}}, "status": status, "messages": ms, "closed_reason": None}


class Sell(unittest.TestCase):
    def test_sell_sample_reads_her_bids_and_our_asks(self):
        t = sell_thread(5, [sell_msg("abuela", 12, 1), sell_msg("t03", 20, 1), sell_msg("abuela", 14, 2), sell_msg("t03", 16, 2, status="settled")], "deal")
        s = M.sample_from_transcript(t, "t03", "own")
        self.assertEqual((s["side"], s["kind"], s["item"], s["asks"], s["bids"], s["price"]), ("sell", "unc", "LAT-07", [12, 14], [20, 16], 16))

    def test_sell_stats_advice_and_grades(self):
        pub = [{**sample(i, "LAT-07", [12, 13, 14], [20, 18, 16], p), "side": "sell"} for i, p in ((1, 14), (2, 16), (3, 13))]
        m = M.Memory(pub, None)
        self.assertEqual(m.sells["unc"]["best_price"], 16); self.assertEqual(m.sells["unc"]["her_limit"], 14)
        self.assertEqual(m.advice_sell("unc")["start_cap"], 25); self.assertIsNone(m.advice_sell("com"))
        self.assertEqual(m.grade({**sample(9, "LAT-07", [12, 14], [20, 16], 16, source="own"), "side": "sell"})[0], "good")
        self.assertEqual(m.grade({**sample(9, "LAT-07", [12, 14], [20, 12], 12, source="own"), "side": "sell"})[0], "bad")

    def test_buy_stats_ignore_sells(self):
        m = M.Memory([{**sample(1, "LAT-07", [12, 14], [20, 16], 16), "side": "sell"}], None)
        self.assertEqual(m.stats["unc"]["n"], 0)

    def test_feed_reconstructs_a_sale(self):
        ev = [{"id": 1, "tick": 1, "type": "thread.opened", "payload": {"thread": 7, "team": "t17", "with": "abuela", "topic": {"sell": {"assets": [253]}}}},
              {"id": 2, "tick": 1, "type": "thread.message", "payload": {"thread": 7, "offer": sell_msg("abuela", 12, 1)["offer"]}},
              {"id": 3, "tick": 1, "type": "thread.message", "payload": {"thread": 7, "offer": sell_msg("t17", 20, 1)["offer"]}},
              {"id": 4, "tick": 2, "type": "settlement", "payload": {"persona": "abuela", "parties": ["t17", "abuela"], "price": 14, "items": [{"ref": "LAT-07"}]}}]
        out = M.samples_from_feed(ev)
        self.assertEqual((len(out), out[0]["side"], out[0]["price"], out[0]["asks"], out[0]["bids"]), (1, "sell", 14, [12], [20]))


class Unlock(unittest.TestCase):
    def test_counts_negotiated_deals_only_and_welcome_never_counts(self):
        pub = [sample(i, "LAV-07", [29, 22], [11, 20], 22) for i in range(1, 4)]
        own = [sample(10, "LAV-06", [17], [], 17, source="own"),                       # welcome: never counts
               sample(11, "LAV-07", [29, 26, 22], [11, 14], 22, final=22, source="own"),
               sample(12, "LAV-08", [29, 26, 24], [11, 14], 24, final=24, source="own"),    # took a final above what others paid: graded bad
               sample(13, "LAT-07", [29], [11], None, source="own")]                  # no deal
        u = M.Memory(pub + own, None).unlock_progress()
        self.assertEqual((u["negotiated"], u["good"], u["needed"], u["assumed"]), (2, 1, 3, True))
        self.assertFalse(M.Memory(own, None, needed=4).unlock_progress()["assumed"])


if __name__ == "__main__":
    unittest.main()
