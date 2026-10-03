"""Pot-odds / equity bot: plays every street purely off Monte-Carlo equity, no profiling, mixes sizes."""
import random
from macpoker import Bot
from _common import equity, chen, size_raise


class EquityBot(Bot):
    name = "equity"

    def __init__(self):
        self.rng = random.Random(33)

    def act(self, s):
        rng = self.rng
        n_opp = max(1, sum(1 for f in s.folded if not f) - 1)
        eq = equity(s.hole, s.board, n_opp, rng, 150)
        odds = s.to_call / (s.pot + s.to_call) if s.to_call else 0
        thr = 0.50 if not s.board else 0.55
        if s.to_call == 0:
            if eq > thr + 0.05 * n_opp and s.can_raise:
                return size_raise(s, 0.66 if eq < 0.8 else 1.0)
            return s.check()
        if eq > 0.78 and s.can_raise:
            return size_raise(s, 0.8)
        return s.call() if eq > odds + 0.05 + (0.04 if not s.board else 0) else s.fold()
