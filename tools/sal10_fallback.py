"""SAL-10 fallback from Los Picaros: the handoff's "13:30 decision" as a factory step.

SAL-10 is the last card of our Salamanca page (177 to us with the page bonus). The market desk bids for it from a team
on El Rastro all day (`--page SAL-10:110:80`), because a team trade scores value - price - fee while a dealer deal
scores only ladder credit. If no team has sold by about 13:30 Madrid (game hour 20.40, see tools/factory_sunday.json,
step sal10 / r3-s1-sal10-picaros), this script buys it from Los Picaros (sold 8 copies at 52 to 62 on Saturday).

`run`, in order:
  1. Reads /api/me: if we already hold SAL-10, logs a nothing-to-do marker and exits 0.
  2. Waits for any other Los Picaros run to end (one process per dealer) BEFORE yielding, so the desk keeps its bid
     meanwhile. A 40-round Picaros run lasts about 40 ticks, so this wait is bounded by window() (re-checked on every
     poll: it ends the moment a run started now could reach the next Market Test, the Final's quiet window or the
     finale warning: exit 6) and by --busy-wall-s, which only binds on a paused clock.
  3. Creates logs/state/page-yield-SAL-10 and waits for the desk's logs/state/page-yield-SAL-10.ack (the desk rewrites
     it every tick) with "open_bid": false and an integer "held" (the desk cancels its SAL-10 bid and stops buying
     that ref while the yield file exists). "held" > 0 means our own bid filled meanwhile: the yield goes, a
     nothing-to-do marker is logged and it exits 0 without chato. The ack wait has the same bounds as step 2; the
     window closing first removes the yield and exits 2. Two copies would be the worst case: the second is worth 22.75.
  4. Re-checks, with the yield kept, that no other Picaros run started and the ack still shows held 0 (same bounds),
     then reads the clock once more (a failed read raises and removes the yield), checks the window, checks for
     another Picaros run one last time and runs agent/chato.py --dealer picaros --only SAL-10 with cap 88, reserve
     40, one deal. chato accepts only an offer whose structured give is exactly one SAL-10 card for cash
     (agent/dealer_client.py exact_offer): a SAL-09 named in a SAL-10 thread is logged as a mismatch, never taken.
  5. Mirrors chato's outcome into logs/sal10/<date>.jsonl, the log the factory reads: a deal (`result` status deal)
     keeps the yield file; a no-deal exit 0 removes it so the desk bids again; a non-zero chato exit is passed through
     and keeps the yield only when an accept may have traded (6 unsettled, or a crash); a dealer stop (quota, cooloff, locked) exits 9.

Retry later: a wall bound (--busy-wall-s / --ack-wall-s, i.e. a clock paused for that long) removes the yield, logs
`retry_later` and exits 0 WITHOUT a done marker. tools/factory.py treats that like a no-deal run and relaunches the
step (up to the process's max_attempts) once its gates (clock running, duel quiet) are open again; a non-zero exit is
never relaunched. The window closing is final: nothing could be bought anyway, so it exits non-zero (6, or 2 with no
ack) and the watchdog shows it.

Residual race: there is no per-dealer lock (agent/lease.py governs accepts, not runs). Both this script and the
picaros keeper check the process table milliseconds before they spawn, so a keeper launch in that gap could put two
Picaros runs side by side. chato's --only SAL-10 and exact_offer still prevent a wrong buy, and the keeper refuses to
launch while our chato runs (its launch_check matches agent/chato.py picaros).

The key is read from .env by chato.py itself (never passed, never printed). `plan` is read-only: keyless clock and
schedule reads, plus /api/me only when BAZAAR_KEY is already set.

    python3 tools/sal10_fallback.py plan
    python3 tools/sal10_fallback.py run          # the factory runs this; needs the operator's yes like any dealer bot
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))
sys.path.insert(0, str(ROOT / "tools"))
from runlog import RunLog  # noqa: E402

REF = "SAL-10"
STATE = ROOT / "logs" / "state"
YIELD = STATE / f"page-yield-{REF}"
ACK = STATE / f"page-yield-{REF}.ack"
BASE = os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai")

EXIT_NO_ACK = 2          # the desk never confirmed it dropped its bid before the window closed: nothing bought
EXIT_WINDOW = 6          # too close to a Market Test or past the last safe game hour: nothing bought
EXIT_RETRY = 0           # a wall bound (paused clock): no done marker, so the factory relaunches the step
EXIT_DEALER_STOP = 9     # chato stopped on persona_quota / cooloff / locked without a deal
CLEAN_EXITS = {2, 3, 4, 5, 7, 8}   # chato refused or closed WITHOUT an accept going out (dealer_client EXIT_*): the yield
                                  # goes; 6 (unsettled) or a crash may have traded, so the yield stays
BENCH_AFTER_H = 0.15     # a Market Test (16 ticks) is over by this many game hours after it starts
FINAL_QUIET_MIN = 25     # the dealers' duel_quiet_min: no dealer run inside it before the Final


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def get_json(path: str, timeout: float = 15.0, tries: int = 3, pause_s: float = 5.0) -> dict:
    """Keyless public GET, tried 3 times 5 s apart: a non-zero exit fails the factory step for good."""
    for n in range(tries):
        try:
            with urllib.request.urlopen(f"{BASE}/api/{path}", timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception:  # noqa: BLE001
            if n == tries - 1:
                raise
            time.sleep(pause_s)


def holds(me: dict, ref: str = REF) -> bool:
    return any(a.get("kind") == "card" and a.get("ref") == ref for a in me.get("assets") or [])


def window(t_hours: float, events: list, run_game_min: float) -> tuple[bool, str]:
    """(ok, why) to START a Picaros run now: the run (about run_game_min game minutes) must end before the next Market
    Test (action bench), not start inside one, and not reach the Final's quiet window or the finale warning."""
    run_h = run_game_min / 60.0
    for e in sorted(events, key=lambda e: float(e.get("at_hours", 0))):
        at, act = float(e.get("at_hours", 0)), e.get("action")
        if act == "bench" and at <= t_hours < at + BENCH_AFTER_H:
            return False, f"inside the Market Test at {at:.3f} h"
        if act == "bench" and t_hours < at < t_hours + run_h:
            return False, f"the Market Test at {at:.3f} h starts within {run_game_min:g} game min"
        if act == "duels" and "final" in str((e.get("params") or {}).get("name", "")).lower():
            if t_hours + run_h > at - FINAL_QUIET_MIN / 60.0:
                return False, f"the Final duels at {at:.3f} h: the run would reach their {FINAL_QUIET_MIN} min quiet window"
        if act == "announce" and "finale" in str(e.get("note", "")).lower() and t_hours + run_h > at:
            return False, f"the finale warning at {at:.3f} h"
    return True, "clear"


