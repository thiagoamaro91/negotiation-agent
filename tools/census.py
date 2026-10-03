"""Card census: who owns every card in the game, read one id at a time from GET /api/cards/{id}. Read only.

`/api/cards/{id}` answers any asset id (a card or a pack) with its ref, name, rarity, owner and history. Asset ids
are minted in order from 1, so walking them all gives an exact snapshot of every team's deck, where the feed-based
rebuild (tools/decks.py) only names the copies the public events showed.

    python3 tools/census.py run --out ~/bazaar-census/out          # full walk, ~45 min at the default 1 request/s
    python3 tools/census.py run --out ~/bazaar-census/out --resume # continue a stopped walk (or re-finalize a done one)
    python3 tools/census.py ids 1140,352 --base SNAPSHOT.json       # top-up: re-read only these ids, merge into SNAPSHOT
    python3 tools/census.py summary SNAPSHOT.json [--team t03]      # every team's deck
    python3 tools/census.py selftest                                # offline walk against a fake server, no network

Key. The walk starts keyless. The server answered 401 `bad_key` to a keyless read of this route on Saturday 3 Oct
(docs/findings.md says the same), so the first 401/403 switches the rest of the run to the team key (BAZAAR_KEY from
the environment or the repo's .env, header X-Team-Key, as kit/bazaar_sdk.py sends it): one keyless try per run, never
one per id. The key is never printed, logged or written; every error text goes through tools/redaction.py first.
A 401/403 with the key stops the run (exit 5): every other id would fail the same way.

Pace. One request at a time, `--rate` per second (default 1; the key allows 5/s shared by every agent on it). HTTP 429
and 5xx, timeouts and network errors are retried on the same id with exponential backoff (Retry-After honoured);
after `--max-retries` the id goes into `errors` and the walk goes on; `--max-consecutive-errors` ids failing in a row
stop the run (exit 5) with the progress kept for --resume.

End of the id space. The walk stops after `--stop-after` consecutive 404s above the highest id found and above
`--expect-max` (an id the operator knows exists, e.g. the highest asset id in the feed; it keeps a gap in the middle
from ending the walk early). `--max-id` is a hard cap; reaching it without that run of 404s exits 4.

Market Test silence (team rule: no API call during a Market Test). `--quiet "22:34-22:50,09:32-09:45"` pauses before
any request inside those local wall-clock windows. Local evidence comes first, with no request: a start inside a
window cached by the previous run (<out>/census-status.json) is refused. Then GET /api/clock and /api/schedule and,
with the doors open, /api/feed and the clock again (the windows are placed from a clock read after the feed): each
Market Test ("bench" in the schedule, "bench.started" in the feed) is silent from 2 min before to 10 min after, as in
tools/announce.py. The run refuses to start inside one (exit 3), pauses for the ones ahead, reads the status again
every 2 min, stops when it cannot be read (exit 3), and with the doors closed stops 2 min before the next opening
(exit 3: resume once the doors are open). `--skip-market-check` overrides all of it, only for an operator who knows.
`--until HH:MM` is a hard stop (exit 6); the partial file keeps everything read.

Files in --out (default logs/census):
  cards-<date>-partial.jsonl   one line per id as it goes (scrubbed raw payload), the basis of --resume
  cards-<date>-t<tick>.json    meta, cards [{id, ref, name, rarity, set, serial, owner}], packs, teams
                               {team: {cards, by_ref}}, other_owners (dealers, no owner): no history
  cards-<date>-t<tick>-history.json   {id: history}, only with --with-history
  census-status.json           the last Market Test windows read, the next run's local evidence
Exit: 0 done; 1 done with ids in `errors` (run --resume retries them); 2 bad input; 3 Market Test on or unknown;
4 id space may go past --max-id; 5 stopped (key refused, no key, too many errors in a row); 6 --until reached;
130 interrupted.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from redaction import scrub  # noqa: E402  (the one credential scrubber, tools/redaction.py)

URL = os.environ.get("BAZAAR_URL", "https://bazaar.causaprima.ai")
TEAM_RE = re.compile(r"^t\d+$")
CARD_REF_RE = re.compile(r"^[A-Z]{2,4}-\d+$")
PROGRESS_EVERY = 100
BACKOFF_CAP_S = 60.0       # exponential backoff ceiling between retries of one id
RETRY_AFTER_MAX_S = 600.0  # a server's Retry-After is honoured up to this
QUIET_BEFORE_S = 120       # Market Test silence, as tools/announce.py: from 2 min before a session starts
QUIET_AFTER_S = 600        # to 10 min after it
QUIET_TAIL_S = 120         # or 2 min after its last tick, whichever is later
BENCH_TICKS = 16           # a session's length when the schedule or the feed does not say
STATUS_REFRESH_S = 120     # the Market Test status is read again this often (before the next card request)
STATUS_FILE = "census-status.json"   # in --out: the last status's windows, the next run's local evidence


class Fatal(Exception):
    """Stops the run with an exit code; the partial file keeps the progress."""

    def __init__(self, message: str, code: int = 5):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- transport and key

def http_fetch(url: str, headers: dict, timeout: float = 15.0):
    """One GET. Returns (status, headers, body bytes) for any HTTP answer; network failures raise (OSError etc.)."""
    req = urllib.request.Request(url, headers={**headers, "Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers.items()), r.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return e.code, dict(e.headers.items()) if e.headers else {}, body


def load_key(env_file: Path | None = None):
    """BAZAAR_KEY from the environment, else from the repo's .env (as tools/announce.py reads it). Never printed."""
    key = os.environ.get("BAZAAR_KEY", "").strip()
    if not key:
        try:
            for line in Path(env_file or ROOT / ".env").read_text().splitlines():
                s = line.strip()
                if s.startswith("export "):
                    s = s[7:].strip()
                if s.startswith("BAZAAR_KEY="):
                    key = s.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    return key or None


