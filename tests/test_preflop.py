"""Preflop scenario tests. Run from the repo root: python -m tests.test_preflop"""

import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "macpoker-scaffold"))

from macpoker.sdk import GameState  # noqa: E402

import ranges as R  # noqa: E402
from preflop import position, preflop_action  # noqa: E402
from preflop_memory import PreflopMemory  # noqa: E402

N, BTN, BB = 5, 0, 2  # seats: 0 BTN, 1 SB, 2 BB, 3 HJ (first to act), 4 CO
RNG = random.Random(0)


def make_state(seat, hole, history=(), stacks=None, street_bets=None, folded=None):
    """Build a preflop decision for `seat`. history: [(seat, kind, raise_to)]."""
    bets = [0, 1, 2, 0, 0]
    stk = [200, 199, 198, 200, 200]
    fold = [False] * N
    hist = []
    for s, kind, amt in history:
        if kind == "fold":
            fold[s] = True
            hist.append(["preflop", s, "fold", 0])
        elif kind == "call":
            c = max(bets) - bets[s]
            stk[s] -= c
            bets[s] += c
            hist.append(["preflop", s, "call", c])
        elif kind == "raise":
            stk[s] -= amt - bets[s]
            bets[s] = amt
            hist.append(["preflop", s, "raise", amt])
    cur = max(bets)
    msg = {
        "type": "act", "hand": 0, "seat": seat, "players": list(range(N)),
        "street": "preflop", "board": [], "hole": hole, "pot": sum(bets) + 0,
        "to_call": min(cur - bets[seat], stk[seat]),
        "min_raise_to": min(cur + max(BB, cur - sorted(bets)[-2]), stk[seat] + bets[seat]),
        "max_raise_to": stk[seat] + bets[seat], "can_raise": True,
        "stacks": stacks or stk, "street_bets": street_bets or bets,
        "folded": folded or fold, "button": BTN, "history": hist, "clock_ms": 30000,
    }
    return GameState(msg)


def act(seat, hole, history=(), mem=None):
    a = preflop_action(make_state(seat, hole, history), RNG, BB, mem)
    return a.kind, a.amount


def test_parser():
    assert len(R.parse("A2s+")) == 12
    assert R.parse("77-22") == {"77", "66", "55", "44", "33", "22"}
    assert R.parse("K9s-K6s") == {"K9s", "K8s", "K7s", "K6s"}
    assert R.parse("TT+") == {"TT", "JJ", "QQ", "KK", "AA"}
    assert R.hand_code(["As", "Kd"]) == "AKo"
    assert R.hand_code(["7h", "Ks"]) == "K7o"
    assert R.hand_code(["9c", "9d"]) == "99"
    assert R.hand_code(["Jh", "Th"]) == "JTs"


def test_range_sizes_and_ladders():
    want = [0.176, 0.214, 0.278, 0.435]
    for got, w in zip(R.OPEN, want):
        assert abs(R.pct(got) - w) < 0.03, (R.pct(got), w)
    for ladder in (R.OPEN, R.THREEBET, R.FOURBET, R.CALL_JAM, R.BB_DEFEND, R.ISO):
        for tight, loose in zip(ladder, ladder[1:]):
            assert R.pct(tight) < R.pct(loose)
    for lvl in R.FOURBET:  # value 4-bets are always strong
        assert {"AA", "KK", "AKs"} <= lvl


def test_positions():
    assert [position(5, s, 0) for s in range(5)] == ["BTN", "SB", "BB", "HJ", "CO"]
    assert [position(6, s, 0) for s in range(6)] == ["BTN", "SB", "BB", "LJ", "HJ", "CO"]
    assert position(2, 0, 0) == "HU" and position(2, 1, 0) == "BB"


def test_unopened():
    assert act(3, ["As", "Ad"]) == ("raise", 5)          # HJ open 2.5bb
    assert act(3, ["7s", "2d"])[0] == "fold"
    assert act(3, ["Ks", "8d"])[0] == "fold"             # K8o is a button open
    fold_to_btn = [(3, "fold", 0), (4, "fold", 0)]
    assert act(0, ["Ks", "8d"], fold_to_btn)[0] == "raise"
    assert act(1, ["Ks", "8d"], fold_to_btn + [(0, "fold", 0)]) == ("raise", 6)  # SB 3bb
    assert act(2, ["7s", "2d"], fold_to_btn + [(0, "fold", 0), (1, "call", 0)])[0] == "check"


