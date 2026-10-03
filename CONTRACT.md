# Bot contract (keep it simple)

## Who owns what
| File | Street | Owner |
|---|---|---|
| `macpoker-scaffold/preflop.py` | 0 board cards | person 1 |
| `macpoker-scaffold/flop.py` | 3 board cards | person 2 (Peter) |
| `macpoker-scaffold/turn.py` | 4 board cards | person 3 |
| `macpoker-scaffold/river.py` | 5 board cards | person 4 |
| `main.py`, `opponent_tracker.py`, `postflop_evaluator.py`, `strategy.py` | shared | change only after telling the others |

`flop.py`, `turn.py` and `river.py` currently delegate to the shared default policy in `strategy.py`
(`default_postflop`). Replace the body of `decide` when your logic is ready.

## Interface
Every street module exposes one function:

    def decide(state, ctx) -> Action

- `state` is the `macpoker` GameState. `ctx` has `tracker` (`tracker.classify(player_id)`), `rng`, `blinds`, `evaluator` (hand bucket + board texture) and `strategy` (shared default).
- `main.py` picks the module by `len(state.board)`: 0 → preflop, 3 → flop, 4 → turn, 5 → river.
- The flop learns who raised preflop only from `state.history`. Preflop does not pass anything extra.

## Rules for every module
- Never raise an exception out of `decide`; `main.py` keeps the check/fold safety net.
- Under 5 ms per call. No network, no files, no threads.
- Only the standard library, numpy and macpoker. Python 3.12 compatible.
- Raises use raise-to amounts. Use `state.all_in()` rather than a made-up large number.

## Before pushing
1. `python tools/arena.py me,tag,lag,equity_bot,nit --deals 150 --seeds 8`
2. Merge only if average points did not drop.
3. Work on your own branch; open a PR into `main`.