def retry_delay(headers: dict, data, attempt: int) -> float:
    """Retry-After (seconds or an HTTP date), else a retry_after field in the body, else 2, 4, 8 ... up to 60 s."""
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    ra = h.get("retry-after")
    if ra:
        try:
            return min(max(float(ra), 0.5), RETRY_AFTER_MAX_S)
        except ValueError:
            try:
                return min(max(parsedate_to_datetime(ra).timestamp() - time.time(), 0.5), RETRY_AFTER_MAX_S)
            except (TypeError, ValueError, IndexError, OverflowError):
                pass
    if isinstance(data, dict):
        v = data.get("retry_after")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return min(float(v), RETRY_AFTER_MAX_S)
    return min(BACKOFF_CAP_S, 2.0 ** attempt)


class Stopped(Fatal):
    """--until reached: every id read so far is in the partial file; --resume continues."""

    def __init__(self, message: str):
        super().__init__(message, 6)


class Reader:
    """One paced GET at a time; keyless until the server asks for a key. Before every request: the hard stop
    (--until), the quiet windows and, before a card request, the Market Test guard (`gate`, set by Guard)."""

    def __init__(self, url=URL, fetch=http_fetch, key_loader=load_key, sleep=time.sleep, now=time.time,
                 rate=1.0, max_retries=8, quiet=(), say=print, until=None):
        self.url, self.fetch, self.key_loader = url.rstrip("/"), fetch, key_loader
        self.sleep, self.now, self.say = sleep, now, say
        self.interval = 1.0 / rate if rate and rate > 0 else 0.0
        self.max_retries = max(1, int(max_retries))
        self.quiet = list(quiet)
        self.key, self.keyed = None, False
        self.last_start = None
        self.requests = 0
        self.paused_s = 0.0
        self.until = until      # epoch of --until, or None
        self.gate = None        # Guard.gate: True when it refreshed the Market Test status (the caller loops)

    def clean(self, text) -> str:
        """Credential-shaped text redacted (tools/redaction.py), and the loaded key itself whatever its shape."""
        s = scrub(str(text))
        if self.key:
            s = s.replace(self.key, "[redacted]")
        return s

    def check_until(self) -> None:
        if self.until is not None and self.now() >= self.until:
            raise Stopped(f"reached --until {hhmm(self.until)}: stopping; every id read so far is in the partial "
                          "file, run again with --resume")

    def wait_quiet(self) -> bool:
        """Sleep through any quiet window `now` falls in, never past --until. No request. True when it slept."""
        slept = False
        while True:
            self.check_until()
            end = quiet_until(self.quiet, self.now())
            if end is None:
                return slept
            stop = end if self.until is None else min(end, self.until)
            wait = max(1.0, stop - self.now())
            self.say(f"census: quiet window until {hhmm(end)}: pausing {wait:.0f} s")
            self.sleep(wait)
            self.paused_s += wait
            slept = True

    def _pace(self, gated: bool) -> None:
        """Hold a request until the pace allows it, no quiet window covers it and, for a card (`gated`), the Market
        Test status is fresh. Loops: a pause or the guard's own refresh requests move the clock."""
        while True:
            self.check_until()
            if self.last_start is not None and self.interval:
                gap = self.interval - (self.now() - self.last_start)
                if gap > 0:
                    self.sleep(gap)
                    continue
            if self.wait_quiet():
                continue
            if gated and self.gate is not None and self.gate():
                continue
            break
        self.last_start = self.now()

    def _once(self, path: str, keyed: bool, gated: bool = False):
        """(status, headers, parsed JSON or None, error text or None); status 0 = no answer."""
        self._pace(gated)
        headers = {"X-Team-Key": self.key} if keyed and self.key else {}
        self.requests += 1
        try:
            status, hdrs, body = self.fetch(self.url + path, headers)
        except Exception as e:  # timeout, refused connection, DNS: no answer, retryable
            return 0, {}, None, self.clean(f"{type(e).__name__}: {e}")
        try:
            data = json.loads(body) if body else None
        except (ValueError, UnicodeDecodeError):
            data = None
            if status == 200:
                return -1, hdrs, None, "bad_response: not JSON"
        return status, hdrs or {}, data, None

    def _describe(self, status, data, err):
        if err:
            return ("network" if status == 0 else "bad_response"), self.clean(err)[:300]
        if isinstance(data, dict):
            return str(data.get("error") or f"http_{status}"), self.clean(data.get("message") or "")[:300]
        return f"http_{status}", ""

    @staticmethod
    def retryable(status: int) -> bool:
        return status in (0, -1, 429) or status >= 500

    def public(self, path: str):
        """A keyless read of a public route (clock, schedule, feed), retried like a card. Raises Fatal(3) on failure."""
        for attempt in range(1, self.max_retries + 1):
            status, hdrs, data, err = self._once(path, keyed=False)
            if status == 200:
                return data
            code, msg = self._describe(status, data, err)
            if not self.retryable(status) or attempt == self.max_retries:
                raise Fatal(f"GET {path} failed: {code} (HTTP {status}) {msg}".strip(), 3)
            self.sleep(retry_delay(hdrs, data, attempt))
        raise Fatal(f"GET {path} failed", 3)

    def card(self, i: int) -> dict:
        """A partial-file record: {"id", "status": 200, "raw"} or {"id", "status": 404} or an error record."""
        path = f"/api/cards/{int(i)}"
        attempt = 0
        while True:
            status, hdrs, data, err = self._once(path, keyed=self.keyed, gated=True)
            if status == 200:
                return {"id": i, "status": 200, "raw": scrub(data)}
            if status == 404:
                return {"id": i, "status": 404}
            code, msg = self._describe(status, data, err)
            if status in (401, 403):
                if not self.keyed:
                    key = self.key_loader()
                    if not key:
                        raise Fatal(f"keyless read of /api/cards refused (HTTP {status} {code}) and no team key found "
                                    "(BAZAAR_KEY in the environment or .env)", 5)
                    self.key, self.keyed = key, True
                    self.say(f"census: keyless read refused (HTTP {status} {code}): using the team key for the rest "
                             "of the run (key not shown)")
                    continue
                raise Fatal(f"team key refused on {path}: HTTP {status} {code} {msg}".strip(), 5)
            attempt += 1
            if not self.retryable(status) or attempt >= self.max_retries:
                return {"id": i, "status": "error", "http": status, "code": code, "message": msg,
                        "attempts": attempt}
            delay = retry_delay(hdrs, data, attempt)
            self.say(f"census: id {i}: {code} (HTTP {status}), retry {attempt}/{self.max_retries - 1} in {delay:.0f} s")
            self.sleep(delay)


