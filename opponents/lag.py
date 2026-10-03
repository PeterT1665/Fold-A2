"""Loose-aggressive: wide opens, frequent bluffs and barrels, 3-bets light."""
import random
from macpoker import Bot
from _common import equity, chen, size_raise


class Lag(Bot):
    name = "lag"

    def __init__(self):
        self.rng = random.Random(22)

    def act(self, s):
        rng = self.rng
        if not s.board:
            sc = chen(s.hole)
            raises = sum(1 for h in s.history if h[2] == "raise")
            if raises == 0:
                if (sc >= 5 or rng.random() < 0.15) and s.can_raise:
                    return s.raise_to(max(s.min_raise_to, min(7, s.max_raise_to)))
                return s.check() if s.to_call == 0 else s.fold()
            if (sc >= 10 or rng.random() < 0.12) and s.can_raise:
                return size_raise(s, 0.9)
            if sc >= 7 and s.to_call < 40:
                return s.call()
            return s.check() if s.to_call == 0 else s.fold()
        n_opp = max(1, sum(1 for f in s.folded if not f) - 1)
        eq = equity(s.hole, s.board, n_opp, rng, 80)
        odds = s.to_call / (s.pot + s.to_call) if s.to_call else 0
        if s.to_call == 0:
            if s.can_raise and (eq > 0.55 or rng.random() < 0.45):
                return size_raise(s, rng.choice([0.5, 0.75, 1.0]))
            return s.check()
        if s.can_raise and (eq > 0.75 or rng.random() < 0.18):
            return size_raise(s, 1.0)
        return s.call() if eq > odds * 0.8 else s.fold()
