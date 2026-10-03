"""Duel book: which rival bot is behind each colour alias, and how it bargains, from the duel snapshots. Read-only.

The alias ("Rival Verde") is random per duel, but each team's bot writes with its own text template and the same
template shows up in both duels of a pair (one per role). So: template every rival message (numbers -> N, the duel's
item -> ITEM, lowercase), group duels into bots (exact template, templates that co-occur in one duel, a conservative
token-Jaccard merge, and the two duels of a pair), then profile each bot's price path relative to what we see at
runtime (our limit, the tick of its first message): opening, per-tick concession, shape, tempo, reactive, who
accepted, final price vs our limit. Every merge is printed so a human can check it.

Usage:
    python3 tools/duel_book.py                                  # build results/duel-book.json + docs/duel-lab/duel-book.md
    python3 tools/duel_book.py --dir /Volumes/bazaar/logs/duels --no-write
    python3 tools/duel_book.py --match "I can do 45. That is a fair deal for both of us."
"""
from __future__ import annotations

import argparse
import collections
import difflib
import json
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = Path("/Volumes/bazaar/logs/duels")
DEFAULT_JSON = ROOT / "results" / "duel-book.json"
DEFAULT_MD = ROOT / "docs" / "duel-lab" / "duel-book.md"
JACCARD_MIN = 0.7
JACCARD_MIN_TOKENS = 4
LLM_TOKENS = 18          # template bots write <= 13 tokens; longer and never repeated is free text (an LLM bot)
ES_WORDS = {"puedo", "primas", "propongo", "cerrar", "cerramos", "precio", "dime", "justo", "para", "los", "dos",
            "una", "que", "muevo", "acercarnos", "pieza", "merece", "pienso", "propuesta", "ganemos", "hecho", "días"}
EN_WORDS = {"i", "can", "do", "the", "for", "we", "offer", "let", "thank", "you", "works", "close", "deal", "my",
            "how", "about", "then", "hello", "is", "of", "us", "from", "side", "our", "with", "days"}

_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_WS = re.compile(r"\s+")
_TOK = re.compile(r"[a-záéíóúñü]+|N|ITEM", re.IGNORECASE)


# ---------------------------------------------------------------- templating

def template(text: str, item: str = "") -> str:
    """'I can do 45 for Café en Goya.' -> 'i can do N for ITEM.'"""
    t = _WS.sub(" ", (text or "").strip()).lower()
    if item:
        t = re.sub(re.escape(item.lower()), "ITEM", t)
    t = _NUM.sub("N", t)
    return t


def tokens(tpl: str) -> frozenset:
    return frozenset(w if w in ("N", "ITEM") else w.lower() for w in _TOK.findall(tpl))


def jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def similarity(a: str, b: str) -> float:
    """Jaccard, or a discounted containment so a template plus a new days clause still matches."""
    if a == b:
        return 1.0
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    j = jaccard(ta, tb)
    small, big = sorted((len(ta), len(tb)))
    if small >= JACCARD_MIN_TOKENS and big <= 2 * small:     # a short line inside a long LLM text is no match
        j = max(j, 0.85 * len(ta & tb) / small)
    return round(j, 3)


def language(texts: list) -> str:
    words = collections.Counter()
    for t in texts:
        words.update(w.lower() for w in re.findall(r"\w+", t or ""))
    es = sum(n for w, n in words.items() if w in ES_WORDS)
    en = sum(n for w, n in words.items() if w in EN_WORDS)
    if not es and not en:
        return "-"
    return "es" if es > en else "en"


# ---------------------------------------------------------------- loading

def load(dirpath: Path) -> list:
    duels = []
    for f in sorted(dirpath.glob("duel-*.json")):
        if f.stem.endswith("-first"):
            continue
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        msgs = d.get("messages") or []
        d["rival_msgs"] = [m for m in msgs if m.get("from") != "you"]
        d["our_msgs"] = [m for m in msgs if m.get("from") == "you"]
        d["templates"] = [template(m.get("text") or "", d.get("item") or "") for m in d["rival_msgs"]]
        duels.append(d)
    return duels


