"""Every team's deck from public asset ids (tools/decks.py). Run: python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import decks  # noqa: E402

CAT = {"sets": [{"id": "LAV", "cards": [{"id": "LAV-01", "name": "Uno"}, {"id": "LAV-06", "name": "La Tabacalera"},
                                        {"id": "LAV-09", "name": "Nueve"}]}],
       "packs": [{"id": "sobre_barrio", "slots": [{}, {}, {}]}, {"id": "sobre_plata", "slots": [{}, {}, {}, {}, {}]}]}
N = decks.STARTER


def ev(tick, kind, **payload):
    return {"tick": tick, "type": kind, "payload": payload}


def listed(tick, maker, *assets):
    return ev(tick, "offer.listed", offer={"maker": maker, "give": {"assets": [
        {"id": i, "kind": "card", "ref": r} for i, r in assets]}})


def settled(tick, frm, to, aid, ref):
    return ev(tick, "settlement", items=[{"id": aid, "kind": "card", "ref": ref, "frm": frm, "to": to}])


JOINED = [ev(0, "team.joined", team="t02"), ev(0, "team.joined", team="t01")]   # join order, not team number


class Decks(unittest.TestCase):
    def test_starter_blocks_follow_the_join_order(self):
        d = decks.build(JOINED, CAT)
        self.assertEqual(d["t02"]["ids"], list(range(1, N + 1)))
        self.assertEqual(d["t01"]["ids"], list(range(N + 1, 2 * N + 1)))
        self.assertEqual((d["t02"]["total"], d["t02"]["unknown_ids"], d["t02"]["known"]), (N, N, {}))

    def test_listings_name_cards_and_settlements_move_them(self):
        d = decks.build(JOINED + [listed(5, "t02", (3, "LAV-01")), settled(6, "t02", "t01", 3, "LAV-01"),
                                  settled(7, "abuela", "t02", 900, "LAV-09")], CAT)
        self.assertEqual(d["t02"]["known"], {"LAV-09": 1})
        self.assertEqual(d["t02"]["total"], N)          # one out, one in
        self.assertEqual(d["t01"]["known"], {"LAV-01": 1})
        self.assertEqual(d["t01"]["total"], N + 1)

    def test_a_pack_with_its_best_card_shown_places_the_whole_block(self):
        d = decks.build(JOINED + [ev(9, "pack.opened", team="t01", pack="sobre_plata",
                                     best={"id": 829, "ref": "LAV-09"})], CAT)
        self.assertEqual(d["t01"]["ids"][-5:], [825, 826, 827, 828, 829])
        self.assertEqual((d["t01"]["known"], d["t01"]["unplaced"], d["t01"]["total"]), ({"LAV-09": 1}, 0, N + 5))

    def test_a_pack_without_its_best_is_counted_once_even_after_its_cards_show_up(self):
        d = decks.build(JOINED + [ev(9, "pack.opened", team="t01", pack="sobre_barrio"),
                                  listed(12, "t01", (500, "LAV-01")), settled(14, "t01", "t02", 501, "LAV-01")], CAT)
        self.assertEqual((d["t01"]["unplaced"], d["t01"]["total"]), (1, N + 2))   # 3 pulled, 1 sold, 1 still unseen
        self.assertEqual(d["t02"]["total"], N + 1)

    def test_a_gift_and_a_workshop_card_are_the_same_copy_when_their_id_shows_up(self):
        d = decks.build(JOINED + [ev(3, "gift.given", team="t02", cards=["LAV-01"]),
                                  ev(4, "taller.crafted", team="t02", card="La Tabacalera"),
                                  listed(6, "t02", (777, "LAV-06"))], CAT)
        self.assertEqual(d["t02"]["floating"], {"LAV-01": 1})
        self.assertEqual(d["t02"]["known"], {"LAV-06": 1})
        self.assertEqual((d["t02"]["burned"], d["t02"]["total"]), (3, N + 1 + 1 - 3))

    def test_upto_stops_at_a_tick(self):
        d = decks.build(JOINED + [settled(50, "abuela", "t02", 900, "LAV-09")], CAT, upto=49)
        self.assertEqual(d["t02"]["total"], N)

    def test_check_against_a_real_deck(self):
        d = decks.build(JOINED + [listed(5, "t02", (3, "LAV-01"))], CAT)["t02"]
        real = [{"id": i, "kind": "card", "ref": "LAV-01" if i == 3 else "LAV-06"} for i in range(2, N + 1)] + \
               [{"id": 99, "kind": "card", "ref": "LAV-09"}]
        c = decks.check(d, real)
        self.assertEqual((c["real"], c["rebuilt"], c["ids_right"], c["ids_missed"], c["ids_wrong"]), (N, N, N - 1, 1, 1))
        self.assertEqual((c["named"], c["names_right"], c["missed"]), (1, 1, [99]))


class BrainDeckCheck(unittest.TestCase):
    def test_the_brain_checks_the_rebuild_on_our_relayed_account_at_its_tick(self):
        import brain
        events = JOINED + [settled(50, "abuela", "t02", 900, "LAV-09")]
        real = [{"id": i, "kind": "card", "ref": "LAV-01"} for i in range(1, N + 1)]
        orig = brain.vi.US
        brain.vi.US = "t02"
        try:
            c = brain.deck_vs_real(events, CAT, {"me": {"tick": 49, "assets": real}})
        finally:
            brain.vi.US = orig
        self.assertEqual((c["tick"], c["real"], c["rebuilt"], c["ids_wrong"]), (49, N, N, 0))


if __name__ == "__main__":
    unittest.main()
