"""Tight-aggressive: premium-ish preflop ranges, equity-driven postflop, value/semi-bluff, folds to big pressure."""
import random
from macpoker import Bot
from _common import equity, chen, size_raise


class Tag(Bot):
    name = "tag"

    def __init__(self):
        self.rng = random.Random(11)

    def act(self, s):
        rng = self.rng
        if not s.board:
            sc = chen(s.hole)
            raises = sum(1 for h in s.history if h[2] == "raise")
            if raises == 0:
                if sc >= 8 and s.can_raise:
                    return s.raise_to(max(s.min_raise_to, min(6, s.max_raise_to)))
                return s.check() if s.to_call == 0 else s.fold()
            if sc >= 12 and s.can_raise:
                return size_raise(s, 1.0)
            if sc >= 9.5 and s.to_call <= 0.15 * 200:
                return s.call()
            return s.check() if s.to_call == 0 else s.fold()
        n_opp = max(1, sum(1 for f in s.folded if not f) - 1)
        eq = equity(s.hole, s.board, n_opp, rng) ** 1.0
        odds = s.to_call / (s.pot + s.to_call) if s.to_call else 0
        if s.to_call == 0:
            if eq > 0.72 and s.can_raise:
                return size_raise(s, 0.7)
            if eq > 0.5 and s.can_raise and rng.random() < 0.5:
                return size_raise(s, 0.5)
            if eq < 0.35 and s.can_raise and rng.random() < 0.15:
                return size_raise(s, 0.5)
            return s.check()
        if eq > 0.82 and s.can_raise:
            return size_raise(s, 1.0)
        return s.call() if eq > odds + 0.08 else s.fold()
