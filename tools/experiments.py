"""Throwaway what-if patches for arena variants (value "EXP:<name>" in tools/variants.py)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "opponents"))


def build(name):
    import preflop
    from _common import chen
    if name.startswith("wide_open_"):
        thr = float(name.split("_")[-1])
        orig = preflop.decide

        def decide(state, ctx):
            raises = sum(1 for h in state.history if h[0] == "preflop" and h[2] == "raise")
            if raises == 0 and state.can_raise and chen(state.hole) >= thr:
                return state.raise_to(max(state.min_raise_to, min(6, state.max_raise_to)))
            return orig(state, ctx)
        return decide
    raise KeyError(name)