# ---------------------------------------------------------------- quiet windows and the Market Test start check

def hhmm(epoch: float) -> str:
    return time.strftime("%H:%M", time.localtime(epoch))


def parse_quiet(text: str, now: float | None = None) -> list:
    """--quiet "22:34-22:50,09:32-09:45": local wall-clock windows for today as [(start, end)] epochs (an end before
    its start runs past midnight)."""
    base = time.localtime(time.time() if now is None else now)
    out = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        a, b = part.split("-")

        def at(hm: str) -> float:
            h, m = (int(x) for x in hm.strip().split(":"))
            if not (0 <= h < 24 and 0 <= m < 60):
                raise ValueError(hm)
            return time.mktime((base.tm_year, base.tm_mon, base.tm_mday, h, m, 0, 0, 0, -1))
        start, end = at(a), at(b)
        if end <= start:
            end += 86400
        out.append((start, end))
    return out


def quiet_until(windows: list, now: float):
    ends = [end for start, end in windows if start <= now < end]
    return max(ends) if ends else None


def session_end(start: float, ticks, tick_s: float) -> float:
    ticks = ticks if isinstance(ticks, int) and ticks > 0 else BENCH_TICKS
    return max(start + QUIET_AFTER_S, start + ticks * tick_s + QUIET_TAIL_S)


def parse_iso(text):
    try:
        return datetime.datetime.fromisoformat(str(text)).timestamp()
    except (TypeError, ValueError):
        return None


def parse_until(text: str, now: float):
    """--until HH:MM: the next such local wall-clock time (tomorrow when it has passed today)."""
    if not text:
        return None
    [(at, _)] = parse_quiet(f"{text}-{text}", now)
    return at if at > now else at + 86400


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def schedule_windows(schedule: dict, clock: dict, clock_at: float, is_open: bool = True) -> list:
    """Every upcoming Market Test (schedule action "bench") as a wall-clock window, from QUIET_BEFORE_S before it to
    QUIET_AFTER_S after (as tools/announce.py). A game hour is a wall hour within a day: today's sessions are placed
    from the clock as sampled at `clock_at` (doors open), a later day's from its day_opens wall time. A session with
    no anchor (doors closed, before any day_opens) cannot be placed and is skipped. The guard refreshes every
    STATUS_REFRESH_S, so a paused clock moves the windows later."""
    t_now = clock.get("t_hours") if isinstance(clock, dict) else None
    tick_s = clock.get("tick_seconds") if isinstance(clock, dict) else None
    tick_s = float(tick_s) if _num(tick_s) and tick_s > 0 else 30.0
    anchor = (clock_at, float(t_now), tick_s) if is_open and _num(t_now) else None
    order = {"day_closes": 0, "day_opens": 1}
    events = [e for e in (schedule or {}).get("upcoming") or [] if isinstance(e, dict) and _num(e.get("at_hours"))]
    out = []
    for ev in sorted(events, key=lambda e: (e["at_hours"], order.get(e.get("action"), 2))):
        at, action, params = ev["at_hours"], ev.get("action"), ev.get("params") or {}
        if action == "day_closes":
            anchor = None
        elif action == "day_opens":
            wall = parse_iso(ev.get("wall"))
            ts = params.get("tick_seconds")
            anchor = (wall, at, float(ts) if _num(ts) and ts > 0 else tick_s) if wall is not None else None
        elif action == "bench" and anchor is not None:
            a_epoch, a_hours, a_tick_s = anchor
            start = a_epoch + (at - a_hours) * 3600      # in the past when the session has already begun
            end = session_end(start, params.get("ticks"), a_tick_s)
            if end > clock_at:
                out.append((math.floor(start - QUIET_BEFORE_S), math.ceil(end)))
    return out


def running_windows(events: list, clock: dict, clock_at: float) -> list:
    """Market Tests already started (the schedule lists only upcoming ones): every bench.started in the feed, placed
    from the clock sampled at `clock_at`. The clock is read after the feed, so a start tick above the clock's tick
    should not happen; if it does, the session is taken as starting at `clock_at` (never dropped)."""
    try:
        tick, tick_s = int(clock["tick"]), float(clock["tick_seconds"])
    except (KeyError, TypeError, ValueError):
        return []
    out = []
    for e in events or []:
        if not isinstance(e, dict) or e.get("type") != "bench.started":
            continue
        pl = e.get("payload") or {}
        st = pl.get("start_tick", e.get("tick"))
        if not isinstance(st, int):
            continue
        ticks = pl.get("ticks") if isinstance(pl.get("ticks"), int) and pl.get("ticks") > 0 else BENCH_TICKS
        start = clock_at - max(0, tick - st) * tick_s
        end = max(session_end(start, ticks, tick_s), clock_at + (st + ticks - tick) * tick_s + QUIET_TAIL_S)
        if end > clock_at:
            out.append((math.floor(start - QUIET_BEFORE_S), math.ceil(end)))
    return out


