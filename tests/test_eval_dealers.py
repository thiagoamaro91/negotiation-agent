"""tools/eval_dealers.py: the grader, the simulated dealer and the harness checks, on synthetic numbers only (no logs,
no network, nothing written).

- G: grade() reads the deal against our private value: in limit, breach, missed in-limit offer, shares clipped.
- S: SimDealer keeps the game's rules the bots rely on (one message per tick, offers lapse, accepts settle next tick).
- H: the real bot code replays a real dealer path exactly while its offers match, and hands over to the model once
  they differ; ORACLE takes the secret limit, NULL makes no deal, RECKLESS lights the guardrail.

    python3 -m unittest discover -s tests -p "test_eval_dealers.py"
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import eval_dealers as E  # noqa: E402


def nego(thread, team, D, U, deal=None, deal_by=None, side="buy", rarity="uncommon", set_="LAV", dealer="abuela"):
    """A rebuilt conversation as all_negotiations() returns it (prices only)."""
    resp = [[D[k + 1][0], D[k + 1][1]] if k + 1 < len(D) else None for k in range(len(U))]
    final = next(([p, k] for k, (p, f) in enumerate(D) if f), None)
    return {"thread": thread, "team": team, "dealer": dealer, "side": side, "kind": "card", "item": "LAV-07",
            "asset_id": 7 if side == "sell" else None, "rarity": rarity, "set": set_, "book": 25, "open_tick": 10,
            "source": "test", "D": [[10 + i, p, f] for i, (p, f) in enumerate(D)],
            "U": [[10 + i, u] for i, u in enumerate(U)], "resp": resp, "final": final,
            "outcome": "deal" if deal is not None else ("walked_after_final" if final else "no_deal"),
            "deal_price": deal, "deal_by": deal_by}


# Abuela's real thread 70 (numbers only): she opens 29, we step 1 P from 11, her final 22 after our 6th offer.
REAL_70 = ([(29, False), (26, False), (24, False), (24, False), (23, False), (22, False), (22, True)],
           [11, 12, 13, 14, 15, 16], 22, "took_final")


def field():
    """A small "other teams" sample for the model: same shape as thread 70, finals mostly at 21 (prior median 21)."""
    out = []
    for i, fin in enumerate((21, 21, 21, 23, 21, 21)):
        D = [(29, False), (26, False), (25, False), (24, False), (fin, True)]
        out.append(nego(100 + i, f"t{10 + i}", D, [11, 13, 15, 17], fin, "took_final"))
    return out


def case_from(r, model, private=40.0):
    key = E.class_key(r["dealer"], r["side"], r["rarity"], r["set"])
    ro, rb = model.refs(key, r["side"])
    return {"id": f"{r['dealer']}-{r['thread']}", "thread": r["thread"], "dealer": r["dealer"], "side": r["side"],
            "item": r["item"], "asset_id": r["asset_id"], "rarity": r["rarity"], "set": r["set"], "book": 25,
            "class": key, "opening": r["D"][0][1], "private": private, "private_source": "test", "ref_open": ro,
            "ref_best": rb, "welcome": False, "real_outcome": "test",
            "real": {k: r[k] for k in ("D", "U", "resp", "final", "outcome", "deal_price", "deal_by")}}


class Grader(unittest.TestCase):
    case = {"side": "buy", "private": 27.5, "ref_open": 29, "ref_best": 21, "opening": 29}

    def test_in_limit_buy(self):
        g = E.grade(self.case, 22, [29, 26, 22], L=22)
        self.assertEqual((g["deal_in_limit"], g["limit_breach"], g["missed_ok_offer"]), (1, 0, 0))
        self.assertAlmostEqual(g["range_share"], 7 / 8)
        self.assertEqual(g["limit_share"], 1.0)

    def test_over_private_value_is_a_breach_and_scores_nothing(self):
        g = E.grade(self.case, 28, [29, 28])          # LAT-06 at 28 against 27.5 (Friday)
        self.assertEqual((g["deal_in_limit"], g["limit_breach"], g["range_share"]), (0, 1, 0.0))

    def test_over_value_reads_book_x_multiplier_not_the_limit(self):
        # Friday's LAT-06: the bot's limit (30) let it pay 28; graded against a limit-derived 30 it is no breach,
        # but book x multiplier (25 x 1.1) says it paid over value.
        lax = dict(self.case, private=30.0, set="LAT", book=25)
        value = E.book_value(lax, {"LAT": 1.1})
        self.assertEqual(value, 27.5)
        g = E.grade(lax, 28, [29, 28], value=value)
        self.assertEqual((g["limit_breach"], g["over_value"]), (0, 1))
        self.assertEqual(E.grade(lax, 27, [29, 27], value=value)["over_value"], 0)   # under value: fine
        self.assertEqual(E.grade(lax, None, [29], value=value)["over_value"], 0)     # no deal, no overpay
        self.assertIsNone(E.book_value(dict(lax, side="sell"), {"LAT": 1.1}))        # buys only

    def test_sell_floor_is_mirrored(self):
        sell = {"side": "sell", "private": 17.5, "ref_open": 16, "ref_best": 20, "opening": 16}
        self.assertEqual(E.grade(sell, 17, [16, 17])["limit_breach"], 1)
        g = E.grade(sell, 19, [16, 19])
        self.assertEqual(g["deal_in_limit"], 1)
        self.assertAlmostEqual(g["range_share"], 0.75)

    def test_walking_from_an_in_limit_offer_is_missed(self):
        self.assertEqual(E.grade(self.case, None, [29, 25])["missed_ok_offer"], 1)
        self.assertEqual(E.grade(self.case, None, [29, 28])["missed_ok_offer"], 0)

    def test_share_is_clipped(self):
        self.assertEqual(E.share("buy", 17, 29, 21), 1.0)       # welcome price past the reference best
        self.assertEqual(E.share("buy", 31, 29, 21), 0.0)


class Sim(unittest.TestCase):
    def setUp(self):
        negos = field()
        self.model = E.DealerModel(negos, exclude_team="t03")
        self.case = case_from(nego(70, "t03", *REAL_70), self.model)

    def sim(self, prefix=True):
        params = E.conversation_params(self.case, self.model, None, True)
        return E.SimDealer(self.case, self.model, params, "s", True, prefix=prefix)

    def test_one_message_per_tick_and_answer_next_tick(self):
        s = self.sim()
        s.open_thread("abuela")
        s.say(s.TID, price=11)
        with self.assertRaises(E.BazaarError):
            s.say(s.TID, price=12)
        self.assertEqual(s.thread(s.TID)["standing_offers"][-1]["give"]["types"], ["card:LAV-07"])
        s.wait_tick()
        self.assertEqual(E.offer_cash(s.thread(s.TID)["standing_offers"][-1]), 26)   # the real answer to 11

    def test_offer_lapses_and_accept_settles_next_tick(self):
        s = self.sim()
        s.open_thread("abuela")
        for _ in range(E.EXPIRY):
            s.wait_tick()
        self.assertEqual(s.thread(s.TID)["standing_offers"], [])
        s2 = self.sim()
        s2.open_thread("abuela")
        s2.accept(s2.offers[-1]["id"])
        self.assertEqual(s2.status, "open")
        s2.wait_tick()
        self.assertEqual((s2.status, s2.deal), ("deal", (29, "took_ask")))


class Harness(unittest.TestCase):
    def setUp(self):
        self.model = E.DealerModel(field(), exclude_team="t03")
        self.case = case_from(nego(70, "t03", *REAL_70), self.model)
        self.cfg = {"cap": None, "step": 1, "anchor_frac": 0.40, "max_rounds": 40}

    def run_policy(self, policy, cfg=None, prefix=True, model_on=True):
        return E.simulate(self.case, self.model, policy, cfg or self.cfg, 0, 0, deterministic=True, prefix=prefix,
                          model_on=model_on)

    def test_bot_replays_the_real_thread_exactly(self):
        sim, _, out, price = self.run_policy("bot", model_on=False)
        ours = [e[3] for e in sim.events if e[1] == "us" and e[2] == "offer"]
        self.assertEqual(ours, [11, 12, 13, 14, 15, 16])
        self.assertEqual((price, sim.diverged_at), (22, None))

    def test_different_offers_hand_over_to_the_model(self):
        sim, params, _, price = self.run_policy("bot", dict(self.cfg, step=2))
        self.assertEqual(sim.diverged_at, 2)                      # 11 matches, 13 does not
        self.assertTrue(any(e[4] == "model" for e in sim.events))
        self.assertEqual(params["L"], 22)                         # the real final is this conversation's limit
        self.assertEqual(price, 22)

    def test_oracle_takes_the_secret_limit(self):
        _, params, _, price = self.run_policy("oracle")
        self.assertEqual(price, params["L"])
        self.assertEqual(E.grade(self.case, price, [], L=params["L"])["limit_share"], 1.0)

    def test_null_makes_no_deal(self):
        sim, _, _, price = self.run_policy("null")
        self.assertIsNone(price)
        self.assertFalse([e for e in sim.events if e[1] == "us" and e[2] in ("offer", "accept")])

    def test_reckless_lights_the_guardrail(self):
        case = dict(self.case, private=27.0)                      # her opening 29 is over our value
        sim, _, _, price = E.simulate(case, self.model, "reckless", self.cfg, 0, 0, deterministic=True)
        self.assertEqual(price, 29)
        self.assertEqual(E.grade(case, price, sim.offers_seen)["limit_breach"], 1)

    def test_bot_never_breaches_its_cap(self):
        sim, _, _, price = self.run_policy("bot", dict(self.cfg, cap=21))   # her final 22 is over the cap: walk
        self.assertIsNone(price)
        self.assertEqual(sim.closed_reason, "closed_by_us")


if __name__ == "__main__":
    unittest.main()