def ack_ok(ack: dict, yield_tick: int) -> bool:
    """A fresh, well-formed desk ack: our ref, no open bid, a tick from this yield and an integer `held` count. Whether
    it lets us buy (held == 0) or says we already hold the card (held > 0) is the caller's branch."""
    return (isinstance(ack, dict) and ack.get("ref") == REF and ack.get("open_bid") is False
            and isinstance(ack.get("tick"), int) and ack["tick"] >= yield_tick - 1
            and isinstance(ack.get("held"), int) and not isinstance(ack.get("held"), bool) and ack["held"] >= 0)


def read_ack(path: Path | None = None):
    try:
        return json.loads((path or ACK).read_text())
    except (OSError, ValueError):
        return None


def fresh_ack(yield_tick: int, path: Path | None = None):
    a = read_ack(path)
    return a if ack_ok(a, yield_tick) else None


def wait_for(ready, read_hours, events: list, run_game_min: float, wall_s: float, poll_s: float,
             sleep=None, now=None) -> tuple[str, object]:
    """Poll ready() until it returns something other than None: ("ready", value). ("window", why) as soon as the game
    clock says a Picaros run started now could no longer finish in time (window()); ("wall", None) after wall_s
    seconds, which only binds on a paused clock. A failed clock read only means the wall bound decides."""
    sleep, now = sleep or time.sleep, now or time.monotonic     # looked up per call so tests can patch the module
    end = now() + wall_s
    while True:
        v = ready()
        if v is not None:
            return "ready", v
        try:
            h = float(read_hours())
        except Exception:  # noqa: BLE001
            h = None
        if h is not None:
            ok, why = window(h, events, run_game_min)
            if not ok:
                return "window", why
        if now() >= end:
            return "wall", None
        sleep(poll_s)


