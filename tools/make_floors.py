"""Write agent/rastro_floors.json (the El Rastro seller's config) from our holdings, our values and observed prices.

One entry per copy we can sell:
  - every copy beyond the one a page needs (we keep the lowest serial, as the seller's config always has), and
  - with --sell-sets, the single copies of those sets too (allow_last_copy), never on a --protect page.
floor     = ceil(our value of that copy + max(margin_min, margin_frac x value)). With several spares of one card we
            use the value of the second copy (25 % of the first) for all of them: whichever sells first, none
            sells under what it costs us.
start_ask = the median price teams paid each other for that card (else its set and rarity, else its rarity) from the
            public tape, one under the cheapest other ask on El Rastro for that card when that is still above the
            floor, and never under the floor. The seller steps down from there to the floor.

    python3 tools/make_floors.py                          # dry run: prints the diff, writes nothing
    python3 tools/make_floors.py --sell-sets MAL          # also our single MAL copies (x0.7 set, page nobody needs)
    python3 tools/make_floors.py --keep-existing          # keep the owner's prices, only add/drop entries
    python3 tools/make_floors.py --write                  # overwrite agent/rastro_floors.json
Keyless by default: holdings from logs/state/me.json brought forward with the public settlements in the feed. Run
tools/snapshot.py first for a fresh me.json; --keyed reads GET /api/me instead (read-only client).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "kit"))
import market_desk as md  # noqa: E402

FLOORS = ROOT / "agent" / "rastro_floors.json"
NOTE = ("El Rastro seller config, read by agent/rastro_seller.py and written by tools/make_floors.py. One entry per "
        "spare copy (asset id, not card ref). floor = our value of that copy + margin (the least cash we keep, net of "
        "any fee we pay); start_ask = the observed team price for that card (median), under the cheapest other ask "
        "when that is still above the floor. start_ask is used only when the asset has no live listing and no earlier "
        "price in today's log. The bot raises a floor to our private value + 1 if it is set lower, and skips an asset "
        "we no longer hold or whose card we hold only once (allow_last_copy sells a last copy). Set enabled to false "
        "to keep a line without selling it. Nothing is listed until the owner starts `run`.")


def build(holdings: dict, valuer: md.Valuer, tape: md.Tape, board: list, *, margin_min: float, margin_frac: float,
          sell_sets: tuple, protect: tuple, me_id: str = "t03") -> list:
    """The entries, pure. holdings: {ref: [asset dicts]}."""
    asks: dict = {}
    for o in board or []:
        chk = md.check_listing(o, me_id)
        if chk["ok"]:
            asks[chk["ref"]] = min(asks.get(chk["ref"], 10 ** 9), chk["price"])
    out = []
    for ref in sorted(holdings):
        copies = sorted((a for a in holdings[ref] if isinstance(a, dict) and isinstance(a.get("id"), int)),
                        key=lambda a: (a.get("serial") or 0, a["id"]))
        if not copies:
            continue
        info = valuer.info(ref)
        first = valuer.first(ref)
        if len(copies) >= 2:
            sell, last = copies[1:], False
            value = first * valuer.marginal(1)
        elif info["set"] in sell_sets and info["set"] not in protect:
            sell, last = copies, True
            value = first * valuer.marginal(0)
        else:
            continue
        floor = int(math.ceil(value + max(margin_min, margin_frac * value)))
        ps, scope = tape.prices(ref, info["set"], info["rarity"])
        ref_price = int(round(statistics.median(ps))) if ps else floor
        start = max(floor, ref_price)
        if ref in asks and asks[ref] - 1 >= floor:
            start = min(start, asks[ref] - 1)
        why = (f"value {value:.1f} + margin -> floor {floor}; " +
               (f"median {ref_price} of {len(ps)} {scope} trades" if ps else "no trades seen") +
               (f"; cheapest other ask {asks[ref]}" if ref in asks else ""))
        for a in sell:
            e = {"asset_id": a["id"], "card": ref, "start_ask": start, "floor": floor}
            if last:
                e["allow_last_copy"] = True
            out.append({"entry": e, "why": why, "serial": a.get("serial"), "value": value})
    return out


def render(note: str, venue: str, entries: list) -> str:
    """The file in the hand-written layout: one card per line."""
    rows = [json.dumps(e, ensure_ascii=False) for e in entries]
    body = ",\n".join("  " + r for r in rows)
    return ("{\n" f' "_note": {json.dumps(note, ensure_ascii=False)},\n' f' "venue": {json.dumps(venue)},\n'
            ' "cards": [\n' + body + ("\n" if rows else "") + " ]\n}\n")


def diff(old: list, new: list) -> list:
    """Human lines: + added, - removed, ~ changed, = same."""
    o = {int(c["asset_id"]): c for c in old}
    n = {int(c["asset_id"]): c for c in new}
    lines = []
    for aid in sorted(set(o) | set(n), key=lambda x: ((n.get(x) or o.get(x))["card"], x)):
        a, b = o.get(aid), n.get(aid)
        if a and not b:
            lines.append(f"- {a['card']} #{aid}: floor {a['floor']}, start {a['start_ask']} (no longer a spare we hold)")
        elif b and not a:
            lines.append(f"+ {b['card']} #{aid}: floor {b['floor']}, start {b['start_ask']}"
                         + (" (last copy)" if b.get("allow_last_copy") else ""))
        else:
            ch = [f"{k} {a.get(k)} -> {b.get(k)}" for k in ("floor", "start_ask", "allow_last_copy", "enabled")
                  if a.get(k) != b.get(k)]
            lines.append(f"{'~' if ch else '='} {b['card']} #{aid}: " + (", ".join(ch) if ch else
                                                                         f"floor {b['floor']}, start {b['start_ask']}"))
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="Write agent/rastro_floors.json from our values and observed prices")
    ap.add_argument("--write", action="store_true", help="overwrite the config (default: dry run, diff only)")
    ap.add_argument("--out", default=str(FLOORS))
    ap.add_argument("--keyed", action="store_true", help="read GET /api/me with the key (read-only)")
    ap.add_argument("--me", default=str(md.ME_SNAPSHOT))
    ap.add_argument("--feed", action="append", default=None, help="recorded feed JSONL for the tape (repeatable)")
    ap.add_argument("--catalog", default=None, help="catalog JSON (default: GET /api/catalog, keyless)")
    ap.add_argument("--no-board", action="store_true", help="do not read the El Rastro board (offline)")
    ap.add_argument("--margin-min", type=float, default=3.0)
    ap.add_argument("--margin-frac", type=float, default=0.10)
    ap.add_argument("--sell-sets", default="", help="sets whose single copies we also sell, e.g. MAL")
    ap.add_argument("--protect", default="LAV", help="pages whose single copies are never sold")
    ap.add_argument("--keep-existing", action="store_true",
                    help="keep the floor and start_ask already in the file for assets it lists (raised to our value "
                         "of the copy + 1 if under it, as the seller does); only add new spares and drop copies we "
                         "no longer hold")
    args = ap.parse_args()
    sets = lambda s: tuple(x.strip().upper() for x in s.split(",") if x.strip())  # noqa: E731
    public = md.PublicClient()
    catalog = json.loads(Path(args.catalog).read_text()) if args.catalog else public.catalog()
    feeds = args.feed if args.feed is not None else [p for p in md.FEED_FILES if p.exists()][:1]
    tape = md.Tape().ingest(md.read_feed_files(feeds))
    if not args.no_board:
        try:
            tape.ingest(public.feed(500).get("events", []))
        except md.BazaarError as e:
            print(f"(live feed unread: {e.code})")
    if args.keyed:
        md.load_env()
        b = md.ReadOnlyBazaar(os.environ.get("BAZAAR_URL", md.URL), os.environ["BAZAAR_KEY"], wait_on_tick=False)
        me = b.me()
        acct = {"id": me["id"], "assets": me.get("assets") or [], "affinity": me.get("affinity") or {},
                "source": "api"}
    else:
        me = json.loads(Path(args.me).read_text())
        acct = md.offline_account(me, [], tape, 10 ** 9)
    holdings = md.holdings_of(acct["assets"])
    valuer = md.Valuer(catalog, acct["affinity"], {r: len(v) for r, v in holdings.items()})
    board = [] if args.no_board else public.board(md.HOME).get("offers", [])
    rows = build(holdings, valuer, tape, board, margin_min=args.margin_min, margin_frac=args.margin_frac,
                 sell_sets=sets(args.sell_sets), protect=sets(args.protect), me_id=acct["id"])
    out = Path(args.out)
    old = json.loads(out.read_text()) if out.exists() else {"cards": []}
    keep_off = {int(c["asset_id"]) for c in old.get("cards", []) if c.get("enabled", True) is False}
    owner = {int(c["asset_id"]): c for c in old.get("cards", [])}
    entries = []
    for r in rows:
        e = dict(r["entry"])
        if e["asset_id"] in keep_off:
            e["enabled"] = False
        if args.keep_existing and e["asset_id"] in owner:   # the owner's prices stand, above our value of the copy
            o = owner[e["asset_id"]]
            e["floor"] = max(int(math.ceil(r["value"])) + 1, int(o.get("floor") or 0))   # the seller's own hard floor
            e["start_ask"] = max(e["floor"], int(o.get("start_ask") or 0))
        entries.append(e)
    print(f"holdings: {acct.get('source')}; values: catalog book x our multipliers x copy marginals "
          f"{valuer.marginals}; margin max({args.margin_min:g}, {args.margin_frac:.0%})")
    for r in rows:
        print(f"  {r['entry']['card']} #{r['entry']['asset_id']} (serial {r['serial']}): {r['why']} -> "
              f"start {r['entry']['start_ask']}")
    print("diff against", out.relative_to(ROOT) if out.is_relative_to(ROOT) else out)
    for ln in diff(old.get("cards", []), entries):
        print("  " + ln)
    if args.write:
        out.write_text(render(NOTE, old.get("venue", md.HOME), entries))
        print(f"wrote {len(entries)} entries to {out}")
    else:
        print("dry run: nothing written (--write to overwrite)")


if __name__ == "__main__":
    main()