def load_status(path) -> list:
    """The Market Test windows the previous run cached ([(start, end)] epochs), or []."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return [(float(a), float(b)) for a, b in data.get("windows") or []]
    except (OSError, ValueError, TypeError, AttributeError):
        return []


class Guard:
    """The Market Test status for the whole run (team rule: no API call during a Market Test).

    Local evidence first, with no request: the --quiet windows and the windows the previous run cached in
    <out>/census-status.json; a start inside a cached window is refused. Then GET /api/clock and /api/schedule and,
    with the doors open, /api/feed and the clock AGAIN: every window is placed from a clock read after the feed, so a
    retried request in between cannot leave a stale tick. The status is refreshed every STATUS_REFRESH_S before the
    next card request; with the doors closed the run stops QUIET_BEFORE_S before the next opening (the status can
    only be read with the doors open), and a refresh that fails stops the run (exit 3, progress kept)."""

    def __init__(self, reader: Reader, cache: Path | None, skip: bool):
        self.reader, self.cache, self.skip = reader, cache, skip
        self.manual = list(reader.quiet)
        self.windows: list = []
        self.valid_until = None   # epoch until which the status holds; None = never read
        self.stop_at = None       # doors closed: the run stops here (next opening - QUIET_BEFORE_S)
        self.opens = None
        self.clock: dict = {}
        self.refreshes = 0

    def local_check(self) -> None:
        """No request: refuse inside a cached Market Test window, pause for the cached ones still ahead."""
        if self.skip or self.cache is None:
            return
        now = self.reader.now()
        cached = load_status(self.cache)
        end = quiet_until(cached, now)
        if end is not None:
            raise Fatal(f"the previous run's schedule ({self.cache.name}) places a Market Test until {hhmm(end)}: "
                        "not starting, no request sent", 3)
        self.reader.quiet = self.manual + [w for w in cached if w[1] > now]

    def _closing_stop(self) -> Fatal:
        return Fatal(f"the doors open at {hhmm(self.opens)} and the Market Test status can only be read once they are "
                     f"open: stopping; progress kept, run again with --resume after {hhmm(self.opens)}", 3)

    def refresh(self) -> None:
        r = self.reader
        try:
            clock = r.public("/api/clock")
            clock = clock if isinstance(clock, dict) else {}
            clock_at = r.now()
            schedule = r.public("/api/schedule")
            is_open = clock.get("doors") in (None, "open")
            events = []
            if is_open:
                events = (r.public("/api/feed?limit=1000") or {}).get("events") or []
                clock = r.public("/api/clock")    # after the feed: its tick covers every bench.started just read
                clock = clock if isinstance(clock, dict) else {}
                clock_at = r.now()
                is_open = clock.get("doors") in (None, "open")
        except Stopped:
            raise
        except Fatal as e:
            raise Fatal(f"Market Test status unknown ({e}); stopping, progress kept (--skip-market-check overrides)", 3)
        windows = schedule_windows(schedule, clock, clock_at, is_open)
        if is_open:
            windows += running_windows(events, clock, clock_at)
        self.windows, self.clock = windows, clock
        self.valid_until, self.stop_at, self.opens = clock_at + STATUS_REFRESH_S, None, None
        if not is_open:
            self.opens = parse_iso(clock.get("next_opens"))
            if self.opens is not None:
                self.stop_at = self.opens - QUIET_BEFORE_S
                self.valid_until = min(self.valid_until, self.stop_at)
        self.refreshes += 1
        r.quiet = self.manual + windows
        if self.cache is not None:
            try:
                write_json(self.cache, {"saved_at": iso(clock_at), "clock_at": clock_at, "doors": clock.get("doors"),
                                        "tick": clock.get("tick"), "windows": [[a, b] for a, b in windows]})
            except OSError:
                pass
        if self.stop_at is not None and clock_at >= self.stop_at:
            raise self._closing_stop()

    def start(self) -> dict:
        """The first status read. Refuses inside a Market Test window (exit 3). Returns the clock."""
        if self.skip:
            self.clock = read_clock(self.reader)
            return self.clock
        self.refresh()
        end = quiet_until(self.windows, self.reader.now())
        if end is not None:
            raise Fatal(f"a Market Test is on or starts within {QUIET_BEFORE_S // 60} min (silence until {hhmm(end)}); "
                        "not starting", 3)
        ahead = [w for w in self.windows if w[1] > self.reader.now()]
        if ahead:
            self.reader.say("census: will pause for Market Tests at " + ", ".join(f"{hhmm(a)}-{hhmm(b)}" for a, b in ahead))
        return self.clock

    def gate(self) -> bool:
        """Before every card request (Reader._pace): stop before the opening when the doors are closed, refresh a
        stale status. True when it refreshed."""
        if self.skip:
            return False
        now = self.reader.now()
        if self.stop_at is not None and now >= self.stop_at:
            raise self._closing_stop()
        if self.valid_until is None or now >= self.valid_until:
            self.refresh()
            return True
        return False


# ---------------------------------------------------------------- payload, partial file, snapshot

_MISSING = object()


def _layers(raw: dict) -> list:
    """The payload, then any nested asset/card object (the shape was not observed keyless; read defensively)."""
    out = [raw]
    for k in ("asset", "card", "item"):
        if isinstance(raw.get(k), dict):
            out.append(raw[k])
    return out


def _pick(raw: dict, names, default=_MISSING, dict_ok: bool = False):
    """The first of `names` found in the payload or a nested layer. A dict value counts only when `dict_ok` (an owner
    or a set given as an object: its id); otherwise it is a nested layer, read by _layers."""
    for layer in _layers(raw):
        for n in names:
            if n not in layer:
                continue
            v = layer[n]
            if isinstance(v, dict):
                if not dict_ok:
                    continue
                v = v.get("id") or v.get("team")
                if v is None:
                    continue
            return v
    return default


def normalize(i: int, raw) -> tuple[dict, bool]:
    """(entry, parsed): entry {id, kind, ref, name, rarity, set, serial, owner}; parsed False when the ref or the
    owner field was not found (the raw payload stays in the partial file, so a fixed normalizer re-finalizes)."""
    raw = raw if isinstance(raw, dict) else {}
    ref = _pick(raw, ("ref", "card_ref", "code", "card"), None)
    ref = ref if isinstance(ref, str) else None
    owner = _pick(raw, ("owner", "holder", "owner_id", "held_by"), dict_ok=True)
    kind = _pick(raw, ("kind", "type"), None)
    if not isinstance(kind, str):
        kind = "card" if ref and CARD_REF_RE.match(ref) else ("pack" if "pack" in raw else "card")
    st = _pick(raw, ("set", "set_id"), None, dict_ok=True)
    if not isinstance(st, str) and ref and "-" in ref:
        st = ref.split("-", 1)[0]
    entry = {"id": i, "kind": kind, "ref": ref, "name": _pick(raw, ("name",), None),
             "rarity": _pick(raw, ("rarity",), None), "set": st if isinstance(st, str) else None,
             "serial": _pick(raw, ("serial",), None), "owner": None if owner is _MISSING else owner}
    if entry["owner"] is not None and not isinstance(entry["owner"], str):
        entry["owner"] = str(entry["owner"])
    return entry, bool(ref) and owner is not _MISSING


def history_of(raw):
    if not isinstance(raw, dict):
        return None
    for layer in _layers(raw):
        for k in ("history", "provenance", "chain"):
            if k in layer:
                return layer[k]
    return None


def read_partial(path: Path) -> dict:
    """id -> the last record for it (a resumed id's newer line wins; a torn last line is skipped)."""
    out = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("id"), int):
            out[rec["id"]] = rec
    return out