def write_yield(tick: int) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    try:
        ACK.unlink()                # a stale ack from an earlier attempt must never count
    except FileNotFoundError:
        pass
    tmp = YIELD.with_suffix(".tmp")
    tmp.write_text(json.dumps({"ref": REF, "tick": tick, "by": "tools/sal10_fallback.py", "pid": os.getpid()}) + "\n")
    tmp.replace(YIELD)


def drop_yield() -> None:
    for p in (YIELD, ACK):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)


def chato_argv(a: argparse.Namespace) -> list:
    return [sys.executable, "-u", "agent/chato.py", "run", "--dealer", "picaros", "--only", REF,
            "--cap", str(a.cap), "--anchor", str(a.anchor), "--step", str(a.step), "--reserve", str(a.reserve),
            "--max-deals", "1", "--max-rounds", str(a.max_rounds), "--max-wait-ticks", str(a.max_wait_ticks)]


def other_picaros_runs() -> list:
    import factory  # tools/factory.py: the same argv matcher the keepers use
    return factory.ps_pids(factory.ps_lines(), ["agent/chato.py", "picaros"])


def read_rows(path: Path, offset: int) -> list:
    rows = []
    if path.exists():
        with open(path, "rb") as fh:
            fh.seek(offset)
            for raw in fh.read().splitlines():
                try:
                    rows.append(json.loads(raw))
                except ValueError:
                    pass
    return rows


def outcome(rc: int, rows: list) -> str:
    """deal | nothing (chato's plan was empty: we hold SAL-10) | stop:<code> | failed | no_deal."""
    if any(r.get("event") == "result" and r.get("status") == "deal" for r in rows):
        return "deal"
    if rc != 0:
        return "failed"
    if any(r.get("event") == "run_start" and r.get("plan") == [] for r in rows):
        return "nothing"
    stops = [r.get("code") for r in rows if r.get("event") == "stop" and r.get("code") in ("persona_quota", "cooloff", "locked")]
    if stops:
        return f"stop:{stops[-1]}"
    return "no_deal"


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["plan", "run"])
    ap.add_argument("--only", choices=[REF], default=REF, help="the one card this fallback buys (explicit in the factory)")
    ap.add_argument("--max-deals", type=int, choices=[1], default=1, help="one copy: a second SAL-10 is worth 22.75")
    ap.add_argument("--cap", type=int, default=88, help="most we pay (SAL-10 ladder ceiling 91)")
    ap.add_argument("--anchor", type=int, default=40)
    ap.add_argument("--step", type=int, default=2)
    ap.add_argument("--reserve", type=int, default=40)
    ap.add_argument("--max-rounds", type=int, default=40)
    ap.add_argument("--max-wait-ticks", type=int, default=20, help="longest Picaros cooloff chato waits out")
    ap.add_argument("--ack-wall-s", type=float, default=1500.0,
                    help="wall cap on the wait for the desk's ack (the window closing ends it first on a running clock)")
    ap.add_argument("--run-game-min", type=float, default=20.0,
                    help="game minutes a Picaros run may take (40 ticks at 15 s, two game hours per wall hour)")
    ap.add_argument("--busy-wall-s", type=float, default=1500.0,
                    help="wall cap on the wait for another Picaros run to end (the window closing ends it first on a "
                         "running clock; a 40-round run takes about 10 wall minutes)")
    ap.add_argument("--ack-poll-s", type=float, default=3.0)
    ap.add_argument("--busy-poll-s", type=float, default=10.0)
    return ap.parse_args(argv)


