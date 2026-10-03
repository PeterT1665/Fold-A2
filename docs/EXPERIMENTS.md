# What worked and what didn't

A log of every bot change we tested, so nobody re-runs a dead end. Newest
first within each section. "Screen" means the same-table test in
`tools/screen.py` (two bots at one 8-seat table, 10 pinned seeds, per-seed
difference). "Ladder replay" means `tools/ladder_replay.py` on downloaded
ladder games (see [LADDER_DATA.md](LADDER_DATA.md)).

## How we decide what ships

1. **Screen against current `main`** on both tables:
   `python tools/screen.py <main copy> <your copy>`. Ship only if it wins
   about **7/10 seeds with a positive mean on the tight table** and doesn't
   lose clearly on the stations table.
2. **Ladder replay** on real games: no crashes, and the "net chips from folds
   that differ" number should not go down versus `main`.
3. **Crash check**: `--subprocess` against house bots at 2, 5 and 8 seats,
   all verdicts `OK`.
4. If it doesn't beat `main`, it doesn't ship. Same rule for everyone.

Our local test bots are softer than the ladder. Anything that only wins on the
stations table (`house:call`, maniac) usually doesn't help on the ladder.

## Version history (ladder)

| Version | What changed | Ladder result |
|---|---|---|
| v3.5 (`cb85d27`) | Robust stack-off rules; strong hands call big bets | First scrims +547 (1st), +397, +123 |
| Jake's `bot.zip` (`jake-review`) | Per-opponent bet trust and fold rates; stricter big calls | +1226 over 6 scrims, peaked #2; then 4 heavy losses (-866 luck-adjusted) when new aggressive bots joined |
| v3.1 (`7e52b37`) | River/turn board-combinatorics fix | Reached #4 |
| v3 (`aa79a56`) | Exact-equity turn | Mixed; a bad stretch of turn overbet jams |
| v2 (`48cc300`) | Jake's range-table preflop + exact river | About break-even luck-adjusted |
| first upload | **The starter template by mistake** | Lost; it ignores its cards. Always zip `macpoker-scaffold/`, never the repo root |

## Kept

| Change | Evidence | Where |
|---|---|---|
| **Commit guard**: a bet or raise putting in >50% of our stack needs trips+ that improves on the board, or two pair on an unpaired board. Off against calling stations | Fixed turn jams with draws/one pair (A-K flush draw, A-J gutshot jamming into boats). 28 ladder games: net +473 vs +315. Tight table 6/10 (+227) | `river.can_commit`, used in turn/river |
| **Strong hands ignore the big-call margin**: two pair+ improving on the board calls big bets | 47 scraped games: calling big river bets with two pair+ won **+33/call** (102 calls); one pair or less lost **-43/call** (64 calls) | `river.py`, `turn.py` |
| Per-opponent bet trust + fold rates, +8% equity to call bets > half pot (Jake) | Ladder replay +315 vs -41; screen 6/10 and 7/10 | `range_model.py` |
| Flop prior from the board's real bucket counts | Screen 9/10, +1209 | `flop._bucket_counts` |
| Barrel margin: +3% equity to call per street the opponent bet | Screen 7/10, +650; ladder replay +61 | `river.barrels` |
| River/turn combos weighted by board combinatorics, not fixed bucket shares | Fixed a pair-of-nines jam into a four-flush board (-200). Screen 6/10, +1260 | `river._weights` |
| Exact-equity turn (all 46 river cards) | Screens 6/10 and 7/10; 8-seat ranked 5.58 -> 5.77 | `turn.py` |
| Exact-equity river vs range-weighted combos | Screens 7/10 | `river.py` |
| Jake's range-table preflop | Beat the Chen preflop 9/10 | `preflop.py`, `ranges.py` |
| Logging when `act()` falls back | Verified decision-neutral (identical chips on 4 seeds) | `main.py` |

## Rejected (don't retry without new evidence)

| Idea | Result |
|---|---|
| Fold one pair to every big river bet | Tight table 3/10 (-187); ladder replay +11. Jake's margin already covers it |
| Smaller bet sizes everywhere (copying the MAC bot's 1/3-pot bets) | Tight table 4/10 (+30), more variance |
| Flop played by the turn's exact-equity engine | 5/10 (-95), and earlier 3/10 |
| Randomized flop bet sizing (`SIZE_TOL` 0.15) | 3/10 (-906). Code kept, set to 0 |
| Endgame "protect a lead" rule | Never changed a finishing place, cost chips |
| Peter's calibrated range tables (`calibrated-ranges`) | Worse than Jake's preflop alone in 6/10 and every arena lineup |
| Chi's Monte Carlo preflop all-in calls | Lost to Jake's preflop 9/10 |
| Copying specific bots (MAC bot, jongwon) | MAC's high Elo is variance (swings ~570/game, lost 1182 in one game). Tuning to the current field adds swings when the field changes |

## Open leads

- **v3.4 jam cap** (`v3.4-jamcap`): no jam bigger than 1.5x pot unless a
  station is in; fold model capped at pot size. Mostly covered by the commit
  guard now. Re-screen against `main` before reusing.
- **Postflop aggression**: winners bet or raise 3-8x per call postflop, we're
  around 2-3x. Untested beyond the rejected small-sizing idea.

## Gotchas

- **The upload test is 2 hands against `house:call`.** It only checks the bot
  runs. A small loss there means nothing.
- **Ladder Elo ranks finishing order, not chips.** +44 while two bots make
  +300 counts as losing to both. The tournament scores by rank too.
- **One game is noise.** A single all-in swings 200 chips. Judge versions over
  8+ scrims, luck-adjusted (see LADDER_DATA.md).
- Seed everything: Python's `hash()` changes between processes, so use
  string seeds for any randomness that must be reproducible.