def pairs(duels: list) -> dict:
    """duel id -> partner id: consecutive ids, same session and item (one duel per role)."""
    out, ordered = {}, sorted(duels, key=lambda d: d["duel"])
    for a, b in zip(ordered, ordered[1:]):
        if a["duel"] in out or b["duel"] - a["duel"] != 1:
            continue
        if a.get("session") == b.get("session") and a.get("item") == b.get("item"):
            out[a["duel"]], out[b["duel"]] = b["duel"], a["duel"]
    return out


# ---------------------------------------------------------------- grouping

class _UF:
    def __init__(self):
        self.p: dict = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        self.p[max(ra, rb)] = min(ra, rb)
        return True


def group(duels: list, use_pairs: bool = True) -> tuple:
    """Union-find over templates. Returns ({root template: [duel ids]}, merges log, silent duel ids)."""
    uf, merges = _UF(), []
    for d in duels:
        for t in d["templates"]:
            uf.find(t)
    # 1 exact match is implicit (same string = same node); 2 co-occurrence within one duel
    for d in duels:
        ts = list(dict.fromkeys(d["templates"]))
        for t in ts[1:]:
            if uf.union(ts[0], t) and len(ts) <= 6:
                merges.append({"step": "co-occur", "duel": d["duel"], "a": ts[0], "b": t})
    # 3 conservative token Jaccard between single templates
    tpls = sorted({t for d in duels for t in d["templates"]})
    for i, a in enumerate(tpls):
        ta = tokens(a)
        for b in tpls[i + 1:]:
            tb = tokens(b)
            if min(len(ta), len(tb)) < JACCARD_MIN_TOKENS or uf.find(a) == uf.find(b):
                continue
            j = jaccard(ta, tb)
            if j >= JACCARD_MIN and uf.union(a, b):
                merges.append({"step": "jaccard", "score": round(j, 2), "a": a, "b": b})
    # 4 the two duels of a pair are the same team, even when it writes a different line per role
    if use_pairs:
        partner, by_id = pairs(duels), {d["duel"]: d for d in duels}
        for did, pid in sorted(partner.items()):
            if did > pid:
                continue
            a, b = by_id[did]["templates"], by_id[pid]["templates"]
            if a and b and uf.union(a[0], b[0]):
                merges.append({"step": "pair", "duels": [did, pid], "a": a[0], "b": b[0]})
    groups, silent = collections.defaultdict(list), []
    for d in duels:
        if d["templates"]:
            groups[uf.find(d["templates"][0])].append(d["duel"])
        else:
            silent.append(d["duel"])
    return dict(groups), merges, silent


# ---------------------------------------------------------------- per-duel profile

def duel_ticks(d: dict) -> int:
    return 16 if (d.get("session") or 0) >= 2 else 12


def _offers(d: dict) -> list:
    out = []
    for m in d["rival_msgs"]:
        if m.get("price") is None:
            continue
        if out and out[-1] == (m["tick"], m["price"]):
            continue
        out.append((m["tick"], m["price"]))
    return out


def _shape(offers: list) -> tuple:
    """(shape, cadence, trailing holds) of the rival's price path."""
    if not offers:
        return "silent", None, 0
    prices = [p for _, p in offers]
    if len(set(prices)) == 1:
        return ("oneshot" if len(offers) == 1 else "holds"), None, len(offers) - 1
    gaps = [offers[i][0] - offers[i - 1][0] for i in range(1, len(offers))]
    moved = [i for i in range(1, len(prices)) if prices[i] != prices[i - 1]]
    trailing = 0
    for i in range(len(prices) - 1, 0, -1):
        if prices[i] != prices[i - 1]:
            break
        trailing += 1
    move_gaps = [offers[moved[k]][0] - offers[moved[k - 1]][0] for k in range(1, len(moved))]
    cadence = statistics.median(move_gaps) if move_gaps else (gaps[0] if gaps else None)
    if len(moved) <= 3 and trailing >= 3:
        return "jump-hold", cadence, trailing
    if len(moved) >= 0.7 * (len(offers) - 1):
        if cadence is not None and cadence >= 2:
            return f"stepped/{int(cadence)}", cadence, trailing
        return "every-tick", cadence, trailing
    return "stepped", cadence, trailing


