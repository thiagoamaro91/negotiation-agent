"""tools/eval_common.py: a results file written under one policy label is never reused under another.

Run.case skips a (case, rep) already on disk, so without this guard a rerun with changed settings would report the
old scores under the new label. Run: python3 -m unittest tests.test_eval_common
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import eval_common as ec  # noqa: E402


class RerunGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = ec.EVALS
        ec.EVALS = Path(self.tmp.name)

    def tearDown(self):
        ec.EVALS = self.saved
        self.tmp.cleanup()

    def write_one(self, label):
        run = ec.Run("flow", "baseline", label)
        run.case("c1", 0, "prompt", [], lambda: ({"score": 1.0}, {}, [], {}))
        return run

    def test_the_same_label_resumes_and_skips_the_cached_case(self):
        self.write_one("policy-a")
        again = ec.Run("flow", "baseline", "policy-a")
        self.assertIn(("c1", 0), again.done)
        self.assertIsNone(again.case("c1", 0, "prompt", [], lambda: self.fail("a cached case must not run again")))

    def test_another_label_on_a_non_empty_results_file_is_refused(self):
        self.write_one("duel.py@abc+params-1.json@111")
        with self.assertRaises(SystemExit) as cm:
            ec.Run("flow", "baseline", "duel.py@abc+params-1.json@222")   # same file name, edited content
        self.assertIn("use a new variant", str(cm.exception))

    def test_a_fresh_variant_dir_takes_any_label(self):
        self.write_one("policy-a")
        ec.Run("flow", "v1", "policy-b")


if __name__ == "__main__":
    unittest.main()
