"""Range shover: moves all in preflop with roughly the top 25% of hands, else check/fold.
Postflop it shoves made pairs or better. Mimics the push/fold bots on the ladder."""
import random
from macpoker import Bot
from _common import chen


class Shover(Bot):
    name = "shover"

    def __init__(self):
        self.rng = random.Random(7)

    def act(self, s):
        if not s.board:
            if chen(s.hole) >= 7 and s.can_raise:
                return s.all_in()
            if s.to_call == 0:
                return s.check()
            return s.call() if chen(s.hole) >= 9 else s.fold()
        ranks = [c[0] for c in s.hole]
        board = [c[0] for c in s.board]
        if any(r in board for r in ranks) or ranks[0] == ranks[1]:
            return s.all_in() if s.can_raise else s.call()
        return s.check() if s.to_call == 0 else s.fold()
