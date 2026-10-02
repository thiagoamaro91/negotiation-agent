"""Memory for the Abuela agent: learn from every past conversation, ours (good and bad) and other teams' (public), before each run.

    from memory import Memory
    mem = Memory.refresh(b)            # pulls our transcripts + the public feed, re-analyses, rewrites logs/memory/*
    adv = mem.advice("unc")            # what to do next time for an uncommon: probe, ceiling, expected final, ...

Files (all committed, so the whole team and the judges can read what the agent learned):
    logs/memory/samples.jsonl      one parsed conversation per line (idempotent: keyed by source + thread id)
    logs/memory/abuela_memory.json derived numbers per item kind (what advice() reads)
    logs/memory/lessons.md         human-readable: every deal of ours graded good/bad, and what changed in the advice

What a "sample" is: one conversation with Abuela, reduced to her ask path, our bid path, whether she named a final, and the outcome.
We read only STRUCTURE (the offers), never her words, except to notice a gift ("a little present").

Facts the grading rests on (from the public feed, Friday): her ask follows a schedule that drops ~1 P a round whatever our step is;
a "final" is where that schedule has got to after ~5-8 of our bids, not her floor; she accepts bids below her current ask, so the
lowest ACCEPTED bid in the data is the best evidence of her floor, and the highest REFUSED bid is the evidence against.
"""
from __future__ import annotations

import json
import re
import statistics as st
from pathlib import Path

from runlog import LOGS, write_json

MEM = LOGS / "memory"
RARITY_BY_NO = {1: "com", 2: "com", 3: "com", 4: "com", 5: "com", 6: "unc", 7: "unc", 8: "unc", 9: "rare", 10: "rare", 11: "epic", 12: "leg"}
DEFAULTS = {  # priors from Friday's public data; replaced by evidence as samples arrive
    "pack": {"welcome": 17, "opening": 30, "final": 22, "accept": 19},
    "unc": {"welcome": 17, "opening": 29, "final": 22, "accept": 21},
    "com": {"welcome": 7, "opening": 12, "final": 9, "accept": 9},
}


def kind_of(ref: str) -> str | None:
    if ref.startswith("sobre_"):
        return "pack"
    m = re.match(r"^[A-Z]{3}-(\d+)$", ref or "")
    return RARITY_BY_NO.get(int(m.group(1))) if m else None


def _cash(o: dict) -> int:
    return int((o.get("want") or {}).get("cash") or (o.get("give") or {}).get("cash") or 0)


def _topic_ref(topic: dict | None) -> str | None:
    buy = (topic or {}).get("buy") or {}
    return buy.get("card") or buy.get("pack")


def is_welcome(s: dict) -> bool:
    """Her fixed first-deal price: the ask never moved and we paid exactly that ask (any bid of ours in the thread was just noise)."""
    return s["outcome"] == "deal" and bool(s["asks"]) and len(set(s["asks"])) == 1 and s["price"] == s["asks"][0]


# ------------------------------------------------------------------------------------------ parsing

def sample_from_transcript(t: dict, me_team: str | None, source: str = "own") -> dict | None:
    """One thread (as GET /api/threads/{id} returns it) -> a sample. Returns None if it is not a buy from Abuela."""
    if t.get("with") != "abuela":
        return None
    ref = _topic_ref(t.get("topic"))
    if not ref or kind_of(ref) is None:
        return None
    asks, bids, final_ask, price, gift = [], [], None, None, False
    for m in t.get("messages", []):
        o = m.get("offer") or {}
        if m.get("sender") == "abuela" and o:
            asks.append(_cash(o))
            if o.get("final"):
                final_ask = _cash(o)
            if o.get("status") == "settled":
                price = _cash(o)
            gift = gift or bool(re.search(r"present|gift|regalo", m.get("text") or "", re.I))
        elif o:
            bids.append(_cash(o))
            if o.get("status") == "settled":
                price = _cash(o)
    deal = t.get("status") == "deal"
    return {"source": source, "thread": t["id"], "team": t.get("team") or me_team, "item": ref, "kind": kind_of(ref), "asks": asks,
            "bids": bids, "final_ask": final_ask, "outcome": "deal" if deal else (t.get("status") or "open"),
            "price": price if deal else None, "gift": gift, "closed_reason": t.get("closed_reason")}


