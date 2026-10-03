#!/usr/bin/env python3
"""Sunday factory: start Team 3's bots in the right order with the right flags, keep them up, report their health.

    python3 tools/factory.py plan                    # read-only (default): clock, schedule in wall time, commands, gates
    python3 tools/factory.py up                      # the same as plan: nothing starts without --yes
    python3 tools/factory.py up --yes                # one tmux window per process (session "factory")
    python3 tools/factory.py status [--notify] [--every 60]   # one line per process; exit 1 if anything required fails

The configuration is data: tools/factory_sunday.json (processes, commands, gates, required or optional). Each tmux
window runs `factory.py keep <name>`, the restart loop. It waits for the gates, runs the command, and on exit does what
the kind says: `service` restarts always, `session` (duels) restarts while the duel window is open, `steps` (dealers)
moves to the next step after a clean exit and retries a failed run or one that lived through a pause. It writes
results/factory/<name>.json (state) and <name>.out (output), and releases its bus claim when it stops. It re-reads
the config before every start, so tonight's and tomorrow's changes are edits to the JSON file.

No key: the factory calls only the keyless GET /api/clock and /api/schedule; the bots read their own .env (the
broker its ~/.bazaar/broker.env). Game text never reaches it: it reads only our own logs' event names and ticks.

Game hours and wall time, MEASURED in our logs: t_hours advances tick_seconds/3600 per tick (Friday ticks 21 to 47:
0.350 to 0.783 h at 60 s; Saturday ticks 265 to 266: 3.533 to 3.542 h at 30 s). While the clock runs, one game hour
is one wall hour at any tick length; only the number of ticks to an event scales with it. Game time stops while the
clock is paused or the doors are closed, so every gate here is evaluated in game hours (a pause freezes it), and wall
times printed during a pause are the earliest possible ones.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import shutil
import signal
import subprocess
import sys
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


def to_wall(at_hours: float, clock: dict, events: list, now: float) -> tuple[float, bool]:
    """(wall epoch, earliest) for a game hour. Anchored at (now, t_hours) while running, at the next opening while the
    doors are closed, and at the last known day opening before the event (game time stops overnight). `earliest` is
    True while the clock is paused: every paused minute moves the event one minute later."""
    h = float(clock.get("t_hours") or 0.0)
    wall, base = now, h
    if clock.get("doors", "open") != "open" and clock.get("next_opens"):
        wall = iso_epoch(clock["next_opens"])
    for e in sorted(events, key=lambda e: float(e.get("at_hours", 0))):
        at = float(e.get("at_hours", -1))
        if e.get("action") == "day_opens" and e.get("wall") and base <= at <= at_hours and iso_epoch(e["wall"]) >= wall:
            wall, base = iso_epoch(e["wall"]), at
    return wall + (at_hours - base) * 3600.0, bool(clock.get("paused")) and at_hours > h


def ticks_until(at_hours: float, now_hours: float, tick_seconds: float) -> int:
    return round((at_hours - now_hours) * 3600.0 / tick_seconds)


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
    """(open, why) for a gate dict: doors_open, clock_running, no_duel_lock, duel_quiet_min, after_event."""
    h = float(clock.get("t_hours") or 0.0)
    if g.get("doors_open") and clock.get("doors", "open") != "open":
        return False, f"doors closed (next opening {clock.get('next_opens') or 'unknown'})"
    if g.get("clock_running") and clock.get("paused"):
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


def bench_summary(rows: list):
    """The last Market Test seen in the broker log: bench id, first and last tick with bench offers on the book,
    matched and dropped counts in that span, and whether the last book still had bench offers (live)."""
    last, live = None, False
    for e in rows:
        ev, t = e.get("event"), e.get("tick")
        if ev == "book":
            offers = (e.get("book") or {}).get("bench_offers") or []
            live = bool(offers)
            if offers:
                bench = str(offers[0].get("id", "?")).split("-")[0]
                if last is None or last["bench"] != bench:
                    last = {"bench": bench, "first": t, "last": t, "matched": 0, "dropped": 0}
                else:
                    last["last"] = t
        elif ev in ("matched", "dropped") and last and isinstance(t, int) and last["first"] <= t <= last["last"] + 3:
            last[ev] += 1
    if last:
        last["live"] = live
    return last


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


def ps_pids(lines: list, match: list, exclude: list = ()) -> list:
    """Python processes whose argv holds every `match` token (a token equal to it, or a path ending in /it) and no
    `exclude` token. Only python argv[0] counts, so a shell or an agent whose prompt quotes the command is ignored."""
    def hit(toks, n):
        return any(t == n or t.endswith("/" + n) for t in toks)
    out = []
    for line in lines:
        parts = line.split()
        if len(parts) < 2 or not parts[0].isdigit() or not os.path.basename(parts[1]).lower().startswith("python"):
            continue
        toks = parts[2:]
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
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    os.replace(tmp, path)


def events_now(cfg: dict, clock: dict, save: bool) -> list:
    cache = STATE / f"schedule-{today()}.json"
    cached = read_json(cache, [])
    try:
        upcoming = get(cfg, "schedule").get("upcoming") or []
    except Exception:
        return cached
    merged = merge_events(upcoming, cached, float(clock.get("t_hours") or 0.0))
    if save:
        write_json(cache, merged)
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
    try:
        return subprocess.run(argv, cwd=ROOT, timeout=90).returncode
    except Exception:
        return 1


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


def gates_for(p: dict, step=None) -> dict:
    g = dict(p.get("gates") or {})
    if step and step.get("after_event"):
        g["after_event"] = step["after_event"]
    return g


def describe(g: dict) -> str:
    parts = [v for k, v in GATE_NAMES.items() if g.get(k)]
    if g.get("duel_quiet_min"):
        parts.append(f"no duel wave within {g['duel_quiet_min']} min")
    return ", ".join(parts) or "none"


# --- plan -----------------------------------------------------------------------------------------------------------

def cmd_plan(cfg: dict, cfg_path) -> int:
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
        wall, early = (iso_epoch(e["wall"]), False) if e.get("wall") else to_wall(at, clock, events, now)
        d = day_of(clock, wall)
        ticks = f"{ticks_until(at, h, day_s):>5} ticks" if d and d is ref_day and at >= h else " " * 11
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
            ev, is_open = session_pick(p["session"], events, h)
            if ev:
                w, early = to_wall(float(ev["at_hours"]), clock, events, now)
                print(f"      {'OPEN now' if is_open else 'next'}: {(ev.get('params') or {}).get('name')} at "
                      f"{float(ev['at_hours']):.3f} h ({hhmm(w, day=True)}{'+' if early else ''}), starts "
                      f"{p['session'].get('lead_min', 10)} min before, window {p['session'].get('window_min', 120)} min")
            if p.get("params") and not (ROOT / p["params"]).exists():
                print(f"      MISSING params file {p['params']}")
        steps = p.get("steps") or [{"label": "", "cmd": p["cmd"]}]
        for s in steps:
            if p["kind"] == "steps":
                after = s.get("after_event")
                hits = [x for x in events if after and matches(x, after)]
                when = ""
                if hits:
                    w, early = to_wall(float(hits[0]["at_hours"]) + float(after.get("delay_min", 0)) / 60, clock, events, now)
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

def cmd_up(cfg: dict, cfg_path, yes: bool) -> int:
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
    for p in cfg["processes"]:
        name = p["name"]
        if not p.get("enabled", True):
            continue
        st = state_of(name)
        if p["kind"] == "steps" and not pending_steps(p, st.get("done_steps", [])):
            print(f"skip    {name}: no enabled step left to run today")
            continue
        why = refuse_reason(name, windows, pid_alive(st.get("keeper_pid")),
                            ps_pids(ps, p.get("match") or [], p.get("exclude") or []))
        if why:
            print(f"REFUSE  {name}: {why}")
            bad += 1
            continue
        rc = bus(cfg, "claim", p.get("bus_thing", name))
        if rc == 4:
            print(f"REFUSE  {name}: someone else holds {p.get('bus_thing', name)!r} on the bus")
            bad += 1
            continue
        if rc != 0:
            print(f"WARN    {name}: bus unreachable (rc {rc}), starting anyway; say it in the team chat")
        keeper = [cfg.get("python") or sys.executable, "-u", "tools/factory.py", "keep", name, "--config", str(cfg_path)]
        subprocess.run(["tmux", "new-window", "-d", "-t", f"{session}:", "-n", name, "-c", str(ROOT),
                        shlex.join(keeper)], check=True)
        print(f"started {name}: tmux window {session}:{name}")
    return 1 if bad else 0


# --- keep (what each tmux window runs) --------------------------------------------------------------------------------

def cmd_keep(cfg_path, name: str) -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    out = open(STATE / f"{name}.out", "a", buffering=1)
    st = state_of(name) or {"date": today()}
    for k in ("done_steps", "failed_steps"):
        st.setdefault(k, [])
    st.update(name=name, keeper_pid=os.getpid(), child_pid=None, state="waiting")
    child, cfg, retries, backoff = None, load_config(cfg_path), {}, 2.5

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
    try:
        while True:
            cfg = load_config(cfg_path)
            p = next(x for x in cfg["processes"] if x["name"] == name)
            try:
                clock = get(cfg, "clock")
            except Exception as e:
                save(state="waiting", why=f"clock unreachable ({type(e).__name__})")
                time.sleep(10)
                continue
            now, h = time.time(), float(clock.get("t_hours") or 0.0)
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
            ok, why = check_gates(gates_for(p, step), clock, events, lock_expiry(), now)
            if ok and p["kind"] == "session":
                ev, ok = session_pick(p["session"], events, h)
                why = "duel window open" if ok else (f"next duel wave at {float(ev['at_hours']):.3f} h" if ev
                                                     else "no duel wave in the schedule")
            if not ok:
                save(state="waiting", why=why, step=step and step["label"], child_pid=None)
                time.sleep(10)
                continue
            argv = render((step or p)["cmd"], context(cfg, cfg_path, p, clock, events, now))
            env = {**os.environ, **{k: str(v) for k, v in (cfg.get("env") or {}).items()}}
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
                        if get(cfg, "clock").get("paused") and not st.get("paused_during_run"):
                            save(paused_during_run=True)
                            say("the clock paused while this run is live")
                    except Exception:
                        pass
            reader.join(timeout=5)
            rc, ran, child = child.returncode, time.time() - now, None
            say(f"exit rc={rc} after {ran:.0f} s")
            if step is not None:
                if rc == 0 and not st.get("paused_during_run"):
                    st["done_steps"].append(step["label"])
                else:
                    retries[step["label"]] = retries.get(step["label"], 0) + 1
                    if retries[step["label"]] > int(p.get("max_retries", 2)):
                        st["failed_steps"].append(step["label"])
                        say(f"step {step['label']} failed {retries[step['label']]} times: giving up on it")
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
        if st.get("state") != "done":
            save(state="stopped", child_pid=None)
        p = next((x for x in cfg["processes"] if x["name"] == name), {})
        bus(cfg, "release", p.get("bus_thing", name))
        say("keeper stopped")


# --- status ---------------------------------------------------------------------------------------------------------

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
    head = f"tick {clock.get('tick')} {tick_s:g} s, doors {clock.get('doors')}{', PAUSED' if clock.get('paused') else ''}"
    lines.append(f"{hhmm(now)}  {head}")
    for p in cfg["processes"]:
        name, st = p["name"], state_of(p["name"])
        if not p.get("enabled", True):
            lines.append(f"  {name:<13} off")
            continue
        keeper, child = pid_alive(st.get("keeper_pid")), pid_alive(st.get("child_pid"))
        state = st.get("state", "never started")
        left = pending_steps(p, st.get("done_steps", []) + st.get("failed_steps", []))
        word = ("RUNNING" if child else state.upper()) if keeper else ("DONE" if p["kind"] == "steps" and not left
                                                                       else "DOWN")
        log = ROOT / str(p.get("log", "")).format(date=today()) if p.get("log") else None
        age = now - log.stat().st_mtime if log and log.exists() else None
        line = (f"  {name:<13} {word:<8} log {f'{age:.0f} s ago' if age is not None else '-':<10} "
                f"restarts {st.get('restarts', 0)}  {st.get('step') or ''} {st.get('why', '')}")
        need = p.get("required")
        if need and word == "DOWN":
            problems.append(f"{name} is down")
        if need and keeper and not child and st.get("last_rc") not in (None, 0):
            problems.append(f"{name} exited rc={st['last_rc']}, restart {st.get('restarts', 0)} pending")
        if need and child and live_clock and is_stale(age, p.get("stale_ticks"), tick_s):
            problems.append(f"{name} log silent for {age:.0f} s ({p['stale_ticks']} ticks at {tick_s:g} s)")
            line += "  STALE"
        if child and p["kind"] == "steps" and clock.get("paused"):
            problems.append(f"{name} dealer run live while the clock is paused (it burns its rounds)")
        if st.get("failed_steps"):
            line += f"  failed steps: {', '.join(st['failed_steps'])}"
        if p.get("bench_watch") and log and log.exists():
            with open(log, "rb") as f:
                f.seek(max(0, log.stat().st_size - 4_000_000))
                rows = []
                for raw in f.read().splitlines():
                    try:
                        rows.append(json.loads(raw))
                    except ValueError:
                        pass
            s = bench_summary(rows)
            if s:
                line += f"  Market Test {s['bench']}: matched {s['matched']} dropped {s['dropped']}{' LIVE' if s['live'] else ''}"
                problems += bench_alerts(s, clock.get("tick"))
        lines.append(line.rstrip())
    return lines, problems


def notify(cfg: dict, text: str) -> None:
    cmd = cfg.get("notify_cmd")
    if not cmd:
        print("(notify_cmd is not set in the config: nothing sent)")
        return
    try:
        subprocess.run(list(cmd) + [text], timeout=60)
    except Exception as e:
        print(f"notify failed: {type(e).__name__}")


def cmd_status(cfg_path, do_notify: bool, every: float) -> int:
    sent = ""
    while True:
        cfg = load_config(cfg_path)
        lines, problems = status_once(cfg)
        print("\n".join(lines + [f"PROBLEM {x}" for x in problems] + (["ok"] if not problems else [])), flush=True)
        text = "Bazaar factory: " + "; ".join(problems) if problems else ""
        if do_notify and text != sent:
            notify(cfg, text or "Bazaar factory: all clear again")
            sent = text
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
    a = ap.parse_args()
    cfg_path = Path(a.config).resolve()
    cfg = load_config(cfg_path)
    if a.cmd == "plan":
        return cmd_plan(cfg, cfg_path)
    if a.cmd == "up":
        return cmd_up(cfg, cfg_path, a.yes)
    if a.cmd == "status":
        return cmd_status(cfg_path, a.notify, a.every)
    if not a.name:
        ap.error("keep needs a process name")
    return cmd_keep(cfg_path, a.name)


if __name__ == "__main__":
    sys.exit(main())