def tally(cards: list) -> tuple[dict, dict]:
    """teams {tNN: {cards, by_ref}} and other_owners (dealers, house, "none") in the same shape."""
    teams, others = {}, {}
    for c in cards:
        owner = c.get("owner") or "none"
        box = teams if TEAM_RE.match(owner) else others
        slot = box.setdefault(owner, {"cards": 0, "by_ref": {}})
        slot["cards"] += 1
        ref = c.get("ref") or "?"
        slot["by_ref"][ref] = slot["by_ref"].get(ref, 0) + 1

    def tidy(box):
        return {k: {"cards": v["cards"], "by_ref": dict(sorted(v["by_ref"].items()))} for k, v in sorted(box.items())}
    return tidy(teams), tidy(others)


def assemble(entries: dict, meta: dict) -> dict:
    """The snapshot from id -> normalized entry."""
    cards = [e for _, e in sorted(entries.items()) if e.get("kind") != "pack"]
    packs = [e for _, e in sorted(entries.items()) if e.get("kind") == "pack"]
    teams, others = tally(cards)
    cards = [{k: e.get(k) for k in ("id", "ref", "name", "rarity", "set", "serial", "owner")} for e in cards]
    packs = [{k: e.get(k) for k in ("id", "ref", "name", "owner")} for e in packs]
    meta = {**meta, "cards_total": len(cards), "cards_team_owned": sum(t["cards"] for t in teams.values()),
            "packs_total": len(packs), "teams_total": len(teams)}
    return {"meta": meta, "cards": cards, "packs": packs, "teams": teams, "other_owners": others}


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(epoch))


def pick_partial(out: Path, args, date: str, topup: bool, say) -> Path:
    """The partial file: --partial, else today's; --resume falls back to the newest one in --out (a walk started
    before midnight and resumed after it). Without --resume an existing one is moved aside, never mixed in."""
    if args.partial:
        path = Path(args.partial).expanduser()
    else:
        path = out / (f"cards-{date}-topup-partial.jsonl" if topup else f"cards-{date}-partial.jsonl")
        if args.resume and not path.exists():
            rx = re.compile(r"^cards-\d{4}-\d{2}-\d{2}-topup-partial\.jsonl$" if topup
                            else r"^cards-\d{4}-\d{2}-\d{2}-partial\.jsonl$")
            found = sorted((p for p in out.glob("cards-*-partial.jsonl") if rx.match(p.name)),
                           key=lambda p: p.stat().st_mtime)
            if found:
                path = found[-1]
                say(f"census: resuming from {path.name}")
    if not args.resume and path.exists():
        aside = path.with_name(path.name + time.strftime(".%H%M%S.old"))
        path.rename(aside)
        say(f"census: an earlier partial file moved aside to {aside.name} (pass --resume to continue one)")
    return path


# ---------------------------------------------------------------- modes

