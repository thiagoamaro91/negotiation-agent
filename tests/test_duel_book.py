"""tools/duel_book.py: templating, grouping duels into rival bots by their text template, the per-duel profile and
the --match path. Fixtures are built here (no /Volumes).

Run: python3 -m unittest discover tests
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import duel_book as book  # noqa: E402


def snap(did, role, limit, rival_lines, ours=(), item="Café en Goya", session=2, deadline=516, status="deal",
         price=None):
    """A duel snapshot like /Volumes/bazaar/logs/duels/duel-NNNNN.json; rival_lines = [(tick, price, text)]."""
    msgs = [{"tick": t, "from": "Rival Verde", "text": txt, "price": p, "days": None} for t, p, txt in rival_lines]
    msgs += [{"tick": t, "from": "you", "text": f"{p} P.", "price": p, "days": None} for t, p in ours]
    msgs.sort(key=lambda m: m["tick"])
    return {"duel": did, "session": session, "status": status, "role": role, "item": item, "issues": ["price"],
            "your_limit": limit, "rival": "Rival Verde", "deadline_tick": deadline, "decay_per_round": 0.06,
            "messages": msgs, "price": price, "your_offer": None, "rival_offer": None, "result": None}


def write_dir(tmp, duels):
    for d in duels:
        Path(tmp, f"duel-{d['duel']:05d}.json").write_text(json.dumps(d))
    return Path(tmp)


FAIR = "I can do {}. That is a fair deal for both of us."


def fair_pair():
    """Saturday's 2336/2337 shape: the same template in both roles, conceding every tick, we take its last."""
    seller = snap(2336, "seller", 80, [(500 + i, p, FAIR.format(p)) for i, p in enumerate([45, 49, 55, 62, 70, 79])],
                  ours=[(503, 124)], price=79)
    buyer = snap(2337, "buyer", 135, [(500 + i, p, FAIR.format(p)) for i, p in enumerate([223, 215, 204, 192])],
                 price=192)
    return seller, buyer


class Templating(unittest.TestCase):
    def test_numbers_item_case_and_whitespace(self):
        self.assertEqual(book.template("I can do 45   for Café en Goya.", "Café en Goya"), "i can do N for ITEM.")
        self.assertEqual(book.template("39?"), "N?")
        self.assertEqual(book.template("Puedo llegar a 96 primas. Dime si cerramos."),
                         "puedo llegar a N primas. dime si cerramos.")
        self.assertEqual(book.template("  12.5 P  "), "N p")

    def test_item_with_digits_is_replaced_before_numbers(self):
        self.assertEqual(book.template("Andén 0 for 80 P", "Andén 0"), "ITEM for N p")

    def test_language(self):
        self.assertEqual(book.language(["Puedo llegar a 96 primas. Dime si cerramos."]), "es")
        self.assertEqual(book.language(["We can do 74 P. Thank you for the talk."]), "en")
        self.assertEqual(book.language(["39?"]), "-")


class Grouping(unittest.TestCase):
    def test_two_duels_with_the_same_template_are_one_bot(self):
        a, b = fair_pair()
        other = snap(2500, "seller", 135, [(549, 136, "I can do 136. Let's close it quickly.")], item="Andén 0")
        groups, merges, silent = book.group(book.load(write_dir(tempfile.mkdtemp(), [a, b, other])))
        members = sorted(sorted(ids) for ids in groups.values())
        self.assertEqual(members, [[2336, 2337], [2500]])
        self.assertEqual(silent, [])

    def test_rotating_phrases_in_one_duel_merge_and_are_logged(self):
        d = snap(2384, "seller", 75, [(490, 74, "We can do 74 P. Thank you for the talk."),
                                      (491, 76, "76 P works well for us.")], price=76)
        e = snap(2390, "buyer", 174, [(505, 161, "161 P works well for us.")], item="Andén 0", price=161)
        groups, merges, _ = book.group(book.load(write_dir(tempfile.mkdtemp(), [d, e])))
        self.assertEqual(len(groups), 1)
        self.assertTrue(any(m["step"] == "co-occur" and m["duel"] == 2384 for m in merges))

    def test_a_pair_is_not_merged_unless_asked(self):
        sell = snap(2360, "seller", 154, [(503, 93, "Puedo llegar a 93 primas. Dime si cerramos.")])
        buy = snap(2361, "buyer", 140, [(518, 158, "Es una pieza que merece su precio: 158 primas. Pienso que es justo.")])
        duels = book.load(write_dir(tempfile.mkdtemp(), [sell, buy]))
        self.assertEqual(len(book.group(duels)[0]), 2)                  # consecutive ids, same item: not proof
        self.assertEqual(len(book.group(duels, use_pairs=True)[0]), 1)  # opt-in (--pairs)

    def test_different_bots_stay_apart_and_first_files_are_skipped(self):
        a = snap(2498, "seller", 51, [(579 + i, 39, "39?") for i in range(4)], item="El Mesón de la Cava")
        b = snap(2586, "buyer", 129, [(612, 137, "Propongo este precio, creo que es justo para los dos.")])
        tmp = write_dir(tempfile.mkdtemp(), [a, b])
        Path(tmp, "duel-02498-first.json").write_text(json.dumps(a))
        duels = book.load(tmp)
        self.assertEqual(sorted(d["duel"] for d in duels), [2498, 2586])
        self.assertEqual(len(book.group(duels, use_pairs=False)[0]), 2)