def _tempo(offers: list) -> str:
    steps = [abs(offers[i][1] - offers[i - 1][1]) for i in range(1, len(offers)) if offers[i][1] != offers[i - 1][1]]
    if len(steps) < 4:
        return "-"
    h = len(steps) // 2
    first, second = sum(steps[:h]) / h, sum(steps[-h:]) / h
    if second > 1.3 * first:
        return "accelerating"
    if second < 0.77 * first:
        return "decelerating"
    return "linear"


def _reactive(offers: list, our_ticks: list):
    """True: every move came after a message of ours; False: it moved while we were silent; None: no evidence."""
    with_us = without_us = 0
    for i in range(1, len(offers)):
        if offers[i][1] == offers[i - 1][1]:
            continue
        lo, hi = offers[i - 1][0], offers[i][0]
        if any(lo < t <= hi for t in our_ticks):
            with_us += 1
        else:
            without_us += 1
    if without_us:
        return False
    return True if with_us else None


def profile_duel(d: dict) -> dict:
    lim = d.get("your_limit") or 0
    our_role = d.get("role") or "?"
    rival_role = {"seller": "buyer", "buyer": "seller"}.get(our_role, "?")
    toward = 1 if rival_role == "buyer" else -1         # direction in which the rival concedes
    offers = _offers(d)
    our_ticks = [m["tick"] for m in d["our_msgs"]]
    our_prices = {m.get("price") for m in d["our_msgs"] if m.get("price") is not None}
    if d.get("your_offer"):
        our_prices.add(d["your_offer"].get("price"))
    shape, cadence, trailing = _shape(offers)
    start = (d.get("deadline_tick") or 0) - duel_ticks(d)
    row = {"duel": d["duel"], "session": d.get("session"), "our_role": our_role, "rival_role": rival_role,
           "alias": d.get("rival"), "limit": lim, "status": d.get("status"), "final": d.get("price"),
           "shape": shape, "trailing_holds": trailing, "n_offers": len(offers),
           "prices": [p for _, p in offers], "ticks": [t - start for t, _ in offers], "result": d.get("result")}
    if offers:
        (t0, p0), (t1, p1) = offers[0], offers[-1]
        span = max(t1 - t0, 1)
        conceded = (p1 - p0) * toward
        gap = abs(p0 - lim)
        acceptable = [t - start for t, p in offers if (p - lim) * toward >= 0]
        row.update({
            "open": p0, "open_at": t0 - start, "open_vs_limit": round(p0 / lim, 3) if lim else None,
            "opens_inside": (p0 - lim) * toward >= 0,
            "last": p1, "last_vs_limit": round(p1 / lim, 3) if lim else None,
            "step_abs": round(conceded / span, 2),
            "step_pct_open": round(100 * conceded / span / p0, 2) if p0 else None,
            "step_frac_gap": round(conceded / span / gap, 3) if gap else None,
            "acceptable_at": acceptable[0] if acceptable else None,
            "tempo": _tempo(offers), "reactive": _reactive(offers, our_ticks)})
    final = d.get("price")
    if d.get("status") == "deal" and final is not None:
        last_rival = offers[-1][1] if offers else None
        if final == last_rival and final in our_prices:
            row["accepted"] = "met"
        elif final == last_rival:
            row["accepted"] = "we took theirs"
        elif final in our_prices:
            row["accepted"] = "took ours"
        else:
            row["accepted"] = "other"
        row["final_vs_limit"] = round(final / lim, 3) if lim else None
    else:
        row["accepted"] = "no deal" if d.get("status") == "no_deal" else d.get("status")
    return row


