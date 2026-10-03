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