class Profile(unittest.TestCase):
    def test_every_tick_buyer_we_took_its_last_offer(self):
        seller, _ = fair_pair()
        r = book.profile_duel(book.load(write_dir(tempfile.mkdtemp(), [seller]))[0])
        self.assertEqual((r["rival_role"], r["shape"], r["open"], r["open_at"]), ("buyer", "every-tick", 45, 0))
        self.assertAlmostEqual(r["open_vs_limit"], 45 / 80, places=3)
        self.assertAlmostEqual(r["step_abs"], (79 - 45) / 5)
        self.assertEqual(r["accepted"], "we took theirs")
        self.assertFalse(r["reactive"])              # it moved while we were silent
        self.assertIsNone(r["acceptable_at"])       # 79 never reached our cost of 80

    def test_holder_that_takes_our_offer(self):
        d = snap(2499, "buyer", 125, [(579 + i, 157, "157?") for i in range(6)], ours=[(583, 80), (584, 115)],
                 deadline=595, price=115)
        r = book.profile_duel(book.load(write_dir(tempfile.mkdtemp(), [d]))[0])
        self.assertEqual((r["shape"], r["accepted"], r["step_abs"]), ("holds", "took ours", 0.0))


class Match(unittest.TestCase):
    def setUp(self):
        a, b = fair_pair()
        other = snap(2458, "seller", 87, [(569, 60, "Hi there. 60 P from my side."), (572, 80, "How about 80 P?")],
                     item="Andén 0", price=80)
        self.dir = write_dir(tempfile.mkdtemp(), [a, b, other])
        self.book = book.build(book.load(self.dir))

    def test_a_new_first_message_names_its_bot_with_high_confidence(self):
        ranked = book.match(self.book, "I can do 51. That is a fair deal for both of us.")
        bot = next(b for b in self.book["bots"] if 2336 in b["duels"])
        self.assertEqual(ranked[0][0], bot["id"])
        self.assertEqual(book.confidence(ranked), "high")

    def test_a_days_clause_still_matches_by_containment(self):
        ranked = book.match(self.book, "I can do 51 in 5 days. That is a fair deal for both of us.")
        self.assertEqual(ranked[0][0], next(b["id"] for b in self.book["bots"] if 2336 in b["duels"]))
        self.assertGreaterEqual(ranked[0][1], 0.7)

    def test_unknown_text_is_low_confidence(self):
        self.assertEqual(book.confidence(book.match(self.book, "Bonjour, je propose 40.")), "low")

    def test_cli_match_prints_the_bot_and_confidence(self):
        out = io.StringIO()
        argv = sys.argv
        sys.argv = ["duel_book.py", "--dir", str(self.dir), "--match", "Hi there. 70 P from my side."]
        try:
            with redirect_stdout(out):
                book.main()
        finally:
            sys.argv = argv
        text = out.getvalue()
        self.assertIn("template: 'hi there. N p from my side.'", text)
        self.assertIn("confidence: high", text)

    def test_build_writes_json_and_markdown(self):
        tmp = Path(tempfile.mkdtemp())
        argv = sys.argv
        sys.argv = ["duel_book.py", "--dir", str(self.dir), "--json", str(tmp / "b.json"), "--md", str(tmp / "b.md")]
        try:
            with redirect_stdout(io.StringIO()):
                book.main()
        finally:
            sys.argv = argv
        saved = json.loads((tmp / "b.json").read_text())
        self.assertEqual(saved["n_bots"], 2)
        self.assertIn("| B01 |", (tmp / "b.md").read_text())


if __name__ == "__main__":
    unittest.main()