# ---------------------------------------------------------------- per-bot profile

def _med(xs: list):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 3) if xs else None


def _role_profile(rows: list) -> dict:
    movers = [r for r in rows if r.get("n_offers")]
    return {
        "n": len(rows), "n_talking": len(movers),
        "open_vs_limit": _med([r.get("open_vs_limit") for r in movers]),
        "open_at": _med([r.get("open_at") for r in movers]),
        "opens_inside": sum(1 for r in movers if r.get("opens_inside")),
        "step_abs": _med([r.get("step_abs") for r in movers]),
        "step_pct_open": _med([r.get("step_pct_open") for r in movers]),
        "step_frac_gap": _med([r.get("step_frac_gap") for r in movers]),
        "acceptable_at": _med([r.get("acceptable_at") for r in movers]),
        "last_vs_limit": _med([r.get("last_vs_limit") for r in movers]),
        "final_vs_limit": _med([r.get("final_vs_limit") for r in rows]),
        "shapes": dict(collections.Counter(r["shape"] for r in rows).most_common()),
        "tempo": dict(collections.Counter(r.get("tempo", "-") for r in movers).most_common()),
        "reactive": dict(collections.Counter(str(r.get("reactive")) for r in movers).most_common()),
        "accepted": dict(collections.Counter(r["accepted"] for r in rows).most_common()),
    }


def _latest(rows: list) -> list:
    """Profile on the real sessions (2+) when the bot played them; Friday practice (12 ticks) only as a fallback."""
    real = [r for r in rows if (r["session"] or 0) >= 2]
    return real or rows


def play(b: dict) -> str:
    """One line on how to play it, from the profile (a heuristic for a human, not a rule the bot applies)."""
    if b["id"] == "SILENT":
        return "never writes; some took our first offer: open high, keep a margin"
    shapes, tempo, acc, at = collections.Counter(), collections.Counter(), collections.Counter(), []
    for p in b["profile"].values():
        shapes.update(p["shapes"])
        tempo.update({k: v for k, v in p["tempo"].items() if k != "-"})
        acc.update(p["accepted"])
        if p.get("acceptable_at") is not None:
            at.append(p["acceptable_at"])
    top = shapes.most_common(1)[0][0] if shapes else "-"
    if top == "holds":
        return "holds one number all duel; took our offer, so make offers instead of taking its number"
    if top in ("oneshot", "silent"):
        return "one line then quiet: little to read, make our own offers"
    when = f" (crosses our limit ~t+{int(max(at))})" if at else ""
    if b.get("llm_free_text"):
        return "LLM free text, slow steps; wait for the last ticks" + when
    if tempo and tempo.most_common(1)[0][0] == "accelerating":
        return "concedes faster near the end: hold and take its last offer" + when
    if tempo and tempo.most_common(1)[0][0] == "decelerating":
        return "concedes early then floors: take it once steps shrink to ~1 P" + when
    return "steady concession: take its offer at the last safe tick" + when


