"""Every team's deck, rebuilt from the public feed by asset id. Keyless.

Every card copy in the game is one asset with a unique id, minted in order, so the public record says a lot more than
"cards seen in a trade":
- starter hands: each team got STARTER ids in a row, in the order the teams joined (t01 1-15, t02 16-30, t03 31-45);
- a pack opening mints its cards as consecutive ids; when the feed shows the pack's best card (`best`, the last slot)
  the whole block is known to be that team's, otherwise only how many cards it added;
- a listing names the maker's assets (it holds them), a settlement moves each asset to its new holder;
- a gift or an easter egg names the card but not its id; the Workshop names the card made, not the three commons
  burned.
So for each team: the copies we can name, the copies we know it owns but have never seen (a starter or pack card never
listed or traded), cards from packs whose ids we cannot place, and the Workshop burns we cannot name. Checked against
our own account (the one deck we know): `python3 tools/decks.py` prints the check and every team's deck.

It also writes the id list for a census top-up (tools/census.py reads every asset by id with the team key; a top-up
re-reads only the ids that may have changed since a full walk):

    python3 tools/decks.py moved --base ~/bazaar-census/out/cards-2026-10-03-t<TICK>.json --out ~/bazaar-census/moved.txt

`moved` = every asset id in a public settlement since the census started (cards and packs changing hands, dealer
copies minted), every id above the census's highest up to the highest id the feed has shown since (a listing, a
settlement, a pack's best card) plus a margin, which covers every new mint, even those the feed never names (packs
without a best card, gifts, eggs, Workshop cards), our own logged Workshop burns, and every common the census gave a
team that has crafted at the Workshop since (the feed never names the three commons it burns). Ids only, one per line.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import value_inference as vi  # noqa: E402

STARTER = 15          # starter ids per team, in join order (checked: our block is 31-45)
CRAFT_BURN = 3        # the Workshop turns three commons into one card


def pack_sizes(cat: dict) -> dict:
    return {p["id"]: len(p.get("slots") or []) for p in cat.get("packs") or [] if isinstance(p, dict)}


def build(events: list, cat: dict, upto: int | None = None) -> dict:
    """team -> {known: {ref: n}, unknown_ids: n, floating: {ref: n}, unplaced: n, burned: n, total: n, ids: [...]}"""
    names = {c["name"]: c["id"] for s in cat["sets"] for c in s["cards"]}
    sizes = pack_sizes(cat)
    order = [e["payload"]["team"] for e in events if e["type"] == "team.joined"]
    teams = set(order)
    holder: dict = {}   # asset id -> current holder (team or dealer)
    ref_of: dict = {}   # asset id -> card ref, once any public event shows it
    for k, team in enumerate(order):
        for i in range(k * STARTER + 1, (k + 1) * STARTER + 1):
            holder[i] = team
    floating = collections.defaultdict(collections.Counter)  # cards a team got without an id (gift, egg, Workshop)
    unplaced = collections.Counter()   # pack cards whose ids we cannot place
    burned = collections.Counter()
    packs = collections.Counter()

    def place(aid: int, ref: str | None, first: str | None, now: str | None) -> None:
        """An asset shown by a public event: `first` held it when it was shown, `now` holds it after the event. The
        first sight of an id that no starter or anchored pack block explains is a card its team got without a known
        id: a gift or Workshop card of that name if there is one, else one of its unplaced pack cards."""
        if aid not in ref_of and aid not in holder and first in teams:
            if ref and floating[first][ref] > 0:
                floating[first][ref] -= 1
            elif unplaced[first] > 0:
                unplaced[first] -= 1
        if ref:
            ref_of[aid] = ref
        if now is not None:
            holder[aid] = now

    for e in events:
        if upto is not None and e["tick"] > upto:
            break
        p, kind = e["payload"], e["type"]
        if kind == "offer.listed":
            o = p.get("offer") or {}
            maker = o.get("maker")
            for a in (o.get("give") or {}).get("assets") or []:
                if isinstance(a, dict) and a.get("kind") == "card" and isinstance(a.get("id"), int):
                    team = maker if maker in teams else None
                    place(a["id"], a.get("ref"), team, team)
        elif kind == "settlement":
            for it in p.get("items") or []:
                if it.get("kind") == "card" and isinstance(it.get("id"), int):
                    place(it["id"], it.get("ref"), it.get("frm"), it.get("to"))
        elif kind == "pack.opened" and p.get("team") in teams:
            team, n = p["team"], sizes.get(p.get("pack"), 0)
            packs[team] += 1
            best = p.get("best") if isinstance(p.get("best"), dict) else None
            if best and isinstance(best.get("id"), int):
                for aid in range(best["id"] - n + 1, best["id"] + 1):
                    if aid not in holder:
                        holder[aid] = team
                ref_of[best["id"]] = best.get("ref")
            else:
                unplaced[team] += n
        elif kind in ("gift.given", "egg.given") and p.get("team") in teams:
            for ref in p.get("cards") or []:
                floating[p["team"]][ref] += 1
        elif kind == "taller.crafted" and p.get("team") in teams:
            burned[p["team"]] += CRAFT_BURN
            ref = names.get(p.get("card"))
            if ref:
                floating[p["team"]][ref] += 1
    out = {}
    for team in order:
        mine = [aid for aid, h in holder.items() if h == team]
        known = collections.Counter(ref_of[a] for a in mine if a in ref_of)
        unknown = sum(1 for a in mine if a not in ref_of)
        fl = {r: n for r, n in floating[team].items() if n > 0}
        total = sum(known.values()) + unknown + sum(fl.values()) + unplaced[team] - burned[team]
        out[team] = {"known": dict(sorted(known.items())), "unknown_ids": unknown, "floating": fl,
                     "unplaced": unplaced[team], "burned": burned[team], "packs": packs[team], "total": total,
                     "ids": sorted(mine)}
    return out


def check(deck: dict, assets: list) -> dict:
    """Our rebuilt deck against our real assets: ids right, missed, wrong; card names right among the named ones."""
    truth = {a["id"]: a["ref"] for a in assets if a.get("kind") == "card" and isinstance(a.get("id"), int)}
    ids = set(deck["ids"])
    right = ids & set(truth)
    return {"real": len(truth), "rebuilt": deck["total"], "ids_right": len(right), "ids_missed": len(set(truth) - ids),
            "ids_wrong": len(ids - set(truth)), "named": sum(deck["known"].values()),
            "names_right": sum(min(n, collections.Counter(truth.values())[r]) for r, n in deck["known"].items()),
            "missed": sorted(set(truth) - ids)}


MINT_MARGIN = 40      # ids above the highest one the feed has shown, for mints it never names


def snapshot_bounds(snap: dict) -> tuple:
    """(tick the census started, highest asset id it found) from a tools/census.py snapshot."""
    meta = snap.get("meta") or {}
    tick = meta.get("tick_start") if isinstance(meta.get("tick_start"), int) else meta.get("tick_end")
    ids = [x["id"] for k in ("cards", "packs") for x in snap.get(k) or [] if isinstance(x.get("id"), int)]
    return tick, max(ids, default=0)


def moved(events: list, cat: dict, snap: dict, since: int | None = None, margin: int = MINT_MARGIN,
          conversions: list | None = None) -> tuple:
    """The ids a census top-up must re-read, and why. `since` defaults to the census's start tick (cards could move
    while it walked)."""
    start, base_max = snapshot_bounds(snap)
    since = since if since is not None else start
    if since is None:
        raise ValueError("the census snapshot has no tick: pass --since")
    ids, why = set(), collections.Counter()
    seen_max, crafters = base_max, set()
    for e in events:
        if e["tick"] < since:
            continue
        p, kind = e["payload"], e["type"]
        if kind == "settlement":
            for it in p.get("items") or []:
                if isinstance(it.get("id"), int):
                    ids.add(it["id"])
                    why["settled"] += 1
                    seen_max = max(seen_max, it["id"])
        elif kind == "offer.listed":
            for a in ((p.get("offer") or {}).get("give") or {}).get("assets") or []:
                if isinstance(a, dict) and isinstance(a.get("id"), int):
                    seen_max = max(seen_max, a["id"])
        elif kind == "pack.opened":  # a pack's cards are minted above the census: its best card raises the range
            best = p.get("best") if isinstance(p.get("best"), dict) else None
            if best and isinstance(best.get("id"), int):
                seen_max = max(seen_max, best["id"])
        elif kind == "taller.crafted" and p.get("team"):
            crafters.add(p["team"])
    new = set(range(base_max + 1, seen_max + margin + 1))
    ids |= new
    why["above the census"] = len(new)
    for c in conversions or []:
        if isinstance(c.get("tick"), int) and c["tick"] >= since:
            for x in (c.get("burned") or []) + (c.get("got") or []):
                aid = x.get("id") if isinstance(x, dict) else x
                if isinstance(aid, int):
                    ids.add(aid)
                    why["our Workshop"] += 1
    for card in snap.get("cards") or []:
        if card.get("owner") in crafters and card.get("rarity") == "common" and isinstance(card.get("id"), int):
            ids.add(card["id"])
            why["commons of crafters"] += 1
    return sorted(ids), {"since": since, "census_max_id": base_max, "feed_max_id": seen_max,
                         "crafters": sorted(crafters), "why": dict(why)}


def cmd_moved(argv: list) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="decks.py moved", description="Ids a census top-up must re-read (ids only).")
    ap.add_argument("--base", type=Path, required=True, help="the census snapshot (tools/census.py run)")
    ap.add_argument("--since", type=int, help="first tick to look at (default: the census's start tick)")
    ap.add_argument("--margin", type=int, default=MINT_MARGIN)
    ap.add_argument("--out", type=Path, help="write the ids here, one per line (default: print them)")
    args = ap.parse_args(argv)
    snap = json.loads(args.base.expanduser().read_text(encoding="utf-8"))
    try:
        convs = json.loads(vi.CONVERSIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        convs = []
    ids, info = moved(vi.rows("feed.jsonl"), vi.catalog(), snap, args.since, args.margin, convs)
    text = "".join(f"{i}\n" for i in ids)
    if args.out:
        args.out.expanduser().parent.mkdir(parents=True, exist_ok=True)
        args.out.expanduser().write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    print(f"moved: {len(ids)} ids since tick {info['since']} (census max id {info['census_max_id']}, feed max id "
          f"{info['feed_max_id']}); {info['why']}; crafters since: {', '.join(info['crafters']) or 'none'}"
          + (f" -> {args.out}" if args.out else ""), file=sys.stderr)


def main() -> None:
    if sys.argv[1:2] == ["moved"]:
        return cmd_moved(sys.argv[2:])
    cat = vi.catalog()
    events = vi.rows("feed.jsonl")
    me = json.loads(vi.ME.read_text(encoding="utf-8"))  # the raw snapshot (the relayed copy may carry Workshop edits)
    then = build(events, cat, upto=me["tick"])
    print(f"check at our account's tick {me['tick']}: {check(then[vi.US], me['assets'])}")
    for team, d in build(events, cat).items():
        print(f"{team}: ~{d['total']} cards · named {sum(d['known'].values())} · owned unseen {d['unknown_ids']} · "
              f"no id {sum(d['floating'].values())} · packs unplaced {d['unplaced']} · burned {d['burned']}")


if __name__ == "__main__":
    main()
