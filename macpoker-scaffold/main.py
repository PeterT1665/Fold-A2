"""Tournament bot: adaptive post-flop exploitation engine.

Modules (all in this folder):
  opponent_tracker  in-memory per-player stats + CALLING_STATION / TIGHT_FOLD /
                    OVER_AGGRESSIVE / BALANCED_GTO classification
  postflop_evaluator  bitmask hand bucketing + board texture
  strategy          action abstraction (CHECK_FOLD / BET_33 / BET_66 / BET_100 /
                    ALL_IN) and the exploitative decision tree
  preflop / flop / turn / river   one module per street, each exposing
                    decide(state, ctx) (see CONTRACT.md)
"""

import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from macpoker import Bot  # noqa: E402

from opponent_tracker import OpponentTracker  # noqa: E402
from preflop_memory import PreflopMemory  # noqa: E402
from postflop_evaluator import PostFlopEvaluator  # noqa: E402
import flop, preflop, river, turn  # noqa: E402
from strategy import PostflopStrategy  # noqa: E402


class Ctx:
    """Shared context handed to every street's decide(state, ctx)."""

    def __init__(self, tracker, rng, blinds, evaluator, strategy, memory):
        self.tracker, self.rng, self.blinds = tracker, rng, blinds
        self.evaluator, self.strategy = evaluator, strategy
        self.memory = memory  # preflop stats by player id (preflop_memory.py)


class MyBot(Bot):
    name = "adaptive-exploiter"

    def __init__(self):
        self.rng = random.Random(1665)
        self.blinds = (1, 2)
        self.n = 5
        self.me = 0
        self.tracker = OpponentTracker(self.blinds)
        self.evaluator = PostFlopEvaluator()
        self.strategy = PostflopStrategy(self.tracker, self.rng)
        self.preflop_memory = PreflopMemory()
        self._button = 0
        self._start_stacks: list[int] = []
        self._events: list[dict] = []
        self._players: list[int] | None = None
        self._seen_players = False

    # ------------------------------------------------------------ observers
    def on_match_start(self, info):
        try:
            self.n = info.get("num_players", self.n)
            self.me = info.get("player", self.me)
            self.blinds = tuple(info.get("blinds", self.blinds))
            self.tracker.blinds = self.blinds
            self.preflop_memory.set_me(self.me)
        except Exception:
            pass

    def on_hand_start(self, info):
        try:
            self._events = []
            self._seen_players = False
            self._button = info.get("button", 0)
            self._start_stacks = list(info.get("stacks") or [])
            seat = info["seat"]
            # seats rotate one step per hand; ids are stable (see GameState.players)
            self._players = [(self.me - seat + s) % self.n for s in range(self.n)]
        except Exception:
            self._players = None

    def on_action(self, event):
        self._events.append(event)

    def on_hand_end(self, info):
        try:
            if self._players:
                showdown = [int(s) for s in (info.get("revealed") or {})]
                self.tracker.observe_hand(self._events, self._players, showdown)
        except Exception as e:
            print(f"tracker error: {e!r}")
        try:
            if self._players:
                self.preflop_memory.observe_hand(
                    self._events, self._players, self._button, self._start_stacks
                )
        except Exception as e:
            print(f"preflop memory error: {e!r}")
        self._events = []

    # ------------------------------------------------------------ decisions
    def act(self, state):
        try:
            return self._act(state)
        except Exception:
            return self._safe(state)

    @staticmethod
    def _safe(state):
        try:
            return state.check() if state.to_call == 0 else state.fold()
        except Exception:
            return state.check()  # the engine turns an illegal check into a fold

    def _act(self, state):
        self._players = list(state.players)  # authoritative mapping for this hand
        clock = state.clock_ms
        if 0 < clock < 150:  # nearly flagged: play instantly
            if state.to_call == 0:
                return state.check()
            if state.to_call <= 0.2 * state.pot:
                return state.call()
            return state.fold()

        ctx = Ctx(self.tracker, self.rng, self.blinds, self.evaluator, self.strategy,
                  self.preflop_memory)
        street = {0: preflop, 3: flop, 4: turn, 5: river}[len(state.board)]
        return street.decide(state, ctx)


bot = MyBot()
