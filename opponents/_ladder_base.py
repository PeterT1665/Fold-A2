"""Opponents shaped from real ladder stats (see tools/analyze_game.py output on games/*.json).
Hand strength comes from the scaffold's cheap evaluator; behaviour is a few frequencies."""
import os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "macpoker-scaffold"))
from macpoker import Bot
from postflop_evaluator import HandClass as HC, PostFlopEvaluator
from _common import chen, size_raise

_EV = PostFlopEvaluator()
STRONG = (HC.NUT_HAND, HC.STRONG_MADE)
MID = (HC.MEDIUM_MADE, HC.STRONG_DRAW)


class LadderBot(Bot):
    seed = 1
    open_t, call_t, three_t = 6.0, 5.0, 11.0   # preflop Chen thresholds
    p_bet = (0.8, 0.4, 0.15)                   # bet freq when checked to: strong / mid / weak
    bet_size = 0.9
    f_mid, f_weak = 0.5, 0.9                   # fold prob facing a bet (at half pot)
    p_raise = 0.1                              # raise prob facing a bet with a strong hand

    def __init__(self):
        self.rng = random.Random(self.seed)

    def act(self, s):
        rng = self.rng
        if not s.board:
            sc = chen(s.hole)
            raises = sum(1 for h in s.history if h[0] == "preflop" and h[2] == "raise")
            if raises == 0:
                if sc >= self.open_t and s.can_raise:
                    return s.raise_to(max(s.min_raise_to, min(6, s.max_raise_to)))
                if s.to_call == 0:
                    return s.check()
                return s.call() if sc >= self.call_t and s.to_call <= 2 else s.fold()
            if sc >= self.three_t and s.can_raise:
                return size_raise(s, 0.9)
            return s.call() if (sc >= self.call_t + 1.5 and s.to_call <= 20) else s.fold()
        hc = _EV.evaluate(s.hole, s.board).hc
        cls = 0 if hc in STRONG else 1 if hc in MID else 2
        if s.to_call == 0:
            if s.can_raise and rng.random() < self.p_bet[cls]:
                return size_raise(s, max(0.25, rng.gauss(self.bet_size, 0.25)))
            return s.check()
        frac = s.to_call / max(s.pot - s.to_call, 1)
        pf = (0.05, self.f_mid, self.f_weak)[cls]
        pf = min(0.98, max(0.0, pf + 0.2 * (frac - 0.5)))
        if cls == 0 and s.can_raise and rng.random() < self.p_raise:
            return size_raise(s, 1.0)
        return s.fold() if rng.random() < pf else s.call()
