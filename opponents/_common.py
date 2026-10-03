"""Shared helpers for test opponents (never shipped in the submission)."""
import random
from macpoker.cards import parse_card
from macpoker.evaluator import evaluate

RANKS = "23456789TJQKA"


def equity(hole, board, n_opps, rng, samples=120):
    """Monte-Carlo equity vs n_opps random hands (ties count half)."""
    h = [parse_card(c) for c in hole]
    b = [parse_card(c) for c in board]
    used = set(h + b)
    deck = [c for c in range(52) if c not in used]
    need = 5 - len(b)
    score = 0.0
    for _ in range(samples):
        draw = rng.sample(deck, need + 2 * n_opps)
        full = b + draw[:need]
        mine = evaluate(h + full)
        best_opp = max(evaluate(draw[need + 2 * i: need + 2 * i + 2] + full) for i in range(n_opps))
        score += 1.0 if mine > best_opp else (0.5 if mine == best_opp else 0.0)
    return score / samples


def chen(hole):
    P = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}
    r1, r2 = RANKS.index(hole[0][0]), RANKS.index(hole[1][0])
    hi, lo = max(r1, r2), min(r1, r2)
    pts = lambda r: P.get(r, (r + 2) / 2)
    if hi == lo:
        return max(5.0, 2 * pts(hi))
    s = pts(hi) + (2 if hole[0][1] == hole[1][1] else 0)
    gap = hi - lo - 1
    s -= (0, 1, 2, 4)[gap] if gap < 4 else 5
    if gap <= 1 and hi < 10:
        s += 1
    return s


def size_raise(state, frac):
    """raise-to for `frac` of pot on top of calling."""
    t = state.street_bets[state.seat] + state.to_call + frac * (state.pot + state.to_call)
    t = int(max(state.min_raise_to, min(t, state.max_raise_to)))
    return state.all_in() if state.max_raise_to - t < 0.4 * state.pot else state.raise_to(t)