def walk(reader: Reader, ids, done: dict, partial: Path, args, say, end_detect: bool) -> dict:
    """Read every id not already done, appending each record to the partial file. Returns the walk's stats."""
    stats = {"found": 0, "not_found": 0, "errors": [], "last_id": 0, "end": None, "resumed": 0}
    highest = max([i for i, r in done.items() if r.get("status") == 200] or [0])
    streak, in_a_row = 0, 0
    t0 = reader.now()
    partial.parent.mkdir(parents=True, exist_ok=True)
    with open(partial, "a", encoding="utf-8") as f:
        for n, i in enumerate(ids, 1):
            rec = done.get(i)
            if rec is not None and rec.get("status") in (200, 404):
                stats["resumed"] += 1
            else:
                rec = reader.card(i)
                rec["at"] = iso(reader.now())
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                done[i] = rec
            stats["last_id"] = i
            status = rec.get("status")
            if status == 200:
                stats["found"] += 1
                highest = max(highest, i)
                streak, in_a_row = 0, 0
            elif status == 404:
                stats["not_found"] += 1
                streak = streak + 1 if i > max(highest, args.expect_max or 0) else 0
                in_a_row = 0
            else:
                stats["errors"].append({k: rec.get(k) for k in ("id", "http", "code", "message", "attempts")})
                streak = 0
                in_a_row += 1
                say(f"census: id {i} failed after {rec.get('attempts')} tries: {rec.get('code')}")
                if in_a_row >= args.max_consecutive_errors:
                    raise Fatal(f"{in_a_row} ids failed in a row (last {i}: {rec.get('code')}); stopping. "
                                "Progress kept: run again with --resume", 5)
            if n % PROGRESS_EVERY == 0:
                say(f"census: id {i} | cards {stats['found']} | 404 {stats['not_found']} | errors "
                    f"{len(stats['errors'])} | {'keyed' if reader.keyed else 'keyless'} | "
                    f"{(reader.now() - t0) / 60:.1f} min")
            if end_detect and streak >= args.stop_after:
                stats["end"] = "404_run"
                break
    if end_detect and stats["end"] is None:
        stats["end"] = "max_id"
    stats["highest_found"] = highest
    return stats


def read_clock(reader: Reader) -> dict:
    try:
        c = reader.public("/api/clock")
        return c if isinstance(c, dict) else {}
    except Fatal:
        return {}


def make_reader(args, deps) -> Reader:
    if not 0 < args.rate <= 5:
        raise Fatal("--rate must be above 0 and at most 5 (the key's limit, shared with every agent on it)", 2)
    env_file = Path(args.env_file).expanduser() if getattr(args, "env_file", None) else None
    key_loader = deps.get("key_loader") or (lambda: load_key(env_file))
    try:
        quiet = parse_quiet(args.quiet, deps["now"]())
    except ValueError:
        raise Fatal(f"--quiet: cannot read {args.quiet!r} (expected HH:MM-HH:MM,...)", 2)
    try:
        until = parse_until(args.until, deps["now"]())
    except ValueError:
        raise Fatal(f"--until: cannot read {args.until!r} (expected HH:MM)", 2)
    return Reader(args.url, deps["fetch"], key_loader, deps["sleep"], deps["now"], args.rate, args.max_retries,
                  quiet, deps["say"], until)


def begin(reader: Reader, out: Path, args) -> tuple:
    """Local evidence first (cached windows, --quiet: no request), then the first Market Test status read."""
    guard = Guard(reader, out / STATUS_FILE, args.skip_market_check)
    reader.gate = guard.gate
    guard.local_check()
    reader.wait_quiet()
    return guard, guard.start()


def finish(reader: Reader, entries: dict, histories: dict, meta: dict, out: Path, args, date: str,
           avoid: Path | None = None) -> Path:
    clock = read_clock(reader)
    meta["tick_end"] = clock.get("tick")
    meta["ended"] = iso(reader.now())
    meta["requests"] = reader.requests
    meta["keyed"] = reader.keyed
    meta["quiet_paused_s"] = round(reader.paused_s)
    tick = meta.get("tick_end") if meta.get("tick_end") is not None else meta.get("tick_start")
    path = out / f"cards-{date}-t{tick if tick is not None else 'NA'}.json"
    if avoid is not None and path.resolve() == avoid.resolve():
        path = path.with_name(path.stem + "-topup.json")
    snap = assemble(entries, meta)
    write_json(path, snap)
    if args.with_history:
        write_json(path.with_name(path.stem + "-history.json"),
                   {str(i): h for i, h in sorted(histories.items())})
    return path


def cmd_run(args, deps) -> int:
    say = deps["say"]
    reader = make_reader(args, deps)
    started = deps["now"]()
    date = time.strftime("%Y-%m-%d", time.localtime(started))
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    partial = pick_partial(out, args, date, topup=False, say=say)
    done = read_partial(partial) if args.resume else {}
    guard, clock = begin(reader, out, args)
    say(f"census: run from id 1 into {out} at {args.rate:g} request/s (tick {clock.get('tick')}, "
        f"doors {clock.get('doors')}){'; ' + str(len(done)) + ' ids in the partial file' if done else ''}")
    stats = walk(reader, range(1, args.max_id + 1), done, partial, args, say, end_detect=True)
    entries, histories, unparsed = {}, {}, []
    for i, rec in done.items():
        if rec.get("status") != 200:
            continue
        entry, ok = normalize(i, rec.get("raw"))
        entries[i] = entry
        if not ok:
            unparsed.append(i)
        if args.with_history:
            histories[i] = history_of(rec.get("raw"))
    meta = {"tool": "tools/census.py", "mode": "run", "url": reader.url, "started": iso(started),
            "tick_start": clock.get("tick"), "doors_start": clock.get("doors"), "ids_walked": stats["last_id"],
            "found": stats["found"], "not_found": stats["not_found"], "resumed_ids": stats["resumed"],
            "end": stats["end"], "highest_found": stats["highest_found"], "stop_after": args.stop_after,
            "max_id": args.max_id, "expect_max": args.expect_max, "unparsed_ids": sorted(unparsed),
            "errors": stats["errors"], "partial": str(partial),
            "status_refreshes": guard.refreshes}
    path = finish(reader, entries, histories, meta, out, args, date)
    snap_meta = json.loads(path.read_text(encoding="utf-8"))["meta"]
    say(f"census: wrote {path} | cards {snap_meta['cards_total']} (team-owned {snap_meta['cards_team_owned']}, "
        f"{snap_meta['teams_total']} teams) | packs {snap_meta['packs_total']} | 404 {stats['not_found']} | errors "
        f"{len(stats['errors'])} | {reader.requests} requests")
    if unparsed:
        say(f"census: WARNING {len(unparsed)} payloads without a ref or owner field (e.g. id {unparsed[0]}); the raw "
            "payloads are in the partial file")
    if stats["end"] == "max_id":
        say(f"census: WARNING reached --max-id {args.max_id} without {args.stop_after} 404s in a row: ids may go on")
        return 4
    if stats["found"] == 0:
        say("census: WARNING no card found at all")
        return 1
    return 1 if stats["errors"] else 0