def clock_hours():
    return get_json("clock").get("t_hours")


def main(argv=None) -> int:
    global SPAWNED
    SPAWNED = False
    a = parse_args(argv)
    load_env()
    clock, events = get_json("clock"), (get_json("schedule").get("upcoming") or [])
    h, tick = float(clock.get("t_hours") or 0.0), int(clock.get("tick") or 0)
    ok, why = window(h, events, a.run_game_min)
    if a.cmd == "plan":
        print(f"sal10_fallback plan  tick {tick}  game {h:.3f} h  paused {clock.get('paused')}  doors {clock.get('doors')}")
        if os.environ.get("BAZAAR_KEY"):
            from dealer_client import DealerBazaar
            me = DealerBazaar(BASE, os.environ["BAZAAR_KEY"], wait_on_tick=False).me()
            print(f"  holds {REF}: {holds(me)}  cash {me.get('cash')}")
        else:
            print(f"  holds {REF}: not checked (no BAZAAR_KEY in .env or the environment)")
        print(f"  window now: {'clear' if ok else why}")
        print(f"  yield file {rel(YIELD)} {'EXISTS' if YIELD.exists() else 'absent'}; "
              f"ack {rel(ACK)}: {read_ack() or 'absent'}")
        print(f"  waits: another Picaros run, then the desk ack (held 0 to buy, held > 0 = ours), each until the window "
              f"closes (exit {EXIT_WINDOW} / {EXIT_NO_ACK}) or {a.busy_wall_s:g} / {a.ack_wall_s:g} wall s "
              f"(exit {EXIT_RETRY} without a done marker: the factory relaunches)")
        print(f"  then: {' '.join(chato_argv(a)[1:])}")
        return 0
    from dealer_client import DealerBazaar
    run = RunLog("sal10")
    me = DealerBazaar(BASE, os.environ["BAZAAR_KEY"], wait_on_tick=False).me()
    if holds(me):
        run.start(plan=[], tick=tick, why=f"{REF} already ours")   # the factory's nothing-to-do marker
        return 0
    run.start(plan=[{"side": "buy", "item": REF, "dealer": "picaros", "cap": a.cap}], tick=tick, t_hours=h,
              cash=me.get("cash"))
    if not ok:
        run.event("refused", why=why, t_hours=h)
        return EXIT_WINDOW
    busy = other_picaros_runs()     # wait BEFORE yielding, so the desk keeps its SAL-10 bid meanwhile
    if busy:
        run.event("busy_wait", pids=busy, phase="before_yield", wall_s=a.busy_wall_s)
        state, why = wait_for(lambda: None if other_picaros_runs() else True, clock_hours, events, a.run_game_min,
                              a.busy_wall_s, a.busy_poll_s)
        if state == "window":
            run.event("refused", why=why, phase="busy_before_yield")
            return EXIT_WINDOW
        if state == "wall":
            run.event("retry_later", phase="busy_before_yield", wall_s=a.busy_wall_s,
                      why="another Picaros run outlasted the wall cap (paused clock?): the factory relaunches")
            return EXIT_RETRY
        try:
            tick = int(get_json("clock").get("tick"))
        except Exception:  # noqa: BLE001  (an older yield tick only widens which acks count; any old ack is deleted)
            pass
    write_yield(tick)
    try:      # until chato is spawned, any failure must give the bid back to the desk (nobody clears it by hand today)
        return after_yield(a, run, tick, events)
    except BaseException:
        if not SPAWNED:
            drop_yield()
        raise


