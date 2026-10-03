"""Hostile input fuzzer: min-bets, min-raises, odd sizes, random jams, limps.
Used to check our bot never crashes or falls back on unusual sizings."""
import random
from macpoker import Bot


class Fuzzer(Bot):
    name = "fuzzer"

    def __init__(self):
        self.rng = random.Random(99)

    def act(self, s):
        r = self.rng.random()
        if s.can_raise and r < 0.35:
            lo, hi = s.min_raise_to, s.max_raise_to
            pick = self.rng.choice([lo, lo + 1, (lo + hi) // 2, hi - 1, hi, lo + self.rng.randint(0, 7)])
            return s.raise_to(max(lo, min(hi, pick)))
        if r < 0.75:
            return s.call() if s.to_call > 0 else s.check()
        return s.check() if s.to_call == 0 else s.fold()
