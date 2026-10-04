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

**Screen noise is about ±400 chips per 10 seeds on the tight table.** Two
builds with identical logic scored 4/10, -437 against each other (the turn's
time-limited enumeration varies under CPU load). Treat anything inside
±400 or 4-6/10 as "no difference".

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
| Open to 3bb instead of 2.5bb (pro-player feedback) | 40 seeds: tight 16/40 (-164), 5-seat 16/40 (-289). Ladder data "3bb opens earn +0.8" compares different bots, not the same bot |
| Wider BB defence vs opens <= 3bb (ladder wide defenders earn +3-4/spot) | 40 seeds: tight 17/40 (-127), 5-seat 17/40 (-259). Those bots win postflop with aggression we don't have |
| Both of the above | tight 16/40 (-161), 5-seat 18/40 (-285) |
| Bigger river value bets (fold model capped at pot size + 2x-pot river size) | 40 seeds: tight 19/40 (-135), 5-seat 16/40 (-208), stations 14/40 (-1030) |
| Bluff the river more (review suggestion) | Ladder data: real river bluffs (bettor behind) lose at every size, -5 to -40 chips per bluff; callers fold only 26-40% when ahead. Our own bluffs are rare (14 in 42 games) and about break-even |
| Commit guard only at 7+ seats (for 5-seat tournament tables) | 5 seats vs Jake: 4/10 both before and after, within noise. No gain |
| Fold one pair to every big river bet | Tight table 3/10 (-187); ladder replay +11. Jake's margin already covers it |
| Smaller bet sizes everywhere (copying the MAC bot's 1/3-pot bets) | Tight table 4/10 (+30), more variance |
| Flop played by the turn's exact-equity engine | 5/10 (-95), and earlier 3/10 |
| Randomized flop bet sizing (`SIZE_TOL` 0.15) | 3/10 (-906). Code kept, set to 0 |
| Endgame "protect a lead" rule | Never changed a finishing place, cost chips |
| Peter's calibrated range tables (`calibrated-ranges`) | Worse than Jake's preflop alone in 6/10 and every arena lineup |
| Chi's Monte Carlo preflop all-in calls | Lost to Jake's preflop 9/10 |
| Copying specific bots (MAC bot, jongwon) | MAC's high Elo is variance (swings ~570/game, lost 1182 in one game). Tuning to the current field adds swings when the field changes |
| Flop rewritten on exact equity vs range-weighted combos (sampled runouts), branch `flop-v2-combos` | Same-table vs v3.3 flop: 5 seats 3.84 vs 3.73 pts, 8 seats 6.52 vs 6.62 pts. A wash, more code and clock. (Differs from "flop on the turn engine" above: this one samples runouts) |
| Flop aggression levers on ladder-shaped opponents: `BLUFF_BET_P` up, `BET_MARGIN` 0, flop-only `FOLD_MULT` 1.3-1.4, bluff gate 0.42 -> 0.3 | 6 variants x 96 games (8 seats, `opponents/ladder_*.py`): 5.47-5.53 pts vs 5.52 baseline. Inert |
| Open wider preflop (any hand with Chen >= 4/5/6 raises first in) to see more flops | Verified it took effect (VPIP 18% -> 26%). 5.36-5.61 pts vs 5.52. No gain on that table |
| Teammate's `turn.py` (time-budget fallback checked per combo + call size as bet/pot-before) | File was based on v3.1, so dropping it in would lose the commit guard, barrel margin and per-opponent logic. Applied just its two changes to current turn: ladder replay on 2 of our games (250 decisions) is identical to `main`. No effect, not shipped |

## Tournament table size (5 seats)

v3.5 at 5 seats (`--table tight5` / `mix5`): even with v3.1 (6/10 -80, 5/10
+472) and with Jake's build (4/10 -402, 4/10 +191), all inside screen noise.
Nothing tuned for the 8-seat ladder measurably hurts at 5 seats.

## Red-team checks (v3.5)

- **Overbet-bluffing us on the river:** 45 ladder games, only 9 big heads-up
  river bets into us; we folded the best hand once (-87). Not being exploited.
- **Odd sizes / crash probing:** `opponents/fuzzer.py` (min-raises, odd
  sizes, random jams) at 2, 5 and 8 seats: all OK, zero fallbacks.
- **Timing tells:** the protocol and replays carry no timestamps.
- **Cross-game profiling:** impossible, every game is a fresh process.
- Theoretical only (field is static): adaptive "teach then punish" against
  Jake's undecayed per-opponent stats, and bet-size tells (big bet = strong).

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

## Ladder scheduling (scrape of the last 50 minutes, Oct 4)

`tools/scrape_ladder.py` returned 51 games, 37 bots, tables of 5-8 seats (mostly 6).
Games per bot: median 2, busiest idc 25, regrets 24, poke-bowl 24, jongwon 24. We played 1
(31st of 37), and tungbot (#1 on the standings) also played 1. So how often a bot is scheduled
is very uneven and is not simply "recently uploaded". Elo only moves when a bot plays, so a bot
that plays rarely slides in rank while busy bots keep climbing. We don't know the scheduling rule;
the standings page's "How the weekend works" dropdown may say. Our peak Elo was 1271 (second highest).

`python tools/ladder_profiles.py` aggregates every scraped game into one row per bot. In this scrape
the best average finishing places (0.42-0.44) came from bots with VPIP 30-43, PFR 18-31, seeing the
flop in 17-29% of hands, and folding 54-67% of the time facing a postflop bet. Bots with a
tight profile like ours (idc: VPIP 15, flop 8%) finished mid-table (0.49). One of the top-5, regrets,
bets or raises only 4 times per 100 hands, so aggression alone does not explain it. Gaps between
bots with 20+ games are small (place 0.42-0.49), so treat all of this as noise-level.
