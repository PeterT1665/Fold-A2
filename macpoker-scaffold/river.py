"""River (5 board cards) decisions. Owner: see CONTRACT.md.

Replace the body of decide() with your own logic. Until then it uses the
shared default policy in strategy.py.
"""

from strategy import default_postflop


def decide(state, ctx):
    return default_postflop(state, ctx)
