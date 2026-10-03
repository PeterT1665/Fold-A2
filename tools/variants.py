"""Named parameter variants for A/B runs: arena spec `me:NAME`.
Keys are "module.ATTR" in macpoker-scaffold (flop, range_model)."""
VARIANTS = {
    "base": {},
    "nobigbet": {"flop.BET_SIZES": (0.25, 0.33, 0.5, 0.66, 0.85, 1.0)},
    "fewbluffs": {"flop.BLUFF_BET_P": (0.3, 0.2, 0.15), "flop.BLUFF_RAISE_P": 0.15},
    "foldlow": {"range_model.FOLD_SCALE": 0.7},
    "smallraise": {"flop.RAISE_SIZES": (0.66, 1.0)},
    "combo": {"flop.BET_SIZES": (0.25, 0.33, 0.5, 0.66, 0.85, 1.0),
              "flop.BLUFF_BET_P": (0.3, 0.2, 0.15), "range_model.FOLD_SCALE": 0.7},
}
VARIANTS["tol08"] = {"flop.SIZE_TOL": 0.08}
VARIANTS["tol15"] = {"flop.SIZE_TOL": 0.15}
VARIANTS["tol30"] = {"flop.SIZE_TOL": 0.30}

# --- flop aggression (these two knobs exist in v3.1 flop.py); on a ladder-like table every
# variant tied with the baseline within noise (5.47-5.53 pts vs 5.52)
VARIANTS["aggr_p"] = {"flop.BLUFF_BET_P": (0.8, 0.6, 0.45), "flop.BET_MARGIN": 0.0}

# --- preflop what-ifs (experiment only; preflop belongs to Jake)
VARIANTS["wide6"] = {"preflop.decide": "EXP:wide_open_6"}
VARIANTS["wide5"] = {"preflop.decide": "EXP:wide_open_5"}
VARIANTS["wide4"] = {"preflop.decide": "EXP:wide_open_4"}