def build(duels: list, use_pairs: bool = True) -> dict:
    groups, merges, silent = group(duels, use_pairs)
    by_id = {d["duel"]: d for d in duels}
    partner = pairs(duels)
    root_of = {did: root for root, ids in groups.items() for did in ids}
    attached = collections.defaultdict(list)
    loose_silent = []
    for did in silent:
        pid = partner.get(did)
        if pid in root_of:
            attached[root_of[pid]].append(did)
        else:
            loose_silent.append(did)
    bots = []
    for root, ids in groups.items():
        all_ids = sorted(ids + attached.get(root, []))
        rows = [profile_duel(by_id[i]) for i in all_ids]
        tcount, first = collections.Counter(), collections.Counter()
        for i in ids:
            ts = by_id[i]["templates"]
            tcount.update(ts)
            first[ts[0]] += 1
        texts = [m.get("text") for i in ids for m in by_id[i]["rival_msgs"]]
        free_text = all(n == 1 for n in tcount.values()) and any(len(tokens(t)) >= LLM_TOKENS for t in tcount)
        latest_first = sorted(ids, key=lambda i: (-(by_id[i].get("session") or 0), i))
        example = next((m.get("text") for i in latest_first for m in by_id[i]["rival_msgs"] if m.get("text")), "")
        bots.append({
            "templates": [{"template": t, "count": n, "first": first.get(t, 0)} for t, n in tcount.most_common()],
            "opening_templates": [t for t, _ in first.most_common()],
            "example": example, "language": language(texts), "llm_free_text": free_text,
            "duels": all_ids, "silent_duels": sorted(attached.get(root, [])),
            "sessions": dict(collections.Counter(by_id[i].get("session") for i in all_ids)),
            "n": len(all_ids), "roles_played": dict(collections.Counter(r["rival_role"] for r in rows)),
            "profile_basis": "session 2+" if any((r["session"] or 0) >= 2 for r in rows) else "session 1",
            "profile": {role: _role_profile([r for r in _latest(rows) if r["rival_role"] == role])
                        for role in ("buyer", "seller") if any(r["rival_role"] == role for r in _latest(rows))},
            "per_duel": rows})
    bots.sort(key=lambda b: (-b["n"], b["duels"][0]))
    for k, b in enumerate(bots, 1):
        b["id"] = f"B{k:02d}"
        b["play"] = play(b)
    silent_rows = [profile_duel(by_id[i]) for i in sorted(loose_silent)]
    if silent_rows:
        bots.append({"id": "SILENT", "templates": [], "opening_templates": [], "example": "", "language": "-",
                     "llm_free_text": False, "duels": sorted(loose_silent), "silent_duels": sorted(loose_silent),
                     "sessions": dict(collections.Counter(r["session"] for r in silent_rows)),
                     "n": len(silent_rows), "roles_played": dict(collections.Counter(r["rival_role"] for r in silent_rows)),
                     "profile": {"any": _role_profile(silent_rows)}, "per_duel": silent_rows,
                     "note": "never wrote in either duel of the pair; may be several teams",
                     "profile_basis": "all"})
        bots[-1]["play"] = play(bots[-1])
    return {"n_duels": len(duels), "n_bots": sum(1 for b in bots if b["id"] != "SILENT"),
            "merges": merges, "bots": bots}


# ---------------------------------------------------------------- match

def match(book: dict, text: str, item: str = "", top: int = 3) -> list:
    """Rank bots for a first message. Returns [(bot id, score, best template)], best first."""
    tpl = template(text, item)
    if not tpl:
        silent = [b for b in book["bots"] if b["id"] == "SILENT"]
        return [("SILENT", 1.0, "")] if silent else []
    scored = []
    for b in book["bots"]:
        best, best_t = 0.0, ""
        for t in b["templates"]:
            s = similarity(tpl, t["template"])
            if t["first"]:
                s = min(1.0, s + 0.05)    # opening lines are what we see first
            if s > best:
                best, best_t = s, t["template"]
        if best > 0:
            scored.append((b["id"], round(best, 3), best_t))
    scored.sort(key=lambda x: -x[1])
    if len(tokens(tpl)) >= LLM_TOKENS and (not scored or scored[0][1] < 0.7):
        llm = [b["id"] for b in book["bots"] if b.get("llm_free_text")]
        scored.insert(0, ("LLM?", 0.5, "free text, closest LLM bots: " + ", ".join(llm)))
    return scored[:top]


def confidence(ranked: list) -> str:
    if not ranked:
        return "none"
    s = ranked[0][1]
    margin = s - (ranked[1][1] if len(ranked) > 1 else 0.0)
    if s >= 0.95 and margin >= 0.15:
        return "high"
    if s >= 0.7 and margin >= 0.1:
        return "medium"
    return "low"


# ---------------------------------------------------------------- report

