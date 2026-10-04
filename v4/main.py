"""Fold-A2 v4 tournament entry. Logic lives in foldv4.py; this file only wires the SDK hooks
and guarantees a legal action even if the brain raises."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from macpoker import Bot, GameState
from macpoker.actions import Action

from foldv4 import Brain


class FoldA2(Bot):
    name = "fold-a2-v4"

    def __init__(self):
        self.brain = Brain()

    def on_match_start(self, info):
        try:
            self.brain.on_hello(info)
        except Exception:
            pass

    def on_hand_start(self, info):
        try:
            self.brain.on_hand_start(info)
        except Exception:
            pass

    def on_action(self, event):
        try:
            self.brain.on_action(event)
        except Exception:
            pass

    def on_hand_end(self, info):
        try:
            self.brain.on_hand_end(info)
        except Exception:
            pass

    def act(self, state: GameState) -> Action:
        try:
            a = self.brain.act(state)
            if isinstance(a, Action):
                return a
        except Exception as e:
            print(f"fold-a2 fallback: {type(e).__name__}: {e}", file=sys.stderr)
        return state.check() if state.to_call == 0 else state.fold()
