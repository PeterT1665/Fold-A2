"""Nit: very tight, plays strong made hands only, folds to any real pressure."""
import random
from macpoker import Bot
from _common import equity, chen, size_raise


class Nit(Bot):
    name = "nit"

    def __init__(self):
        self.rng = random.Random(44)

    def act(self, s):
        if not s.board:
            sc = chen(s.hole)
            if sc >= 10 and s.can_raise and s.to_call <= 6:
                return s.raise_to(max(s.min_raise_to, min(6, s.max_raise_to)))
            if sc >= 12:
                return s.call() if s.to_call else s.check()
            return s.check() if s.to_call == 0 else s.fold()
        n_opp = max(1, sum(1 for f in s.folded if not f) - 1)
        eq = equity(s.hole, s.board, n_opp, self.rng, 80)
        if s.to_call == 0:
            if eq > 0.75 and s.can_raise:
                return size_raise(s, 0.6)
            return s.check()
        if eq > 0.8:
            return s.call()
        return s.fold()
