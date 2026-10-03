"""Compact preflop policy (Chen-score based). Post-flop is the focus of this
bot; this just keeps preflop sane and cheap."""

from __future__ import annotations

from opponent_tracker import OpponentClass
from postflop_evaluator import RANKS

_PTS = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}


def chen(hole) -> float:
    r1, r2 = RANKS.index(hole[0][0]), RANKS.index(hole[1][0])
    suited = hole[0][1] == hole[1][1]
    hi, lo = max(r1, r2), min(r1, r2)
    pts = lambda r: _PTS.get(r, (r + 2) / 2)
    if hi == lo:
        return float(max(5.0, 2 * pts(hi)))
    score = pts(hi)
    if suited:
        score += 2
    gap = hi - lo - 1
    score -= (0, 1, 2, 4)[gap] if gap < 4 else 5
    if gap <= 1 and hi < 10:
        score += 1
    return float(-(-score * 2 // 1) / 2)  # round up to half point


def _est_equity(score: float) -> float:
    return min(0.85, 0.28 + 0.022 * score)


def preflop_action(state, rng, bb: int, raiser_class: OpponentClass | None):
    n = state.num_players
    me = state.seat
    score = chen(state.hole)
    rel = (me - state.button) % n
    pf = [h for h in state.history if h[0] == "preflop"]
    raises = sum(1 for h in pf if h[2] == "raise")
    limpers = sum(1 for h in pf if h[2] == "call")
    to_call = state.to_call
    pot = state.pot
    can_raise = state.can_raise

    def raise_to(x):
        x = int(max(state.min_raise_to, min(x, state.max_raise_to)))
        if state.max_raise_to - x < 0.4 * (pot + x):
            return state.all_in()
        return state.raise_to(x)

    def passive():
        return state.call() if to_call > 0 else state.check()

    if raises == 0:
        # table position: BTN / CO late, blinds mid, UTG early
        if n <= 3:
            thr = 4.0
        elif rel == 0:
            thr = 5.5
        elif rel == n - 1:
            thr = 7.0
        elif rel == 1:
            thr = 6.5
        elif rel == 2:
            thr = 8.0  # BB raising over limps
        else:
            thr = 9.0
        if score >= thr and can_raise:
            return raise_to((3 + limpers) * bb)
        if to_call == 0:
            return state.check()
        if rel == 1 and score >= 4.5 and to_call <= bb:
            return state.call()
        return state.fold()

    # facing a raise
    need = to_call / (pot + to_call)
    eq = _est_equity(score)
    if raiser_class is OpponentClass.OVER_AGGRESSIVE:
        eq += 0.10  # their range is wide
    elif raiser_class is OpponentClass.TIGHT_FOLD:
        eq -= 0.05
    if raises >= 2:
        eq -= 0.04
    cur_bet = state.street_bets[me] + to_call
    if score >= (12 if raises >= 2 else 11.5) and can_raise:
        return state.all_in() if raises >= 2 else raise_to(cur_bet * 3.2)
    if to_call >= state.my_stack:  # call-off decision
        return state.call() if eq >= need + 0.03 else state.fold()
    if eq >= need + 0.02 and score >= 8.0 and to_call <= 0.25 * (state.my_stack + state.street_bets[me]):
        return state.call()
    return state.fold()
