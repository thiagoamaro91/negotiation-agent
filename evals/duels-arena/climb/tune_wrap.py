"""Runs tools/duel_tune.py unchanged, with two patches applied at import (so spawn workers get them too):
  1. duel_arena.PAIR_SEEN = 0 (Duels I found the paired limit in 0/34; the test eval hides it too).
  2. every arena.evaluate call gets the start file's non-tunable keys (late_poll, late_ticks, slot_demand, last_share,
     duel_ticks) merged under the candidate: duel_tune keeps only its TUNABLE keys, which would switch the late read
     off (-0.030 on TRAIN) and tune for a world Sunday will not run."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]  # repo root (this file lives in evals/duels-arena/climb/)
sys.path.insert(0, str(ROOT / "tools")); sys.path.insert(0, str(ROOT / "agent")); sys.path.insert(0, str(ROOT / "kit"))
import duel_arena as arena
import duel_tune as dt
arena.PAIR_SEEN = 0.0
START = json.loads((ROOT / "evals/duels-arena/climb/duels3-v1.json").read_text())
EXTRA = {k: v for k, v in START.items() if k not in dt.TUNABLE}
_orig = arena.evaluate
def _evaluate(params, *a, **k):
    return _orig({**EXTRA, **params}, *a, **k)
arena.evaluate = _evaluate
if __name__ == "__main__":
    print("fixed extras:", EXTRA, flush=True)
    sys.argv = ["duel_tune.py"] + sys.argv[1:]
    dt.main()
