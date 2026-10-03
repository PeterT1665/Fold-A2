"""Sticky station that occasionally min-raises: calls almost everything, bets only strong hands, rare big bluff."""
import random
from macpoker import Bot
from _common import equity, chen, size_raise


class StickyStation(Bot):
    name = "sticky"

    def __init__(self):
        self.rng = random.Random(55)

    def act(self, s):
        if not s.board:
            if chen(s.hole) >= 9 and s.can_raise and not s.to_call > 10:
                return s.raise_to(max(s.min_raise_to, min(6, s.max_raise_to)))
            return s.call() if s.to_call and s.to_call < 30 else (s.check() if not s.to_call else s.fold())
        eq = equity(s.hole, s.board, max(1, sum(1 for f in s.folded if not f) - 1), self.rng, 60)
        if s.to_call == 0:
            if eq > 0.7 and s.can_raise:
                return size_raise(s, 0.5)
            return s.check()
        return s.call() if eq > 0.28 else s.fold()