def parse_ids(text: str) -> list:
    return sorted({int(x) for x in re.findall(r"\d+", text or "")})


def cmd_ids(args, deps) -> int:
    say = deps["say"]
    ids = parse_ids(args.id_list or "")
    if args.ids_file:
        try:
            ids = sorted(set(ids) | set(parse_ids(Path(args.ids_file).expanduser().read_text())))
        except OSError as e:
            raise Fatal(f"--ids-file: {e}", 2)
    if not ids:
        raise Fatal("no ids given (ids 12,57,... or --ids-file FILE)", 2)
    base_path = Path(args.base).expanduser()
    try:
        base = json.loads(base_path.read_text(encoding="utf-8"))
        base_cards = {c["id"]: {**c, "kind": "card"} for c in base["cards"]}
        base_packs = {p["id"]: {**p, "kind": "pack"} for p in base.get("packs") or []}
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise Fatal(f"--base {base_path}: not a census snapshot ({type(e).__name__})", 2)
    reader = make_reader(args, deps)
    started = deps["now"]()
    date = time.strftime("%Y-%m-%d", time.localtime(started))
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    partial = pick_partial(out, args, date, topup=True, say=say)
    done = read_partial(partial) if args.resume else {}
    guard, clock = begin(reader, out, args)
    say(f"census: top-up of {len(ids)} ids over {base_path.name} (tick {clock.get('tick')})")
    stats = walk(reader, ids, done, partial, args, say, end_detect=False)
    entries = {**base_cards, **base_packs}
    histories, changed, added, removed, unparsed = {}, [], [], [], []
    for i in ids:
        rec = done.get(i) or {}
        if rec.get("status") == 404:
            if entries.pop(i, None) is not None:
                removed.append(i)
        elif rec.get("status") == 200:
            entry, ok = normalize(i, rec.get("raw"))
            if not ok:
                unparsed.append(i)
            old = entries.get(i)
            if old is None:
                added.append(i)
            elif old.get("owner") != entry.get("owner"):
                changed.append({"id": i, "ref": entry.get("ref"), "from": old.get("owner"), "to": entry.get("owner")})
            entries[i] = entry
            if args.with_history:
                histories[i] = history_of(rec.get("raw"))
    meta = {"tool": "tools/census.py", "mode": "topup", "url": reader.url, "started": iso(started),
            "base": str(base_path), "base_tick": (base.get("meta") or {}).get("tick_end"),
            "tick_start": clock.get("tick"), "doors_start": clock.get("doors"), "ids_walked": len(ids),
            "ids": ids, "found": stats["found"], "not_found": stats["not_found"], "moved": changed, "added": added,
            "removed": removed, "unparsed_ids": sorted(unparsed), "errors": stats["errors"], "partial": str(partial),
            "status_refreshes": guard.refreshes}
    path = finish(reader, entries, histories, meta, out, args, date, avoid=base_path)
    say(f"census: wrote {path} | {len(ids)} ids re-read | moved {len(changed)} | added {len(added)} | removed "
        f"{len(removed)} | errors {len(stats['errors'])}")
    return 1 if stats["errors"] else 0


def summary_lines(snap: dict, team: str | None = None) -> list:
    m = snap.get("meta") or {}
    lines = [f"census {m.get('mode', '?')} | tick {m.get('tick_end', m.get('tick_start'))} | cards "
             f"{m.get('cards_total')} (team-owned {m.get('cards_team_owned')}) | teams {m.get('teams_total')} | "
             f"errors {len(m.get('errors') or [])}"]
    groups = [("", snap.get("teams") or {}), ("other owner ", snap.get("other_owners") or {})]
    for label, box in groups:
        for owner, t in box.items():
            if team and owner != team:
                continue
            lines.append(f"{label}{owner}  {t['cards']} cards")
            by_set = {}
            for ref, n in t["by_ref"].items():
                by_set.setdefault(ref.split("-", 1)[0], []).append(ref if n == 1 else f"{ref} x{n}")
            for s, refs in sorted(by_set.items()):
                lines.append(f"  {s:<4} " + ", ".join(refs))
    return lines