def _fmt(x, nd=2, suffix=""):
    return "-" if x is None else f"{x:.{nd}f}{suffix}"


def _role_cell(b: dict, key: str, nd=2, suffix="") -> str:
    parts = []
    for role, p in b["profile"].items():
        v = p.get(key)
        if v is not None:
            parts.append(f"{role[0]} {_fmt(v, nd, suffix)}")
    return " / ".join(parts) or "-"


def _top(d: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in d.items()) or "-"


def recognise(b: dict) -> str:
    if b["id"] == "SILENT":
        return "no message at all"
    if b.get("llm_free_text"):
        return "long free text, never repeats (LLM)"
    opening = b["opening_templates"][0] if b["opening_templates"] else ""
    ats = [p.get("open_at") for p in b["profile"].values() if p.get("open_at") is not None]
    when = f" at t+{int(min(ats))}" if ats else ""
    return f"`{opening[:70]}`{when}"


def markdown(book: dict, src: str) -> str:
    lines = [
        "# Duel book: the rival bots behind the colour aliases",
        "",
        f"Built by `tools/duel_book.py` from {book['n_duels']} duel snapshots in `{src}` (session 1 = Friday practice,"
        " session 2 = Saturday Duels I). A bot is a group of duels whose rival writes with the same text template"
        " (numbers -> N, item -> ITEM). Prices are read relative to OUR limit (x limit): a buyer rival opening at 0.56"
        " offers 56 % of our cost; a seller rival at 1.65 asks 165 % of our max. b = the rival was the buyer"
        " (we sold), s = the rival was the seller (we bought). Step = median concession per tick in primas, and as a"
        " share of the gap between its opening and our limit. Acceptable at = median tick (from the duel start) at"
        " which its offer first crosses our limit. Profile columns use session 2 when the bot played it (Friday"
        " practice had 12 ticks and our side was mostly silent), n counts every duel. Run `--match \"TEXT\"` on a"
        " first message to name the bot.",
        "",
        "| bot | example (first line) | n (s1/s2) | lang | shape | opening x limit @ tick | step P/tick (gap/tick)"
        " | acceptable at | reactive? | who accepted | final x limit | recognise it by | how to play it |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for b in book["bots"]:
        ex = (b["example"] or "").replace("|", "/")
        ex = ex if len(ex) <= 70 else ex[:67] + "..."
        sess = b["sessions"]
        n = f"{b['n']} ({sess.get(1, 0)}/{sess.get(2, 0)})"
        shapes = collections.Counter()
        tempo = collections.Counter()
        react = collections.Counter()
        acc = collections.Counter()
        for p in b["profile"].values():
            shapes.update(p["shapes"])
            tempo.update({k: v for k, v in p["tempo"].items() if k != "-"})
            react.update(p["reactive"])
            acc.update(p["accepted"])
        shape = _top(dict(shapes.most_common(2))) + (f"; {tempo.most_common(1)[0][0]}" if tempo else "")
        opening = []
        step = []
        for role, p in b["profile"].items():
            if p.get("open_vs_limit") is not None:
                opening.append(f"{role[0]} {p['open_vs_limit']:.2f} @{int(p['open_at'])}")
            if p.get("step_abs") is not None:
                step.append(f"{role[0]} {p['step_abs']:.1f} ({_fmt(p.get('step_frac_gap'), 2)})")
        lines.append(" | ".join([
            f"| {b['id']}", f"\"{ex}\"" if ex else "-", n, b["language"], shape,
            " / ".join(opening) or "-", " / ".join(step) or "-", _role_cell(b, "acceptable_at", 0),
            _top(dict(react.most_common())), _top(dict(acc.most_common())),
            _role_cell(b, "final_vs_limit"), recognise(b), b["play"] + " |"]))
    only = {k: [b for b in book["bots"] if b["id"] != "SILENT" and set(b["sessions"]) == {k}] for k in (1, 2)}
    if only[1] and only[2]:
        lines += ["", "## Same team across sessions?", "",
                  "Each session pairs us once with each of the same 17 teams, so a bot seen only on Friday is"
                  " most likely one of the bots (or silent pairs) seen only on Saturday. Closest template by"
                  " character overlap (a hint for a human):", ""]
        for b in only[1]:
            best = max(((max((difflib.SequenceMatcher(None, t["template"], u["template"]).ratio() for t in b["templates"]
                              for u in c["templates"]), default=0.0), c["id"]) for c in only[2]), default=(0, "-"))
            lines.append(f"- {b['id']} (`{(b['opening_templates'] or [''])[0][:50]}`): closest {best[1]}"
                         f" ({best[0]:.2f}); not merged")
    lines += ["", "## Evidence (duel ids per bot)", ""]
    for b in book["bots"]:
        extra = f"; silent in {b['silent_duels']}" if b["silent_duels"] and b["id"] != "SILENT" else ""
        lines.append(f"- **{b['id']}**: {b['duels']}{extra}. Templates: "
                     + "; ".join(f"`{t['template'][:60]}` x{t['count']}" for t in b["templates"][:4]))
    lines += ["", "## Merges (check these by eye)", ""]
    for m in book["merges"]:
        where = m.get("duel") or m.get("duels") or m.get("score")
        lines.append(f"- {m['step']} ({where}): `{m['a'][:60]}` + `{m['b'][:60]}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default=str(DEFAULT_DIR), help="folder of duel-NNNNN.json snapshots")
    ap.add_argument("--json", default=str(DEFAULT_JSON))
    ap.add_argument("--md", default=str(DEFAULT_MD))
    ap.add_argument("--no-write", action="store_true", help="print only")
    ap.add_argument("--no-pairs", action="store_true", help="do not merge the two duels of a pair")
    ap.add_argument("--match", help="a rival's first message: which bot is it?")
    ap.add_argument("--item", default="", help="the duel's item, so --match can template it")
    ap.add_argument("--book", help="match against this saved duel-book.json instead of rebuilding")
    a = ap.parse_args()
    if a.match is not None:
        if a.book:
            book = json.loads(Path(a.book).read_text())
        else:
            book = build(load(Path(a.dir).expanduser()), not a.no_pairs)
        ranked = match(book, a.match, a.item)
        bots = {b["id"]: b for b in book["bots"]}
        print(f"template: {template(a.match, a.item)!r}")
        print(f"confidence: {confidence(ranked)}")
        for bid, s, t in ranked:
            b = bots.get(bid)
            hint = ""
            if b:
                hint = " | " + "; ".join(
                    f"as {role}: {_top(dict(list(p['shapes'].items())[:2]))}, open {_fmt(p.get('open_vs_limit'))}x,"
                    f" step {_fmt(p.get('step_abs'), 1)} P/t, final {_fmt(p.get('final_vs_limit'))}x,"
                    f" {_top(p['accepted'])}" for role, p in b["profile"].items())
            print(f"  {bid:6} {s:.2f}  {t[:70]!r}{hint}")
        return
    src = Path(a.dir).expanduser()
    book = build(load(src), not a.no_pairs)
    print(f"{book['n_duels']} duels -> {book['n_bots']} bots")
    print("\nmerges:")
    for m in book["merges"]:
        where = m.get("duel") or m.get("duels") or m.get("score")
        print(f"  {m['step']:8} {where!s:14} {m['a'][:55]!r}\n  {'':8} {'':14} {m['b'][:55]!r}")
    print()
    for b in book["bots"]:
        print(f"{b['id']:6} n={b['n']:2} {b['language']} duels={b['duels']}")
        for t in b["templates"][:3]:
            print(f"         {t['count']:2}x {t['template'][:90]!r}")
    if not a.no_write:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(book, ensure_ascii=False, indent=1) + "\n")
        Path(a.md).write_text(markdown(book, str(src)))
        print(f"\nwrote {a.json} and {a.md}")


if __name__ == "__main__":
    main()
