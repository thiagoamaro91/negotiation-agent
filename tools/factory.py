#!/usr/bin/env python3
"""Sunday factory: start Team 3's bots in the right order with the right flags, keep them up, report their health.

    python3 tools/factory.py plan                    # read-only (default): clock, schedule in wall time, commands, gates
    python3 tools/factory.py up                      # the same as plan: nothing starts without --yes
    python3 tools/factory.py up --yes [--no-bus]     # one tmux window per process (session "factory")
    python3 tools/factory.py status [--notify] [--every 60]   # one line per process; exit 1 if anything required fails

The configuration is data: tools/factory_sunday.json (processes, commands, gates, required or optional). Each tmux
window runs `factory.py keep <name>`, the restart loop. It holds results/factory/<name>.lock for its life (one keeper
per process). Before EVERY launch it re-reads the config (stops if the entry is disabled or an input file is gone)
and checks the gates (doors open and clock running, explicit values only), the duel wave (inside opening hours),
and that no copy of the bot runs outside the factory (argv only: script basename plus mode, in any path form). On
exit: `service` restarts, `session` (duels) restarts while the duel window is open, `steps` (dealers, off by default
until PR #35) moves on only after a deal or nothing-to-do line in the dealer's log and stops on any non-zero exit.
`up` fails closed on the bus: an unreadable board, a claim on another machine or a failed claim starts nothing
(`--no-bus` is the operator's override when GitHub is down). It writes <name>.json (state) and <name>.out (output).

No key: the factory calls only the keyless GET /api/clock and /api/schedule, and the bots get an allowlisted
environment (SAFE_ENV) with no key in it; they read their own .env (the broker its ~/.bazaar/broker.env). Game text
never reaches it: it reads only our own logs' event names, ticks and offer ids.

Game hours and wall time. On Friday and Saturday t_hours advanced tick_seconds/3600 per tick (Friday ticks 21 to 47:
0.350 to 0.783 h at 60 s; Saturday ticks 265 to 266: 3.533 to 3.542 h at 30 s): one game hour per wall hour. Sunday's
published table (hard Market Test 09:39, Duels III 11:39, Final 14:09, Madrid) fits about TWO game hours per wall hour,
so nothing here assumes a pace. Every decision (the duel session, the dealer gates, after_event) is made in game hours
from the live /api/clock and /api/schedule, re-read on every loop: a pause freezes it, a different pace only moves the
wall time at which it happens. The wall times that `plan` prints (marked +) are ESTIMATES: `plan` uses the pace the
keepers measured from the live clock (results/factory/pace.json), else `--pace X`, else 1.0 and says so. Bots act on
game events, never on those estimates.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "results" / "factory"
LOCK = ROOT / "results" / "duel.lock"
CONFIG = ROOT / "tools" / "factory_sunday.json"
MADRID = ZoneInfo("Europe/Madrid")
GATE_NAMES = {"doors_open": "doors open", "clock_running": "clock running", "no_duel_lock": "no duel lock"}
GATE_DEFAULTS = {"doors_open": True, "clock_running": True}     # fail closed: a process opts out explicitly
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
SAFE_ENV = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR", "BAZAAR_OPERATOR",
            "BAZAAR_URL", "TEAM_BUS_REPO", "TEAM_BUS_ISSUE", "TEAM_BUS_STATE", "TEAM_BUS_SESSION", "PYTHONUNBUFFERED")
SECRETISH = re.compile(r"KEY|TOKEN|SECRET|PASS", re.I)
RECHECK_S = 6.0          # status looks twice before calling a child dead (a keeper notices an exit within 5 s)
PACE_FASTEST = 4.0       # the fastest game clock we would believe (game hours per wall hour): with no measured pace,
                         # a wave is projected as early as that allows, so an unknown pace never refuses a launch
PACE_MIN_SPAN_S = 120.0  # a pace is reported only after this long of a running clock (tick edges are seen to 10 s)
PACE_WINDOW_S = 900.0    # ... measured over at most this long
PACE_MAX_AGE_S = 600.0   # `plan` and `status` trust results/factory/pace.json for this long


# --- pure logic (tests/test_factory.py) ----------------------------------------------------------------------------

def iso_epoch(s):
    return datetime.fromisoformat(s).timestamp() if s else None


def hhmm(epoch, tz=MADRID, day=False) -> str:
    return datetime.fromtimestamp(epoch, tz).strftime("%a %H:%M" if day else "%H:%M")


def day_of(clock: dict, wall: float):
    """The opening day in clock["days"] that contains this wall time, or None."""
    for d in clock.get("days") or []:
        o, c = iso_epoch(d.get("opens")), iso_epoch(d.get("closes"))
        if o is not None and c is not None and o <= wall < c:
            return d
    return None


def to_wall(at_hours: float, clock: dict, events: list, now: float, pace: float = 1.0) -> tuple[float, bool]:
    """(wall epoch, earliest) for a game hour: an ESTIMATE, at `pace` game hours per wall hour. Anchored at
    (now, t_hours) while running, at the next opening while the doors are closed, and at the last known day opening
    before the event (game time stops overnight). While the doors are closed the clock resumes at the hour it shows, so
    a day opening listed LATER than that hour (Saturday closed at 13.37 h, the schedule's Sunday opens at 16.65 h) is
    not an anchor. `earliest` is True while the clock is paused: every paused minute moves the event one minute later."""
    h = float(clock.get("t_hours") or 0.0)
    wall, base = now, h
    closed = clock.get("doors", "open") != "open"
    if closed and clock.get("next_opens"):
        wall = iso_epoch(clock["next_opens"])
    for e in sorted(events, key=lambda e: float(e.get("at_hours", 0))):
        at = float(e.get("at_hours", -1))
        if closed and at > h + 1e-6:
            continue
        if e.get("action") == "day_opens" and e.get("wall") and base <= at <= at_hours and iso_epoch(e["wall"]) >= wall:
            wall, base = iso_epoch(e["wall"]), at
    return wall + (at_hours - base) * 3600.0 / (pace or 1.0), bool(clock.get("paused")) and at_hours > h


def ticks_until(at_hours: float, now_hours: float, tick_seconds: float, pace: float = 1.0) -> int:
    """Ticks to a game hour: a tick is tick_seconds wall seconds and carries tick_seconds x pace game seconds."""
    return round((at_hours - now_hours) * 3600.0 / (tick_seconds * (pace or 1.0)))


class PaceMeter:
    """Game hours per wall hour, measured from successive /api/clock reads while the clock runs. One sample per tick
    (the first read that sees it), so the span is a whole number of ticks to within the polling interval (<= 10 s): over
    PACE_MIN_SPAN_S or more the error is under 10 %, over 15 minutes about 1 %. A pause, a closed door or a clock that
    goes backwards starts it again. None until it has seen enough."""

    def __init__(self):
        self.samples = []          # (wall, t_hours, tick)

    def update(self, wall: float, clock: dict) -> None:
        tick = clock.get("tick")
        if clock.get("doors") != "open" or clock.get("paused") is not False or not isinstance(tick, int):
            self.samples.clear()
            return
        h = float(clock.get("t_hours") or 0.0)
        if self.samples and (tick < self.samples[-1][2] or h < self.samples[-1][1] or wall < self.samples[-1][0]):
            self.samples.clear()
        if not self.samples or tick != self.samples[-1][2]:
            self.samples.append((wall, h, tick))
        while len(self.samples) > 2 and wall - self.samples[0][0] > PACE_WINDOW_S:
            self.samples.pop(0)

    @property
    def pace(self):
        if len(self.samples) < 2:
            return None
        (w0, h0, t0), (w1, h1, t1) = self.samples[0], self.samples[-1]
        if t1 <= t0 or w1 - w0 < PACE_MIN_SPAN_S or h1 <= h0:
            return None
        return (h1 - h0) * 3600.0 / (w1 - w0)


def pace_path() -> Path:
    return STATE / "pace.json"


def read_pace(now: float):
    """The pace a keeper measured in the last PACE_MAX_AGE_S seconds, or None."""
    d = read_json(pace_path(), {})
    try:
        if now - float(d["at"]) <= PACE_MAX_AGE_S and float(d["pace"]) > 0:
            return float(d["pace"])
    except (KeyError, TypeError, ValueError):
        pass
    return None


def event_key(e: dict) -> str:
    p = e.get("params") or {}
    return f"{e.get('action')}|{float(e.get('at_hours', 0)):.3f}|{p.get('name') or p.get('id') or e.get('note')}"


def merge_events(upcoming: list, cached: list, now_hours: float) -> list:
    """The schedule only lists what is still ahead; keep the events that already fired (from today's cache) so a late
    start still knows a duel wave is on. A cached future event missing from `upcoming` was moved or cancelled."""
    keys = {event_key(e) for e in upcoming}
    past = [e for e in cached if float(e.get("at_hours", 0)) <= now_hours and event_key(e) not in keys]
    return sorted(past + list(upcoming), key=lambda e: float(e.get("at_hours", 0)))


def matches(e: dict, sel: dict) -> bool:
    text = f"{e.get('note', '')} {(e.get('params') or {}).get('name', '')}".lower()
    return e.get("action") == sel.get("action") and str(sel.get("contains", "")).lower() in text


def check_gates(g: dict, clock: dict, events: list, lock_expiry, now: float) -> tuple[bool, str]:
    """(open, why) for a gate dict: doors_open and clock_running (both default on), no_duel_lock, duel_quiet_min,
    after_event."""
    h = float(clock.get("t_hours") or 0.0)
    if g.get("doors_open", True) and clock.get("doors") != "open":         # explicit values only: {} is closed
        return False, f"doors closed (next opening {clock.get('next_opens') or 'unknown'})"
    if g.get("clock_running", True) and clock.get("paused") is not False:
        return False, "clock paused"
    if g.get("no_duel_lock") and lock_expiry is not None and lock_expiry > now:
        return False, f"duel lock fresh for {lock_expiry - now:.0f} s"
    quiet = g.get("duel_quiet_min")
    if quiet:
        for e in events:
            at = float(e.get("at_hours", 0))
            if e.get("action") == "duels" and h - 0.05 <= at <= h + quiet / 60.0:
                return False, f"{(e.get('params') or {}).get('name', 'duels')} at {at:.3f} h is within {quiet} min"
    after = g.get("after_event")
    if after:
        hits = [float(e["at_hours"]) for e in events if matches(e, after)]
        if not hits:
            return False, f"waiting for {after.get('action')} (not in the schedule)"
        at = min(hits) + float(after.get("delay_min", 0)) / 60.0
        if h < at:
            return False, f"waiting for {after.get('action')} at {at:.3f} h"
    return True, "open"


def session_pick(sess: dict, events: list, now_hours: float):
    """(event, open) for a duel session: open from lead_min before the event to window_min after it, in game hours."""
    lead, win = float(sess.get("lead_min", 10)) / 60.0, float(sess.get("window_min", 120)) / 60.0
    hits = [e for e in events if matches(e, sess.get("event") or {"action": "duels"})]
    for e in hits:
        if float(e["at_hours"]) - lead <= now_hours < float(e["at_hours"]) + win:
            return e, True
    ahead = [e for e in hits if float(e["at_hours"]) - lead > now_hours]
    return (ahead[0] if ahead else None), False


def session_gate(sess: dict, clock: dict, events: list, now: float, pace=None):
    """(event, open, why). WHETHER the session is open is decided in game hours only (session_pick: the game clock
    against the event's game hour, whatever the pace). On top of that the wave's projected wall time must fall inside
    opening hours, so a pause that pushes a wave past the close stops a launch that could only idle; that projection
    uses the measured `pace`, and with none it uses PACE_FASTEST (the earliest the wave could come), so an unknown pace
    can never refuse a launch that a real one would allow."""
    ev, is_open = session_pick(sess, events, float(clock.get("t_hours") or 0.0))
    if not ev:
        return None, False, "no duel wave in the schedule"
    name = (ev.get("params") or {}).get("name", "duels")
    wall, _ = to_wall(float(ev["at_hours"]), clock, events, now, pace or PACE_FASTEST)
    if clock.get("days") and not day_of(clock, wall):
        return ev, False, f"{name} projected at {hhmm(wall, day=True)}, outside opening hours: not launching"
    if not is_open:
        return ev, False, f"next duel wave {name} at {float(ev['at_hours']):.3f} h"
    return ev, True, "duel window open"


def until_for(clock: dict, wall: float, margin_min: float) -> str:
    """--until HH:MM (Madrid) for a run on the day that contains `wall`: that day's closing time plus a margin."""
    d = day_of(clock, wall)
    closes = iso_epoch((d or {}).get("closes") or clock.get("closes"))
    return hhmm(closes + margin_min * 60) if closes else "23:59"


def render(argv: list, ctx: dict) -> list:
    """Fill {python}, {until}, {params}, {duel_ticks}, {idle_ticks}, {config}, {date}; an unknown name is an error."""
    try:
        return [str(a).format_map(ctx) for a in argv]
    except KeyError as e:
        raise ValueError(f"unknown placeholder {e} in {argv}") from None


def is_stale(age_s, stale_ticks, tick_seconds: float, floor_s: float = 30.0) -> bool:
    """A log is stale after stale_ticks ticks without a line (never under floor_s): 4 ticks is 60 s at 15 s ticks."""
    return stale_ticks is not None and age_s is not None and age_s > max(floor_s, stale_ticks * tick_seconds)


def bench_sessions(rows: list) -> list:
    """Every Market Test seen in the broker log, oldest first: bench run id, first and last tick with its offers on
    our book, and matched / dropped counts for pairs holding one of THAT run's offers (ids like "b36-17"), so a
    public fill during a test does not count. `live`: the last book still shows bench offers."""
    out, live = [], False
    for e in rows:
        ev, t = e.get("event"), e.get("tick")
        if ev == "book":
            offers = (e.get("book") or {}).get("bench_offers") or []
            live = bool(offers)
            if offers:
                bench = str(offers[0].get("id", "?")).split("-")[0]
                if not out or out[-1]["bench"] != bench:
                    out.append({"bench": bench, "first": t, "last": t, "matched": 0, "dropped": 0, "live": False})
                out[-1]["last"] = t
        elif ev in ("matched", "dropped"):
            ids = [str(x) for x in [e.get("sell"), e.get("buy"), *(e.get("match") or [])]]
            for sess in out:
                if any(i.startswith(sess["bench"] + "-") for i in ids):
                    sess[ev] += 1
    if out:
        out[-1]["live"] = live
    return out


def bench_summary(rows: list):
    sessions = bench_sessions(rows)
    return sessions[-1] if sessions else None


def bench_alerts(s, tick, no_match_ticks: int = 6, hold_ticks: int = 20) -> list:
    """Problems with the last Market Test while it runs and for hold_ticks after it: any dropped match, or no match
    after no_match_ticks ticks (b36 on Saturday: 15 dropped, 0 matched, the whole session lost)."""
    if not s or tick is None or (not s["live"] and tick - s["last"] > hold_ticks):
        return []
    out = []
    if s["dropped"]:
        out.append(f"broker dropped {s['dropped']} matches in Market Test {s['bench']}")
    if not s["matched"] and (not s["live"] or tick - s["first"] >= no_match_ticks):
        out.append(f"broker has no match in Market Test {s['bench']} after {tick - s['first']} ticks")
    return out


def missed_tests(events: list, sessions: list, clock: dict, start_ticks: int = 4, hold_ticks: int = 20,
                 pace: float = 1.0) -> list:
    """Market Tests the schedule says are running (or ended under hold_ticks ago) that never showed on our book: the
    broker is down, reads the wrong venue, or the venue is closed. Game hours map to ticks at the current length and
    pace (game hours per wall hour; 2.0 means a tick carries twice tick_seconds of game time)."""
    tick, h = clock.get("tick"), float(clock.get("t_hours") or 0.0)
    ts = float(clock.get("tick_seconds") or 15.0)
    if not isinstance(tick, int) or clock.get("doors", "open") != "open":
        return []
    out = []
    for e in events:
        if e.get("action") != "bench":
            continue
        n = int((e.get("params") or {}).get("ticks", 16))
        start = tick - round((h - float(e["at_hours"])) * 3600.0 / (ts * (pace or 1.0)))
        if start + start_ticks <= tick <= start + n + hold_ticks and \
                not any(x["last"] >= start - 2 and x["first"] <= start + n + 2 for x in sessions):
            out.append(f"Market Test at {float(e['at_hours']):.3f} h not on our book after {tick - start} ticks")
    return out


def ps_pids(lines: list, match: list, exclude: list = ()) -> list:
    """Processes running a bot, decided from argv strings only (no file is ever opened). A match is the script's
    BASENAME plus the mode tokens, whatever the path form: `agent/broker.py run`, `cd agent; python3 broker.py run`,
    `python3 -m agent.broker run`, or a shell -c restart loop around any of them. `--x=y` counts as `--x y`. Our own
    keepers' shells and other programs (an agent quoting the command) are ignored. A shell loop kept in a script file
    is visible only while its child runs (the runbook says to stop those by hand)."""
    def hit(toks, n):
        base = os.path.basename(n)
        mod = base[:-3] if base.endswith(".py") else None
        return any(os.path.basename(t) == base or (mod and i and toks[i - 1] == "-m" and t.split(".")[-1] == mod)
                   for i, t in enumerate(toks))
    out = []
    for line in lines:
        parts = line.split()
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        prog = os.path.basename(parts[1]).lower().lstrip("-")
        if not (prog.startswith("python") or (prog in SHELLS and "factory.py" not in line)):
            continue
        toks = [t for t in re.split(r"[\s;|&()<>'\"`=]+", " ".join(parts[2:])) if t]
        if all(hit(toks, m) for m in match) and not any(hit(toks, x) for x in exclude):
            out.append(int(parts[0]))
    return out


def refuse_reason(name: str, windows: set, keeper_alive: bool, pids: list):
    if name in windows:
        return f"tmux window {name!r} already exists"
    if keeper_alive:
        return "its factory keeper is already running"
    if pids:
        return f"already running outside the factory (pid {', '.join(map(str, pids))})"
    return None


def pending_steps(p: dict, done: list) -> list:
    return [s for s in p.get("steps") or [] if s.get("enabled", True) and s["label"] not in done]


def step_done(rows: list) -> bool:
    """A dealer step is done only on an explicit marker in the lines its run added to the dealer's log: a deal
    (`result` with status `deal`) or nothing to do (`run_start` with an empty `plan`). Exit 0 without one, such as
    a start refused by a fresh duel lock, is not done."""
    return any((e.get("event") == "result" and e.get("status") == "deal") or
               (e.get("event") == "run_start" and e.get("plan") == []) for e in rows)


def duel_stale(age_s, since_wave_s, lock_present: bool, tick_s: float, stale_ticks: int, start_ticks: int = 6) -> bool:
    """A duel run is stale while a scheduled wave is live (since_wave_s: seconds since it began, None outside the
    window) when nothing was logged since the wave began after start_ticks ticks, or when our duel lock exists (the
    bot thinks a duel is live and logs every tick) but the log is silent for stale_ticks ticks. Quiet after our
    duels end (lock removed) is fine."""
    if since_wave_s is None:
        return False
    if since_wave_s >= start_ticks * tick_s and (age_s is None or age_s > since_wave_s):
        return True
    return lock_present and age_s is not None and age_s > stale_ticks * tick_s


def problem_key(text: str) -> str:
    """A stable id for a problem: its text without numbers, so ages and counters do not make a new incident."""
    return re.sub(r"\d+(?:\.\d+)?", "#", text)


def child_env(extra: dict, environ) -> dict:
    """A bot's environment: an allowlist from ours plus the config's `env`; never a key (bots read their own .env)."""
    env = {k: environ[k] for k in SAFE_ENV if k in environ}
    for k, v in (extra or {}).items():
        if SECRETISH.search(k):
            raise SystemExit(f"config env {k} looks like a secret; the bots read their own .env")
        env[k] = str(v)
    return env


# --- I/O ------------------------------------------------------------------------------------------------------------

def load_config(path) -> dict:
    cfg = json.loads(Path(path).read_text())
    names = [p["name"] for p in cfg["processes"]]
    if len(names) != len(set(names)):
        raise SystemExit(f"{path}: duplicate process names")
    return cfg


def get(cfg: dict, path: str) -> dict:
    base = os.environ.get("BAZAAR_URL") or cfg.get("base_url", "https://bazaar.causaprima.ai")
    req = urllib.request.Request(base.rstrip("/") + "/api/" + path, headers={"User-Agent": "team3-factory"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def today() -> str:
    return time.strftime("%Y-%m-%d")


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, data) -> None:
    """Atomic write through a temp file of our own (keepers share the schedule cache: one shared .tmp name raced)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(data, indent=1))
    os.replace(tmp, path)


def cached_events(cache) -> list:
    data = read_json(cache, [])
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def events_now(cfg: dict, clock: dict, save: bool) -> list:
    """Upcoming events plus today's cache of the ones that already fired. Never raises: the save re-reads the cache
    just before writing (another keeper may have written since) and a failed save is skipped."""
    cache = STATE / f"schedule-{today()}.json"
    try:
        upcoming = get(cfg, "schedule").get("upcoming") or []
    except Exception:
        return cached_events(cache)
    h = float(clock.get("t_hours") or 0.0)
    merged = merge_events(upcoming, cached_events(cache), h)
    if save:
        try:
            write_json(cache, merge_events(upcoming, cached_events(cache), h))
        except OSError:
            pass
    return merged


def lock_expiry():
    try:
        return float(LOCK.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def ps_lines() -> list:
    try:
        return subprocess.run(["ps", "-axo", "pid=,args="], capture_output=True, text=True, timeout=10).stdout.splitlines()
    except Exception:
        return []


def pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def acquire_singleton(name: str):
    """Take results/factory/<name>.lock (flock) for this keeper's life; the OS frees it if the keeper dies. None if
    another keeper holds it. The fd is not inherited by the bots."""
    STATE.mkdir(parents=True, exist_ok=True)
    fd = os.open(STATE / f"{name}.lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


def singleton_held(name: str) -> bool:
    path = STATE / f"{name}.lock"
    if not path.exists():
        return False
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def missing_inputs(p: dict) -> list:
    return [x for x in [p.get("params"), *(p.get("requires") or [])] if x and not (ROOT / x).exists()]


def tmux_windows(session: str) -> set:
    r = subprocess.run(["tmux", "list-windows", "-t", session, "-F", "#{window_name}"], capture_output=True, text=True)
    return set(r.stdout.split()) if r.returncode == 0 else set()


def bus(cfg: dict, action: str, thing: str) -> int:
    """tools/bus.py claim/release; 0 ok, 4 held by someone else, anything else: bus unreachable."""
    b = cfg.get("bus")
    if not b:
        return 0
    argv = [sys.executable, str(ROOT / "tools" / "bus.py"), "--session", b["session"], action, thing]
    if action == "claim":
        argv += ["--where", b.get("where", ""), "--note", "factory.py"]
    env = {**child_env({}, os.environ), **{k: os.environ[k] for k in ("GH_TOKEN", "GITHUB_TOKEN", "GH_HOST",
                                                                          "GH_CONFIG_DIR") if k in os.environ}}
    try:
        return subprocess.run(argv, cwd=ROOT, env=env, timeout=90).returncode
    except Exception:
        return 1


def bus_board(cfg: dict):
    """{thing: (who, where)} from `tools/bus.py board`, or None if it cannot be read. The bus compares GitHub logins
    only, so this is how the factory sees a claim made from another machine on the same login."""
    b = cfg.get("bus")
    if not b:
        return {}
    env = {**child_env({}, os.environ), **{k: os.environ[k] for k in ("GH_TOKEN", "GITHUB_TOKEN", "GH_HOST",
                                                                          "GH_CONFIG_DIR") if k in os.environ}}
    try:
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "bus.py"), "--session", b["session"], "board"],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in r.stdout.splitlines()
            if line.startswith("|")]
    return {row[0].lower(): (row[1], row[2]) for row in rows if len(row) >= 3 and row[0] not in ("What", "---")}


def state_of(name: str) -> dict:
    st = read_json(STATE / f"{name}.json", {})
    return st if st.get("date") == today() else {}


def context(cfg: dict, cfg_path, p: dict, clock: dict, events: list, now: float) -> dict:
    """Placeholder values for one process. A session takes duel_ticks from its schedule event and an idle budget that
    covers its window at that day's tick length; --until is the closing time of the day the run starts in."""
    ctx = {"python": cfg.get("python") or sys.executable, "config": str(cfg_path), "date": today(),
           "params": p.get("params", ""), "duel_ticks": "?", "idle_ticks": "?"}
    wall = now
    if p.get("kind") == "session":
        ev, _ = session_pick(p.get("session") or {}, events, float(clock.get("t_hours") or 0.0))
        if ev:
            wall = max(now, to_wall(float(ev["at_hours"]), clock, events, now)[0])
            tick_s = float((day_of(clock, wall) or clock).get("tick_seconds") or 15.0)
            ctx["duel_ticks"] = (ev.get("params") or {}).get("duel_ticks", "?")
            ctx["idle_ticks"] = math.ceil(float(p["session"].get("window_min", 120)) * 60.0 / tick_s)
    ctx["until"] = until_for(clock, wall, float(cfg.get("until_margin_min", 5)))
    return ctx


def launch_check(p: dict, step, clock: dict, events: list, now: float, skip=(), pace=None) -> tuple[bool, str]:
    """(ok, why), evaluated before EVERY launch, restarts included: the gates, the duel session (inside opening
    hours), and no copy of the bot running outside the factory."""
    ok, why = check_gates(gates_for(p, step), clock, events, lock_expiry(), now)
    if ok and p["kind"] == "session":
        _, ok, why = session_gate(p["session"], clock, events, now, pace)
    if ok:
        others = [x for x in ps_pids(ps_lines(), p.get("match") or [], p.get("exclude") or []) if x not in skip]
        if others:
            ok, why = False, f"another copy runs outside the factory (pid {', '.join(map(str, others))})"
    return ok, why


def gates_for(p: dict, step=None) -> dict:
    g = dict(p.get("gates") or {})
    if step and step.get("after_event"):
        g["after_event"] = step["after_event"]
    return g


def describe(g: dict) -> str:
    parts = [v for k, v in GATE_NAMES.items() if g.get(k, GATE_DEFAULTS.get(k, False))]
    if g.get("duel_quiet_min"):
        parts.append(f"no duel wave within {g['duel_quiet_min']} min")
    return ", ".join(parts) or "none"


# --- plan -----------------------------------------------------------------------------------------------------------

def cmd_plan(cfg: dict, cfg_path, pace_arg=None) -> int:
    now = time.time()
    try:
        clock = get(cfg, "clock")
    except Exception as e:
        print(f"cannot read /api/clock ({type(e).__name__}): no plan")
        return 1
    events, h = events_now(cfg, clock, save=False), float(clock.get("t_hours") or 0.0)
    tick_s = float(clock.get("tick_seconds") or 15.0)
    ref_day = day_of(clock, now) or day_of(clock, iso_epoch(clock.get("next_opens")) or now)
    day_s = float((ref_day or clock).get("tick_seconds") or tick_s)
    shown = cfg_path.relative_to(ROOT) if cfg_path.is_relative_to(ROOT) else cfg_path
    print(f"factory plan  {hhmm(now, day=True)} Madrid  config {shown}  (read-only: starts nothing)")
    print(f"clock  tick {clock.get('tick')}  game {h:.3f} h  {tick_s:g} s ticks  round {clock.get('round')} "
          f"({clock.get('round_name')})  doors {clock.get('doors')}  closes "
          f"{hhmm(iso_epoch(clock['closes']), day=True) if clock.get('closes') else '?'}")
    measured = None if pace_arg else read_pace(now)
    known = pace_arg or measured
    assumed = float(cfg.get("pace_assumed") or 1.0)
    pace = known or assumed
    if pace_arg:
        print(f"pace {pace_arg:g} game hours per wall hour (--pace): the wall times below are estimates at that pace")
    elif measured:
        print(f"pace {measured:.2f} game hours per wall hour, measured by the keepers from the live clock: the wall times "
              f"below are estimates at that pace (Madrid). Bots act on game events, not on them.")
    else:
        print(f"pace NOT MEASURED yet (no keeper has seen the clock run): the wall times below assume {assumed:g} game "
              f"hours per wall hour (config pace_assumed: Sunday's published table fits about 2). They are estimates, "
              f"and a pause is not modelled, so they can be off by an hour. The published table (Madrid) is the "
              f"reference; bots act on game events.")
    if clock.get("paused"):
        print("PAUSED: game time is stopped; wall times marked + are the earliest and move later with every paused minute")
    if clock.get("doors", "open") != "open":
        print(f"DOORS CLOSED: nothing ticks until {clock.get('next_opens')}; wall times count from that opening")
    if datetime.now().astimezone().utcoffset() != datetime.now(MADRID).utcoffset():
        print("WARNING: this machine is not on Madrid time, and duel.py / rastro_seller.py read --until as local time")
    print(f"\nschedule (game hour, Madrid wall time, ticks away at {day_s:g} s, the tick length of the open day)")
    for e in events:
        at = float(e.get("at_hours", 0))
        if at < h - 0.5:
            continue
        wall, early = (iso_epoch(e["wall"]), False) if e.get("wall") else to_wall(at, clock, events, now, pace)
        d = day_of(clock, wall)
        ticks = f"{ticks_until(at, h, day_s, pace):>5} ticks" if d and d is ref_day and at >= h else " " * 11
        flag = ""
        if e.get("action") not in ("day_opens", "day_closes") and not d:
            flag = "  OUTSIDE OPENING HOURS: runs only if the organisers move it"
        name = (e.get("params") or {}).get("name") or e.get("note", "")
        print(f"  {at:7.3f}  {hhmm(wall, day=True)}{'+' if early else ' '} {ticks}  {e.get('action'):<13} {name[:58]}{flag}")
    ps = ps_lines()
    print(f"\nprocesses (tmux session {cfg.get('tmux_session', 'factory')!r}; each window runs factory.py keep <name>)")
    for p in cfg["processes"]:
        if not p.get("enabled", True):
            print(f"  {p['name']:<13} OFF   {p.get('note') or p.get('todo') or ''}"[:118])
            for s_ in p.get("steps") or []:           # the manual command list for a class up does not start
                print(f"      manual{'' if s_.get('enabled', True) else ' (off)'} {s_['label']}: "
                      f"{shlex.join(render(s_['cmd'], context(cfg, cfg_path, p, clock, events, now)))}")
            continue
        g = gates_for(p)
        ok, why = check_gates(g, clock, events, lock_expiry(), now)
        others = ps_pids(ps, p.get("match") or [], p.get("exclude") or [])
        req = "required" if p.get("required") else "optional"
        print(f"  {p['name']:<13} {p['kind']:<8} {req}  gate: {describe(g)} -> {'open' if ok else why}")
        if others:
            print(f"      ALREADY RUNNING outside the factory: pid {', '.join(map(str, others))} (up will refuse it)")
        ctx = context(cfg, cfg_path, p, clock, events, now)
        if p["kind"] == "session":
            ev, _, why_s = session_gate(p["session"], clock, events, now, known)
            w, early = to_wall(float(ev["at_hours"]), clock, events, now, pace) if ev else (now, False)
            when = f" ({hhmm(w, day=True)}{'+' if early else ''})" if ev else ""
            print(f"      session: {why_s}{when}; starts {p['session'].get('lead_min', 10)} min before, "
                  f"window {p['session'].get('window_min', 120)} min")
        for m in missing_inputs(p):
            print(f"      MISSING input file {m} (up refuses this process until it exists)")
        steps = p.get("steps") or [{"label": "", "cmd": p["cmd"]}]
        for s in steps:
            if p["kind"] == "steps":
                after = s.get("after_event")
                hits = [x for x in events if after and matches(x, after)]
                when = ""
                if hits:
                    w, early = to_wall(float(hits[0]["at_hours"]) + float(after.get("delay_min", 0)) / 60, clock, events,
                                       now, pace)
                    when = f"  after {after['action']} ({hhmm(w, day=True)}{'+' if early else ''})"
                state = "" if s.get("enabled", True) else "  OFF"
                print(f"    - {s['label']}{state}{when}")
            print(f"      {shlex.join(render(s['cmd'], ctx))}")
            if s.get("todo"):
                print(f"      TODO {s['todo']}")
        if p.get("todo"):
            print(f"      TODO {p['todo']}")
    return 0


# --- up -------------------------------------------------------------------------------------------------------------

def cmd_up(cfg: dict, cfg_path, yes: bool, no_bus: bool = False) -> int:
    if not yes:
        rc = cmd_plan(cfg, cfg_path)
        print("\ndry run: nothing started. `up --yes` starts every enabled process that is not already running.")
        return rc
    if not shutil.which("tmux"):
        raise SystemExit("tmux not found")
    session = cfg.get("tmux_session", "factory")
    if subprocess.run(["tmux", "has-session", "-t", session], capture_output=True).returncode != 0:
        subprocess.run(["tmux", "new-session", "-d", "-s", session, "-n", "home", "-c", str(ROOT)], check=True)
    windows, ps, bad = tmux_windows(session), ps_lines(), 0
    board = {} if no_bus else bus_board(cfg)
    for p in cfg["processes"]:
        name = p["name"]
        if not p.get("enabled", True):
            print(f"off     {name}: {p.get('note') or 'disabled in the config'}")
            continue
        st = state_of(name)
        if p["kind"] == "steps" and not pending_steps(p, st.get("done_steps", [])):
            print(f"skip    {name}: no enabled step left to run today")
            continue
        missing = missing_inputs(p)
        why = (f"missing input file {', '.join(missing)}" if missing else
               refuse_reason(name, windows, singleton_held(name),
                             ps_pids(ps, p.get("match") or [], p.get("exclude") or [])))
        thing, where = p.get("bus_thing", name), (cfg.get("bus") or {}).get("where", "")
        if not why and not no_bus and board is None:
            why = "cannot read the bus board, not started; if GitHub is down, run `up --yes --no-bus`"
        elif not why and not no_bus and thing in board and board[thing][1] != where:
            who, there = board[thing]
            why = f"{who} holds {thing!r} on {there or 'an unnamed machine'}: stop it there and release it first"
        if not why and not no_bus:
            rc = bus(cfg, "claim", thing)
            if rc == 4:
                why = f"someone else holds {p.get('bus_thing', name)!r} on the bus"
            elif rc != 0:
                why = (f"bus claim failed (rc {rc}), not started; if GitHub is down, say so in the team chat and run "
                       f"`up --yes --no-bus`")
        if why:
            print(f"REFUSE  {name}: {why}")
            bad += 1
            continue
        keeper = [cfg.get("python") or sys.executable, "-u", "tools/factory.py", "keep", name, "--config",
                  str(cfg_path)] + (["--no-bus"] if no_bus else [])
        subprocess.run(["tmux", "new-window", "-d", "-t", f"{session}:", "-n", name, "-c", str(ROOT),
                        shlex.join(keeper)], check=True)
        print(f"started {name}: tmux window {session}:{name}")
    return 1 if bad else 0


# --- keep (what each tmux window runs) --------------------------------------------------------------------------------

def cmd_keep(cfg_path, name: str, no_bus: bool = False) -> int:
    lock_fd = acquire_singleton(name)
    if lock_fd is None:
        print(f"{name}: another keeper holds {STATE / (name + '.lock')}; this one exits", flush=True)
        return 3
    out = open(STATE / f"{name}.out", "a", buffering=1)
    st = state_of(name) or {"date": today()}
    st.setdefault("done_steps", [])
    st["failed_steps"], st["attempts"] = [], {}   # starting a keeper (up --yes) is the go to rerun a failed step
    st.update(name=name, keeper_pid=os.getpid(), child_pid=None, state="waiting")
    child, cfg, backoff = None, load_config(cfg_path), 2.5

    def say(msg):
        line = f"{time.strftime('%H:%M:%S')} [factory] {msg}\n"
        out.write(line)
        print(line, end="", flush=True)

    def pump(src):
        for raw in iter(src.readline, b""):
            text = raw.decode("utf-8", "replace")
            out.write(text)
            sys.stdout.write(text)
            sys.stdout.flush()

    def save(**kw):
        st.update(kw, updated=time.time())
        write_json(STATE / f"{name}.json", st)

    def stop(signum, _frame):
        raise SystemExit(128 + signum)

    for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(s, stop)
    events, events_at = [], 0.0
    meter, pace_written = PaceMeter(), [0.0]

    def note_clock(c):
        """Feed the pace meter and share what it measured (plan and status read it); never an input to a launch gate
        except the opening-hours projection of a duel wave, which uses it only to be less strict."""
        meter.update(time.time(), c)
        measured = meter.pace
        if measured and time.time() - pace_written[0] >= 30:
            pace_written[0] = time.time()
            try:
                write_json(pace_path(), {"pace": round(measured, 3), "at": time.time(), "tick": c.get("tick"),
                                         "t_hours": c.get("t_hours")})
            except OSError:
                pass
    try:
        while True:
            cfg = load_config(cfg_path)
            p = next((x for x in cfg["processes"] if x["name"] == name), None)
            if p is None or not p.get("enabled", True):
                save(state="stopped", why="disabled in the config", child_pid=None)
                say("disabled in the config: not launching")
                return 0
            if missing_inputs(p):
                save(state="failed", why=f"missing input {', '.join(missing_inputs(p))}", child_pid=None)
                say(st["why"])
                return 1
            try:
                clock = get(cfg, "clock")
            except Exception as e:
                save(state="waiting", why=f"clock unreachable ({type(e).__name__})")
                time.sleep(10)
                continue
            now = time.time()
            note_clock(clock)
            if now - events_at > 60:
                events, events_at = events_now(cfg, clock, save=True), now
            step = None
            if p["kind"] == "steps":
                left = pending_steps(p, st["done_steps"] + st["failed_steps"])
                if not left:
                    save(state="done", why="no enabled step left", child_pid=None)
                    say("all enabled steps done")
                    return 0
                step = left[0]
            ok, why = launch_check(p, step, clock, events, now, skip={os.getpid(), os.getppid()}, pace=meter.pace)
            if not ok:
                save(state="waiting", why=why, step=step and step["label"], child_pid=None)
                time.sleep(10)
                continue
            argv = render((step or p)["cmd"], context(cfg, cfg_path, p, clock, events, now))
            log = ROOT / p["log"].format(date=today()) if p.get("log") else None
            offset = log.stat().st_size if log and log.exists() else 0
            env = child_env(cfg.get("env"), os.environ)
            say(f"start {shlex.join(argv)}")
            child = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            reader = threading.Thread(target=pump, args=(child.stdout,), daemon=True)
            reader.start()
            save(state="running", why=why, step=step and step["label"], child_pid=child.pid, started=now,
                 paused_during_run=False)
            last_clock = now
            while child.poll() is None:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                if time.time() - last_clock >= 15:
                    last_clock = time.time()
                    try:
                        live = get(cfg, "clock")
                        note_clock(live)
                        if live.get("paused") and not st.get("paused_during_run"):
                            save(paused_during_run=True)
                            say("the clock paused while this run is live")
                    except Exception:
                        pass
            reader.join(timeout=5)
            rc, ran, child = child.returncode, time.time() - now, None
            say(f"exit rc={rc} after {ran:.0f} s")
            if step is not None:
                if rc != 0:      # lock_timeout, close_failed, all buys blocked, a crash: a person decides
                    st["failed_steps"].append(step["label"])
                    save(state="failed", why=f"step {step['label']} exited rc={rc}: not relaunched", last_rc=rc,
                         child_pid=None)
                    say(f"step {step['label']} exited rc={rc}: not relaunched; check the log, then up --yes")
                    return 1
                rows = []
                if log and log.exists():
                    with open(log, "rb") as fh:
                        fh.seek(offset)
                        for raw in fh.read().splitlines():
                            try:
                                rows.append(json.loads(raw))
                            except ValueError:
                                pass
                if step_done(rows):
                    st["done_steps"].append(step["label"])
                else:
                    tries = st.setdefault("attempts", {})
                    tries[step["label"]] = tries.get(step["label"], 0) + 1
                    if tries[step["label"]] >= int(p.get("max_attempts", 3)):
                        st["failed_steps"].append(step["label"])
                        save(state="failed", child_pid=None, last_rc=rc,
                             why=f"step {step['label']} ran {tries[step['label']]} times without a deal or "
                                 f"nothing-to-do marker: not relaunched")
                        say(st["why"])
                        return 1
            st["restarts"] = st.get("restarts", 0) + 1
            save(state="waiting", why=f"exited rc={rc}", last_rc=rc, child_pid=None)
            backoff = 5.0 if ran > 300 else min(backoff * 2, 120.0)     # 5, 10, 20 ... 120 s while it keeps dying
            time.sleep(2 if (step and rc == 0) else backoff)
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
        if st.get("state") not in ("done", "failed"):
            save(state="stopped", child_pid=None)
        if not no_bus:
            p = next((x for x in cfg["processes"] if x["name"] == name), {})
            bus(cfg, "release", p.get("bus_thing", name))
        say("keeper stopped")
        os.close(lock_fd)


# --- status ---------------------------------------------------------------------------------------------------------

def observe(p: dict, ps: list) -> tuple[dict, bool, bool]:
    """(state, keeper alive, child alive): the keeper by its lock, the child by its pid AND its command line."""
    st = state_of(p["name"])
    pid = st.get("child_pid")
    child = pid_alive(pid) and (not p.get("match") or pid in ps_pids(ps, p["match"], p.get("exclude") or []))
    return st, singleton_held(p["name"]), bool(child)


def status_once(cfg: dict) -> tuple[list, list]:
    """(lines, problems): one line per process; problems are what makes the exit code 1."""
    lines, problems, now = [], [], time.time()
    try:
        clock = get(cfg, "clock")
    except Exception as e:
        clock = {}
        problems.append(f"clock unreachable ({type(e).__name__})")
    tick_s = float(clock.get("tick_seconds") or 15.0)
    live_clock = clock.get("doors") == "open" and not clock.get("paused")
    events = events_now(cfg, clock, save=True) if clock else []
    ps = ps_lines()
    head = f"tick {clock.get('tick')} {tick_s:g} s, doors {clock.get('doors')}{', PAUSED' if clock.get('paused') else ''}"
    lines.append(f"{hhmm(now)}  {head}")
    for p in cfg["processes"]:
        name = p["name"]
        st, keeper, child = observe(p, ps)
        if not p.get("enabled", True):
            lines.append(f"  {name:<13} off{'  STILL RUNNING' if keeper or child else ''}")
            if keeper or child:
                problems.append(f"{name} is disabled in the config but still runs (keeper {keeper}, child "
                                f"{st.get('child_pid') if child else 'none'}): stop its window")
            continue
        if keeper and not child and st.get("state") == "running":      # maybe an exit the keeper has not seen yet
            time.sleep(RECHECK_S)
            ps = ps_lines()
            st, keeper, child = observe(p, ps)
        state, need = st.get("state", "never started"), p.get("required")
        left = pending_steps(p, st.get("done_steps", []) + st.get("failed_steps", []))
        if keeper:
            word = "RUNNING" if child else ("NO CHILD" if state == "running" else "WAITING")
        else:
            word = "FAILED" if state == "failed" else ("DONE" if p["kind"] == "steps" and not left else "DOWN")
        log = ROOT / str(p.get("log", "")).format(date=today()) if p.get("log") else None
        age = now - log.stat().st_mtime if log and log.exists() else None
        line = (f"  {name:<13} {word:<8} log {f'{age:.0f} s ago' if age is not None else '-':<10} "
                f"restarts {st.get('restarts', 0)}  {st.get('step') or ''} {st.get('why', '')}")
        if need and word in ("DOWN", "NO CHILD"):
            problems.append(f"{name} is down" if word == "DOWN" else
                            f"{name}: keeper says running but child pid {st.get('child_pid')} is gone")
        if word == "FAILED":
            problems.append(f"{name}: {st.get('why')}")
        if keeper and "outside the factory" in st.get("why", ""):
            problems.append(f"{name}: {st['why']}")
        if need and keeper and not child and st.get("last_rc") not in (None, 0):
            problems.append(f"{name} exited rc={st['last_rc']}, restart {st.get('restarts', 0)} pending")
        grace = max(120.0, 2 * float(p.get("stale_ticks") or 4) * tick_s)
        if child and log and age is None and now - float(st.get("started") or now) > grace:
            line += "  NO LOG"
            if need:
                problems.append(f"{name}: no log at {p['log'].format(date=today())} after {now - st['started']:.0f} s")
        if p["kind"] == "session":       # fresh only while a scheduled wave is live (quiet between waves is normal)
            ev, _ = session_pick(p["session"], events, float(clock.get("t_hours") or 0.0))
            since = None
            if ev and live_clock:
                since = (float(clock["t_hours"]) - float(ev["at_hours"])) * 3600.0
                since = since if 0 <= since <= float(p["session"].get("window_min", 120)) * 60 else None
            if need and child and duel_stale(age, since, LOCK.exists(), tick_s, int(p.get("stale_ticks") or 8)):
                problems.append(f"{name} stale during {(ev.get('params') or {}).get('name', 'the duel wave')}: "
                                f"last log line {'never' if age is None else f'{age:.0f} s ago'}")
                line += "  STALE"
        elif need and child and live_clock and is_stale(age, p.get("stale_ticks"), tick_s):
            problems.append(f"{name} log silent for {age:.0f} s ({p['stale_ticks']} ticks at {tick_s:g} s)")
            line += "  STALE"
        if child and p["kind"] == "steps" and clock.get("paused"):
            problems.append(f"{name} dealer run live while the clock is paused")
        if p.get("bench_watch"):
            rows = []
            if log and log.exists():
                with open(log, "rb") as fh:
                    fh.seek(max(0, log.stat().st_size - 4_000_000))
                    for raw in fh.read().splitlines():
                        try:
                            rows.append(json.loads(raw))
                        except ValueError:
                            pass
            sessions = bench_sessions(rows)
            if sessions:
                s = sessions[-1]
                line += f"  Market Test {s['bench']}: matched {s['matched']} dropped {s['dropped']}{' LIVE' if s['live'] else ''}"
                problems += bench_alerts(s, clock.get("tick"))
            problems += missed_tests(events, sessions, clock, pace=read_pace(now) or 1.0)
        lines.append(line.rstrip())
    return lines, problems


def notify(cfg: dict, text: str) -> None:
    cmd = cfg.get("notify_cmd")
    if not cmd:
        print("(notify_cmd is not set in the config: nothing sent)")
        return
    try:
        subprocess.run(list(cmd) + [text], env=child_env({}, os.environ), timeout=60)
    except Exception as e:
        print(f"notify failed: {type(e).__name__}")


def cmd_status(cfg_path, do_notify: bool, every: float) -> int:
    sent = set()
    while True:
        cfg = load_config(cfg_path)
        lines, problems = status_once(cfg)
        print("\n".join(lines + [f"PROBLEM {x}" for x in problems] + (["ok"] if not problems else [])), flush=True)
        keys = {problem_key(x) for x in problems}       # one incident = one message, whatever its ages and counts
        if do_notify and keys != sent:
            notify(cfg, "Bazaar factory: " + "; ".join(problems) if problems else "Bazaar factory: all clear again")
            sent = keys
        if not every:
            return 1 if problems else 0
        time.sleep(every)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", nargs="?", default="plan", choices=["plan", "up", "status", "keep"])
    ap.add_argument("name", nargs="?", help="keep: the process to run (internal: what each tmux window runs)")
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--yes", action="store_true", help="up: really start (without it, up only prints the plan)")
    ap.add_argument("--notify", action="store_true", help="status: run notify_cmd with the problem text")
    ap.add_argument("--every", type=float, default=0, help="status: repeat every N seconds (notify on change only)")
    ap.add_argument("--no-bus", action="store_true", help="up/keep: skip the bus claim (only when GitHub is down)")
    ap.add_argument("--pace", type=float, default=None, help="plan: estimate wall times at this many game hours per wall "
                    "hour (default: what the keepers measured, else 1.0); the bots never use it")
    a = ap.parse_args()
    cfg_path = Path(a.config).resolve()
    cfg = load_config(cfg_path)
    if a.cmd == "plan":
        return cmd_plan(cfg, cfg_path, a.pace)
    if a.cmd == "up":
        return cmd_up(cfg, cfg_path, a.yes, a.no_bus)
    if a.cmd == "status":
        return cmd_status(cfg_path, a.notify, a.every)
    if not a.name:
        ap.error("keep needs a process name")
    return cmd_keep(cfg_path, a.name, a.no_bus)


if __name__ == "__main__":
    sys.exit(main())