def cmd_summary(args, deps) -> int:
    try:
        snap = json.loads(Path(args.snapshot).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Fatal(f"{args.snapshot}: {type(e).__name__}", 2)
    for line in summary_lines(snap, args.team):
        deps["say"](line)
    return 0


def cmd_selftest(args, deps) -> int:
    """An offline walk against a fake server: 3 teams, a dealer, a pack, a 429, a mid gap; checks the snapshot."""
    cards = {i: {"id": i, "kind": "card", "ref": f"LAV-{(i % 12) + 1:02d}", "name": "x", "rarity": "common",
                 "set": "LAV", "serial": i, "owner": ("t01", "t02", "t03", "abuela")[i % 4], "history": []}
             for i in range(1, 121) if not 50 <= i < 55}
    cards[7] = {"id": 7, "kind": "pack", "ref": "sobre_barrio", "owner": "t02"}
    hits = {"429": 0}

    def fake(url, headers, timeout=15.0):
        if url.endswith("/api/clock"):
            return 200, {}, json.dumps({"tick": 9, "doors": "closed"}).encode()
        if url.endswith("/api/schedule"):
            return 200, {}, b'{"upcoming": []}'
        if not headers.get("X-Team-Key"):
            return 401, {}, b'{"error": "bad_key"}'
        i = int(url.rsplit("/", 1)[1])
        if i == 30 and hits["429"] == 0:
            hits["429"] += 1
            return 429, {"Retry-After": "2"}, b'{"error": "rate_limited"}'
        return (200, {}, json.dumps(cards[i]).encode()) if i in cards else (404, {}, b'{"error": "not_found"}')

    clock = [0.0]
    with tempfile.TemporaryDirectory() as tmp:
        argv = ["run", "--out", tmp, "--stop-after", "10", "--max-id", "500"]
        code = main(argv, fetch=fake, sleep=lambda s: clock.__setitem__(0, clock[0] + s),
                    now=lambda: 1_790_000_000.0 + clock[0], key_loader=lambda: "tk-self-test-0000",
                    say=lambda *a: None)
        snaps = [p for p in Path(tmp).glob("cards-*-t*.json")]
        snap = json.loads(snaps[0].read_text()) if len(snaps) == 1 else {}
        text = "".join(p.read_text() for p in Path(tmp).iterdir())
    owned = sum(1 for c in snap.get("cards") or [] if TEAM_RE.match(c.get("owner") or ""))
    checks = [("exit 0", code == 0), ("one snapshot", len(snaps) == 1),
              ("teams total = team-owned cards", sum(t["cards"] for t in (snap.get("teams") or {}).values()) == owned
               == (snap.get("meta") or {}).get("cards_team_owned")),
              ("all cards found", len(snap.get("cards") or []) == len(cards) - 1),
              ("pack kept apart", [p["id"] for p in snap.get("packs") or []] == [7]),
              ("stopped 10 past the last id", (snap.get("meta") or {}).get("ids_walked") == 130),
              ("key never written", "tk-self-test-0000" not in text)]
    for name, ok in checks:
        deps["say"](f"selftest: {'ok  ' if ok else 'FAIL'} {name}")
    return 0 if all(ok for _, ok in checks) else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="census.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    walk_opts = argparse.ArgumentParser(add_help=False)
    walk_opts.add_argument("--out", default=str(ROOT / "logs" / "census"), help="output directory (default logs/census)")
    walk_opts.add_argument("--rate", type=float, default=1.0, help="requests per second, single-threaded (default 1)")
    walk_opts.add_argument("--quiet", default="", help='local wall-clock pause windows, e.g. "22:34-22:50,09:32-09:45"')
    walk_opts.add_argument("--resume", action="store_true", help="skip ids already in the partial file")
    walk_opts.add_argument("--partial", help="partial file to write or resume (default <out>/cards-<date>-partial.jsonl)")
    walk_opts.add_argument("--with-history", action="store_true", help="also write each card's history to a -history.json")
    walk_opts.add_argument("--max-retries", type=int, default=8, help="tries per id on 429/5xx/network (default 8)")
    walk_opts.add_argument("--max-consecutive-errors", type=int, default=10,
                           help="stop after this many ids fail in a row (default 10)")
    walk_opts.add_argument("--skip-market-check", action="store_true",
                           help="start without the Market Test check (only when you know none is on)")
    walk_opts.add_argument("--until", help="HH:MM local: stop there (partial file kept, exit 6); --resume continues")
    walk_opts.add_argument("--env-file", help="file holding BAZAAR_KEY= (default the repo's .env)")
    walk_opts.add_argument("--url", default=URL, help="server (default BAZAAR_URL or https://bazaar.causaprima.ai)")
    sub = ap.add_subparsers(dest="mode", required=True)
    run = sub.add_parser("run", parents=[walk_opts], help="walk every id from 1")
    run.add_argument("--stop-after", type=int, default=60, help="consecutive 404s that end the id space (default 60)")
    run.add_argument("--max-id", type=int, default=3000, help="hard cap on ids (default 3000)")
    run.add_argument("--expect-max", type=int, default=0,
                     help="an id known to exist: 404 runs below it never end the walk")
    ids = sub.add_parser("ids", parents=[walk_opts], help="top-up: re-read these ids and merge into --base")
    ids.add_argument("id_list", nargs="?", default="", help="comma-separated ids, e.g. 12,57,1140")
    ids.add_argument("--ids-file", help="file with ids (any separators)")
    ids.add_argument("--base", required=True, help="the snapshot to merge into")
    summ = sub.add_parser("summary", help="print every team's deck from a snapshot")
    summ.add_argument("snapshot")
    summ.add_argument("--team", help="only this owner, e.g. t03")
    sub.add_parser("selftest", help="offline walk against a fake server (no network, no key)")
    return ap


def main(argv=None, *, fetch=http_fetch, sleep=time.sleep, now=time.time, key_loader=None, say=None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "mode", None) == "ids":
        args.stop_after, args.max_id, args.expect_max = 0, 0, 0
    emit = say or (lambda *a: print(*a, flush=True))
    deps = {"fetch": fetch, "sleep": sleep, "now": now, "key_loader": key_loader, "say": lambda m: emit(scrub(str(m)))}
    try:
        return {"run": cmd_run, "ids": cmd_ids, "summary": cmd_summary, "selftest": cmd_selftest}[args.mode](args, deps)
    except Fatal as e:
        deps["say"](f"census: {e}")
        return e.code
    except KeyboardInterrupt:
        deps["say"]("census: interrupted; progress kept, run again with --resume")
        return 130


if __name__ == "__main__":
    sys.exit(main())