def samples_from_feed(events: list[dict]) -> list[dict]:
    """Rebuild other teams' conversations from the public feed (message text is hidden there; the offers are not)."""
    th: dict[int, dict] = {}
    for e in sorted(events, key=lambda e: e["id"]):
        p = e["payload"]
        if e["type"] == "thread.opened" and p.get("with") == "abuela":
            th[p["thread"]] = {"id": p["thread"], "team": p["team"], "with": "abuela", "topic": p.get("topic"), "messages": [], "status": "open", "last": e["tick"]}
        elif e["type"] == "thread.message" and p.get("thread") in th and p.get("offer"):
            o = p["offer"]
            th[p["thread"]]["messages"].append({"sender": "abuela" if o["maker"] == "abuela" else o["maker"], "offer": o})
            th[p["thread"]]["last"] = e["tick"]
        elif e["type"] == "settlement" and p.get("persona") == "abuela":
            team = next((x for x in p["parties"] if x != "abuela"), None)
            refs = {i.get("ref") for i in p.get("items", [])}
            cands = [t for t in th.values() if t["team"] == team and _topic_ref(t["topic"]) in refs and t["status"] == "open" and t["last"] <= e["tick"]]
            if cands:
                c = max(cands, key=lambda t: t["last"])
                c["status"], c["price"] = "deal", p["price"]
    out = []
    for t in th.values():
        s = sample_from_transcript(t, t["team"], "public")
        if s and s["asks"]:
            if s["outcome"] == "deal":
                s["price"] = t.get("price")
            out.append(s)
    return out


# ------------------------------------------------------------------------------------------ memory