SPAWNED = False


def after_yield(a: argparse.Namespace, run, tick: int, events: list) -> int:
    global SPAWNED
    run.event("yield_written", path=rel(YIELD), tick=tick)
    state, ack = wait_for(lambda: fresh_ack(tick), clock_hours, events, a.run_game_min, a.ack_wall_s, a.ack_poll_s)
    if state != "ready":
        drop_yield()
        if state == "window":
            run.event("no_ack", tick=tick, why=f"no desk ack (open_bid false, held count) before the window closed "
                                               f"({ack}): nothing bought, yield removed")
            print("NO ACK from the market desk before the window closed: not buying SAL-10 (yield removed).", flush=True)
            return EXIT_NO_ACK
        run.event("retry_later", phase="ack", tick=tick, wall_s=a.ack_wall_s,
                  why="no desk ack within the wall cap (paused clock?): yield removed, the factory relaunches")
        return EXIT_RETRY
    run.event("ack", **{k: ack.get(k) for k in ("ref", "tick", "open_bid", "held")})
    deadline = time.monotonic() + a.busy_wall_s

    def ready():
        cur = fresh_ack(tick) or ack      # the desk rewrites the ack every tick: a fill since shows as held > 0
        if cur["held"] > 0:
            return "held", cur
        return None if other_picaros_runs() else ("go", cur)
    while True:
        state, v = wait_for(ready, clock_hours, events, a.run_game_min, max(0.0, deadline - time.monotonic()),
                            a.busy_poll_s)
        if state == "window":
            drop_yield()
            run.event("refused", why=v, phase="after_ack")
            return EXIT_WINDOW
        if state == "wall":
            drop_yield()
            run.event("retry_later", phase="busy_after_ack", wall_s=a.busy_wall_s,
                      why="another Picaros run outlasted the wall cap (paused clock?): yield removed, the factory relaunches")
            return EXIT_RETRY
        kind, cur = v
        if kind == "held":     # our desk's bid filled: the desk stops on its own, the yield can go
            drop_yield()
            run.start(plan=[], tick=cur.get("tick"), why=f"{REF} held via the market desk (ack held {cur['held']})")
            return 0
        clock = get_json("clock")       # unguarded on purpose: a failed read raises and main() removes the yield
        ok, why = window(float(clock.get("t_hours") or 0.0), events, a.run_game_min)
        if not ok:
            drop_yield()
            run.event("refused", why=why, t_hours=clock.get("t_hours"))
            return EXIT_WINDOW
        busy = other_picaros_runs()     # last look, right before the spawn (see the residual race in the docstring)
        if not busy:
            break
        run.event("busy_wait", pids=busy, phase="before_spawn")
    log = ROOT / "logs" / "picaros" / (time.strftime("%Y-%m-%d") + ".jsonl")
    offset = log.stat().st_size if log.exists() else 0
    argv = chato_argv(a)
    run.event("chato_start", argv=argv[1:])
    SPAWNED = True
    rc = subprocess.call(argv, cwd=ROOT)
    res = outcome(rc, read_rows(log, offset))
    if res == "deal":
        run.event("result", status="deal", ref=REF, dealer="picaros")        # the factory's done marker
        return 0
    if res == "failed":
        keep = rc not in CLEAN_EXITS     # unsettled or a crash: an accept may have traded, the desk must not buy too
        if not keep:
            drop_yield()
        run.event("chato_failed", rc=rc, yield_kept=keep)
        return rc
    drop_yield()
    if res == "nothing":
        run.start(plan=[], why=f"chato found nothing to buy: {REF} is ours")
        return 0
    if res.startswith("stop:"):
        run.event("dealer_stop", code=res[5:])
        return EXIT_DEALER_STOP
    run.event("no_deal", why="yield removed: the desk bids again")
    return 0


if __name__ == "__main__":
    sys.exit(main())