def test_facing_open():
    hj_open = [(3, "raise", 5)]
    assert act(4, ["As", "Ad"], hj_open) == ("raise", 15)   # IP 3-bet 3x
    assert act(4, ["7s", "2d"], hj_open)[0] == "fold"
    assert act(4, ["8s", "8d"], hj_open)[0] == "call"
    btn_open = [(3, "fold", 0), (4, "fold", 0), (0, "raise", 5), (1, "fold", 0)]
    assert act(2, ["8s", "7d"], btn_open)[0] == "call"       # BB defends wide vs BTN
    assert act(2, ["Ks", "Kd"], btn_open) == ("raise", 20)  # OOP 3-bet 4x
    assert act(2, ["8s", "2d"], btn_open)[0] == "fold"


def test_facing_3bet_and_jam():
    h = [(3, "raise", 5), (4, "raise", 15), (0, "fold", 0), (1, "fold", 0), (2, "fold", 0)]
    assert act(3, ["Ks", "Kd"], h)[0] == "raise"            # 4-bet value
    assert act(3, ["9s", "8s"], h)[0] == "fold"
    jam = [(3, "raise", 200)]
    assert act(4, ["As", "Ad"], jam)[0] == "call"
    assert act(4, ["As", "2d"], jam)[0] == "fold"


def test_memory_exploits():
    mem = PreflopMemory()
    # the button shoves every hand for 30 hands
    for _ in range(30):
        ev = [{"street": "preflop", "seat": s, "action": "fold", "amount": 0} for s in (3, 4)]
        ev += [{"street": "preflop", "seat": 0, "action": "raise", "amount": 200}]
        ev += [{"street": "preflop", "seat": s, "action": "fold", "amount": 0} for s in (1, 2)]
        mem.observe_hand(ev, list(range(N)), BTN, [200] * N)
    assert mem.rate(0, "jam") > 0.7 and mem.player_type(0) == "maniac"
    assert mem.rate(1, "fold_to_open") > 0.9
    jam = [(3, "fold", 0), (4, "fold", 0), (0, "raise", 200)]
    assert act(1, ["As", "2d"], jam)[0] == "fold"
    assert act(1, ["As", "2d"], jam, mem)[0] == "call"      # wide call-off vs a maniac
    assert act(1, ["7s", "2d"], jam, mem)[0] == "fold"

    # nobody ever defends: steal wider from CO
    mem2 = PreflopMemory()
    for _ in range(40):
        ev = [{"street": "preflop", "seat": 3, "action": "raise", "amount": 5}]
        ev += [{"street": "preflop", "seat": s, "action": "fold", "amount": 0} for s in (4, 0, 1, 2)]
        mem2.observe_hand(ev, list(range(N)), BTN, [200] * N)
    hj_fold = [(3, "fold", 0)]
    assert act(4, ["Ks", "5d"], hj_fold)[0] == "fold"
    assert act(4, ["Ks", "5d"], hj_fold, mem2)[0] == "raise"


def test_confidence_and_station_iso():
    mem = PreflopMemory()
    assert mem.confidence(3, "vpip") == 0.0
    for _ in range(24):  # seat 3 limps every hand, then calls everything
        ev = [{"street": "preflop", "seat": 3, "action": "call", "amount": 2},
              {"street": "preflop", "seat": 4, "action": "raise", "amount": 10},
              {"street": "preflop", "seat": 3, "action": "call", "amount": 8}]
        mem.observe_hand(ev, list(range(N)), BTN, [200] * N)
    assert abs(mem.confidence(3, "vpip") - 0.75) < 1e-9
    assert mem.player_type(3) == "station"
    limp = [(3, "call", 0)]
    assert act(4, ["Qs", "Td"], limp)[0] == "fold"        # not an iso vs an unknown
    assert act(4, ["Qs", "Td"], limp, mem)[0] == "raise"  # value iso vs a station


def test_speed():
    t = time.perf_counter()
    for _ in range(2000):
        act(4, ["Ts", "9d"], [(3, "raise", 5)])
    per = (time.perf_counter() - t) / 2000
    assert per < 0.001, per


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("all preflop tests passed")