class Memory:
    def __init__(self, samples: list[dict], me_team: str | None):
        self.samples, self.me = samples, me_team
        self.stats = self.analyse()

    # ---- load / refresh
    @classmethod
    def load(cls, me_team: str | None = None) -> "Memory":
        path = MEM / "samples.jsonl"
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []
        return cls(rows, me_team)

    @classmethod
    def refresh(cls, b, public: bool = True, quiet: bool = False) -> "Memory":
        """Pull our conversations (every one the server holds) and the public feed, merge, re-analyse, rewrite files, print the brief."""
        me = b.me()
        team = me.get("id") or (me.get("score") or {}).get("team")
        known = {(s["source"], s["thread"]): s for s in cls.load(team).samples}
        for t in b.my_threads().get("threads", []):
            full = b.thread(t["id"])
            write_json(LOGS / "threads" / f"thread-{int(t['id']):05d}.json", full)     # same files snapshot.py writes
            s = sample_from_transcript(full, team, "own")
            if s and s["outcome"] != "open":
                known[("own", s["thread"])] = s
        if public:
            try:
                for s in samples_from_feed(b.feed(1000).get("events") or []):
                    if s["team"] != team and s["outcome"] != "open":
                        known[("public", s["thread"])] = s
            except Exception as e:  # the feed is a bonus: never block a run on it
                print(f"[memory] public feed unavailable ({e})")
        mem = cls(list(known.values()), team)
        mem.save(me)
        if not quiet:
            print(mem.brief())
        return mem

    def save(self, me: dict | None = None) -> None:
        MEM.mkdir(parents=True, exist_ok=True)
        (MEM / "samples.jsonl").write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in sorted(self.samples, key=lambda s: (s["source"], s["thread"]))))
        write_json(MEM / "abuela_memory.json", self.stats)
        (MEM / "lessons.md").write_text(self.lessons(me))

    # ---- analysis
    def analyse(self) -> dict:
        out: dict = {}
        for kind, prior in DEFAULTS.items():
            ss = [s for s in self.samples if s["kind"] == kind]
            deals = [s for s in ss if s["outcome"] == "deal" and s["price"]]
            welcome = [s["price"] for s in deals if is_welcome(s)]                          # her fixed welcome price
            negotiated = [s for s in deals if s["bids"] and not is_welcome(s)]
            by_bid = [s["price"] for s in negotiated if s["price"] in s["bids"]]            # a bid of OURS she accepted: evidence of her floor
            finals = [s["final_ask"] for s in ss if s["final_ask"]]
            # a bid she did not take is a refusal: all our bids when we ended on her ask/final, all but the last when she took a bid of ours
            refused = [max((s["bids"][:-1] if s["price"] in s["bids"] else s["bids"]), default=0) for s in negotiated]
            bids_to_final = [len([b for b in s["bids"]]) for s in ss if s["final_ask"]]
            opening = [s["asks"][0] for s in ss if s["asks"] and s["bids"]]                 # her ask before any bid (welcome deals excluded)
            out[kind] = {
                "n": len(ss), "n_deals": len(deals), "n_negotiated": len(negotiated),
                "welcome": round(st.median(welcome)) if welcome else prior["welcome"],
                "opening": round(st.median(opening)) if opening else prior["opening"],
                "final": round(st.median(finals)) if finals else prior["final"],
                "bids_to_final": round(st.median(bids_to_final)) if bids_to_final else 6,
                "accept_low": min(by_bid) if by_bid else prior["accept"],                   # lowest price she ever took from a bid
                "refused_high": max(refused) if refused else 0,                             # highest bid she refused on the way to a deal
                "deal_prices": sorted(s["price"] for s in negotiated),
            }
        return out

    def advice(self, kind: str) -> dict:
        s = self.stats.get(kind) or self.analyse()[kind]
        probe = max(s["refused_high"] + 1, s["accept_low"] - 1)           # one under the lowest price she has accepted, above what she refused
        return {"probe": probe, "ceiling": max(probe, s["final"] - 1), "expected_final": s["final"], "bids_to_final": s["bids_to_final"],
                "welcome": s["welcome"], "opening": s["opening"], "confidence": s["n_negotiated"]}

    # ---- grading our own deals
    def grade(self, s: dict) -> tuple[str, str]:
        st_ = self.stats[s["kind"]]
        paid, others = s["price"], [p["price"] for p in self.samples if p["source"] == "public" and p["kind"] == s["kind"] and p["outcome"] == "deal" and p["bids"]]
        if is_welcome(s):
            return "neutral", f"took her welcome price {paid} P (fixed ~{st_['welcome']}); it never counts toward the ladder, so use it once, on the item with the biggest private gain"
        if s["outcome"] == "deal":
            best = min(others + [paid])
            if s["final_ask"] and paid == s["final_ask"] and best < paid:
                return "bad", f"took her final {paid} P but another team paid {best} P for the same kind"
            if others and paid <= st.median(others):
                return "good", f"paid {paid} P, at or under the median {round(st.median(others))} P other teams paid (lowest {best} P)"
            return "ok", f"paid {paid} P; other teams paid {round(st.median(others))} P (lowest {best} P)" if others else f"paid {paid} P (no comparison yet)"
        why = f", closed: {s['closed_reason']}" if s.get("closed_reason") else ""
        return ("bad", f"no deal after {len(s['bids'])} bids{why}") if s["bids"] else ("neutral", f"talked only ({s['outcome']}{why})")

    def lessons(self, me: dict | None = None) -> str:
        mine = [s for s in sorted(self.samples, key=lambda s: s["thread"]) if s["source"] == "own"]
        lines = ["# What the Abuela agent has learned", "", f"{len(self.samples)} conversations analysed ({len(mine)} ours, {len(self.samples) - len(mine)} other teams', public).", ""]
        lines += ["## Our conversations, graded", "", "| thread | item | result | grade | why |", "|---|---|---|---|---|"]
        for s in mine:
            g, why = self.grade(s)
            lines.append(f"| {s['thread']} | {s['item']} | {s['outcome']}{' @ ' + str(s['price']) if s['price'] else ''}{' (gift)' if s['gift'] else ''} | **{g}** | {why} |")
        lines += ["", "## What we know about her, per item kind", "", "| kind | samples | welcome | opens at | final lands at | bids before final | lowest accepted bid | highest refused | probe | ceiling |", "|---|---|---|---|---|---|---|---|---|---|"]
        for k, s in self.stats.items():
            a = self.advice(k)
            lines.append(f"| {k} | {s['n']} ({s['n_negotiated']} negotiated) | {s['welcome']} | {s['opening']} | {s['final']} | {s['bids_to_final']} | {s['accept_low']} | {s['refused_high'] or '-'} | {a['probe']} | {a['ceiling']} |")
        lines += ["", "Reading it: **probe** is where the next negotiation aims (one under the lowest price she has ever accepted, above anything she refused);",
                  "**ceiling** is the most we bid before she names a final. If she names a final at or under our private value we still take it.", ""]
        return "\n".join(lines)

    def brief(self) -> str:
        lines = [f"[memory] {len(self.samples)} conversations ({sum(s['source'] == 'own' for s in self.samples)} ours). advice:"]
        for k in self.stats:
            a = self.advice(k)
            lines.append(f"[memory]   {k:4} probe={a['probe']:>3} ceiling={a['ceiling']:>3} final~{a['expected_final']:>3} welcome={a['welcome']:>3} (from {a['confidence']} negotiated deals)")
        bad = [s for s in self.samples if s["source"] == "own" and self.grade(s)[0] == "bad"]
        for s in bad:
            lines.append(f"[memory] LESSON thread {s['thread']} {s['item']}: {self.grade(s)[1]}")
        return "\n".join(lines)


if __name__ == "__main__":      # python3 agent/memory.py  -> rebuild from the committed transcripts only (no network)
    import sys
    rows = []
    for p in sorted((LOGS / "threads").glob("thread-*.json")):
        t = json.loads(p.read_text())
        s = sample_from_transcript(t, t.get("team"), "own")
        if s and s["outcome"] != "open":
            rows.append(s)
    m = Memory(rows, None)
    m.save()
    print(m.brief())
    sys.exit(0)
