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


if __name__ == "__main__":
    unittest.main()
