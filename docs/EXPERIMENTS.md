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
that plays rarely slides in rank while busy bots keep climbing. The rule (from the standings page, "How the weekend
works"): **uploads play public scrims every few minutes for 3 hours, then every 10.** Our row said "scrims every
few minutes until 15:58" after a 12:58 upload. A fresh upload also gets a 2x Elo multiplier ("new upload") for its
first scrims. **Only the main submission at the Sun 18:00 lock counts; ladder results and Elo play no part in the
tournament, so submitting late on Sunday is fine.** So: re-uploading (even an identical zip) restarts the burst of
frequent scrims, which is the way to collect more of our own games. Our peak Elo was 1271 (second highest).

`python tools/ladder_profiles.py` aggregates every scraped game into one row per bot. In this scrape
the best average finishing places (0.42-0.44) came from bots with VPIP 30-43, PFR 18-31, seeing the
flop in 17-29% of hands, and folding 54-67% of the time facing a postflop bet. Bots with a
tight profile like ours (idc: VPIP 15, flop 8%) finished mid-table (0.49). One of the top-5, regrets,
bets or raises only 4 times per 100 hands, so aggression alone does not explain it. Gaps between
bots with 20+ games are small (place 0.42-0.49), so treat all of this as noise-level.

## Do our opponent labels match the ladder? (77 scraped games, Oct 4)

We ran `OpponentTracker` over every scraped game and compared its end-of-game label with how each bot
really played. Labels are accurate: TIGHT_FOLD bots fold 68% to postflop bets, BALANCED 43%,
OVER_AGGRESSIVE bots bet 4.8 times per call. Field mix: 40% OVER_AGGRESSIVE, 30% TIGHT_FOLD,
27% BALANCED, **1% CALLING_STATION**, so the calling-station exploits rarely fire on the ladder.
One mismatch: OVER_AGGRESSIVE bots fold 54% to bets, more than BALANCED (43%), while
`range_model.fold_probs` scales their folds down (x0.7). The per-player fold rates added in
`45a7af7` mostly correct that. No change made.

Also from the same data (68 games, 5,946 first-in opens): weak opens lose chips (button, Chen < 6: -1.5 to
-2.9 per open; early position, Chen < 6: -3 to -8), strong opens earn about +10. Our own 25 opens were
all Chen >= 5 and netted +48. Do not widen opens.

## Big-bet calls by hand type, whole field (107 ladder games, 1,331 calls, Oct 4)

Calls of a bet > half pot on turn/river, by every bot. "Fold would gain" = chips saved by folding at that point
instead (positive means the call lost chips versus folding); +/- is one standard error.

| Caller held | Calls | Fold would gain |
|---|---|---|
| trips or better, improving the board | 129 | -65 +/- 15 (calling is right) |
| two pair on an unpaired board | 59 | -37 +/- 22 |
| two pair on a paired board (leans on the board's pair) | 251 | -18 +/- 9 (calling still right) |
| one pair | 567 | +3 +/- 5 (break-even) |
| no pair / board plays | 325 | **+54 +/- 6** (clear mistake) |

So the "strong hands ignore the big-call margin" exemption holds even for two pair on a paired board. Two of our
-200 stack-offs came from that hand type (77 on 4c 8s 8c Qd; QQ on 2d 2h Ah) but the field data says it is not a leak,
just two coolers. Our bot made 0 big calls with no pair. `tools/check_decisions.py` also checks each of our
postflop folds and calls against the opponents' real hole cards: 83 decisions, 6 clearly wrong folds (mostly cheap
flop folds), the rest balanced.

## Looking for our own mistakes (20 of our games, 135 scraped games, Oct 4 afternoon)

Since the 12:58 re-upload of the identical v3.5 build: 16 games, +5,488 chips, average place 3.6 of 8, five 1sts.
Tools: `tools/our_lines.py` (our bets/raises/folds against real cards and against no-hindsight hand strength),
`tools/check_decisions.py` (each postflop fold/call vs the opponents' real hole cards).

- **Hindsight trap:** grouping our bets by equity against the opponents' *real* cards makes bluffs look like they never
  work (folded hands are weak, so they flatter our equity). Use hand strength against random hands instead.
- Postflop opening bets, whole field (n about 8,700): one pair earns +10 (flop) / +18 (turn); air or a draw -0 / -13;
  two pair or better +32 / +38. Ours: one pair +17 / +24, air -5 / -10 (same as the field).
- Two pair or better: ours +0 / -3 vs the field +32 / +38, but 3 of our 27 such bets lost 200 each (flush vs straight flush,
  77 vs an 8, etc). Our 7 overbets of 2.6x to 17x pot averaged **+40** (not a leak); our 20 normal-size bets averaged -13.
  So `v3.4-jamcap` is NOT supported by this data.
- Bets that get re-raised: field 10%, ours 10%. Bettor then folds 61% (field) vs 77% (ours); with air/draw ours get re-raised
  22% vs 11% (10 events). Too small to act on.
- Folds and calls vs real cards (83 decisions): folds that should have called and calls that should have folded cost about the
  same (411 vs 348 chips of equity gap). No systematic over-folding or over-calling.
- Stack-offs: 4 of 8 lost, but we were ahead in 5 of them (equity 68%, 95%, 93%, 78%, 65%) and behind in 2 (43%, 5%).

## How catherine and tungbot play, and bet size vs result (148 scraped games, Oct 4)

`python tools/bot_profile.py catherine tungbot love-of-da-game` (one row per bot plus the rest of the field).
catherine 17 games (place 0.35, +106 chips/game), tungbot only 5 games (0.29, +140), us 21 games (0.41, +246 mean, +180 median).

| | VPIP | flop seen | c-bet | flop bet | turn bet | showdown win |
|---|---|---|---|---|---|---|
| us | 17 | 9% | 62% | 0.61x | 1.97x | 63% |
| catherine | 24 | 15% | 90% | 0.89x | 0.89x | 61% |
| tungbot | 33 | 21% | 81% | 1.32x | 0.51x | 50% |
| rest of field | 25 | 16% | 67% | 0.94x | 0.88x | 49% |

- We play fewer hands and win showdowns far more often. Our mean chips/game is the highest of the three but our average
  place is worse (finishing place is what the tournament scores).
- Field opening bets by size (bettor held a pair or better, n about 7,000): flop result rises with size: <0.5x +0, 0.5-0.8x +13,
  0.8-1.2x +22, 1.2-2x +24. Turn: +18, +20, +30, +34, and **+109 +/- 16 for overbets above 2x**. Air/draw bets earn about 0 on
  the flop and lose 8 to 23 on the turn.
- **"Bigger flop value bets" tested and dropped:** our flop value bets are already 0.87x (two pair+) and median 0.82x (one pair).
  The 0.61x average was dragged down by probe bets with air/draws (0.42x). A candidate that forced value bets to >= 0.85x pot
  changes nothing in the test spots.
- C-bet frequency: air/draw c-bets are break-even across the field (n 2,077 flop, -0 per bet), so catherine's 90% c-bet rate is
  not evidence that we should c-bet more.

## "We climb then crash": is there a pattern? (25 of our games, Oct 4)

No specific cause found. Elo per game moves +/-50; schedule strength is flat (opponents' average Elo 990-1060);
we do best late in a game, not worst; our longest bottom-half run (6) occurs in 19% of random sequences with our
win rate. Against the GOON / jongwon we average about -250 chips per game vs +250 without them (7 games each).
**Mean +179 chips per game but median about -10**: four huge wins (+1,566, +1,802, +760, +575) carry the average, and our
average finishing place is the middle (0.49). Placement is what gets scored, so the typical game matters more than the mean.
"Slow starter" (+13 early vs +107 late per 25 hands) disappears without our 3 best games (+5 vs +12). No change made.

## Making the typical game better: what we checked (Oct 4, 14:00-14:40)

- **Protect a lead (play tight when far ahead late):** 165 real games. After 70 hands a leader 100-250 chips ahead finishes 1st only 68% of
  the time (n=53), 250-500 ahead 84% (n=31), 500+ 90% (n=10). We led after 70 hands in only 4 of 28 games and kept 1st in 3, so the
  ceiling is about +1 place point per 28 games (+0.04 per game). Too small to detect or justify; not built (Chi's earlier version also never changed a place).
- **Do the top-placing bots share a style?** Across 29 bots with >= 12 games, correlation of average place with VPIP +0.05, PFR +0.03,
  first-in open % -0.07, fold-to-raise % +0.10, flops seen % +0.05, c-bet % -0.07. No style predicts placement. Top bots (Gladiators, catherine,
  merch where, pocket-nuts, wicked wings combo, sungjinwoo) still lose chips on weak first-in opens (Chen < 4: -1.5, 4-6: -1.1 per open) but less
  than everyone else (-6.2, -3.1); they earn about +3 chips more per open at every strength. Their edge is conversion, not looseness.
- **Clock safety:** whole bot at 8 seats, 100 hands: 1.15 s per game normally (slowest decision 214 ms), 1.82 s per game with 10 CPU-burning processes
  competing (slowest 353 ms). Budget is about 40 s per game, so a timeout is not a realistic risk.
- **Bigger flop value bets:** already the case (see above), dropped.

## Trying to play better: decision quality vs real cards (Oct 4, 14:30-15:00)

Tools: `tools/decision_regret.py` (every postflop fold/call vs a bet, judged against the opponents' real hole cards),
`tools/make_instrumented.py` + `tools/calib_collect.py` (replay real hands through our bot and compare its own equity
estimate with the true equity). 16,673 scored decisions from 188 games; 8,234 replayed decisions.

- **Fold/call accuracy is not what separates the top bots.** Regret per decision (chips given away vs the better of fold/call): us 7.8,
  field about 8; merch where 11.3, idc 10.5, catherine 8.3 (all place well), netanyahu 2.4, kurimanju 4.0.
- **Where the chips come from, per 100 hands:** us +163, top-placing bots +129, rest of field -33. Top bots win 13.1 pots per 100 hands
  without a showdown (+158 chips) vs our 8.4 (+81), but fold after investing more (-130 vs -47). Our profit sits in showdowns and big pots.
- **Our model's equity estimate vs the truth:** flop is low by 6-10 points in every range (n about 4,900); turn about right (+0 to +5);
  river overestimates strong hands (says 69%, truth 56%). **Correcting it does not pay:** shifting the flop estimate +0.07 gains +380 chips on one
  half of the games and loses 118 on the other half; turn correction is positive on both halves but only about +1.8 chips per 100-hand game;
  river flips sign. Not shipped.
- **Does swing hurt placement?** Across 29 bots with >= 12 games: place = 0.56 - 0.027 x (mean chips/100) - 0.012 x (sd/100); the swing
  coefficient's 95% bootstrap range is -0.027 to +0.015, i.e. no evidence either way. Mean chips matters: each +100 chips per game is worth
  about 0.027 of finishing place. We average +169 chips (typical regular +46), predicted place about 0.45, observed 0.48.
- Bottom line: no change found that is both real and measurable; the gap to the very best bots is general skill after the flop.

## "How are the best bots better after the flop?" (Oct 4, 15:00-15:20)

`python tools/flop_policy_compare.py` (flop hands by the evaluator's hand class: share of flops, postflop profit, bet rate, fold rate, raise rate).
23,914 flop hands (4,828 by the top-placing bots, 391 by us).

- **Same flop policy by hand class.** With no bet to face, top / us / rest bet: medium made hands 64% / 64% / 54%, strong made 75% / 76% / 85%,
  weak draws 53% / 38% / 41%, trash 38% / 32% / 37%. Facing a flop bet, fold rates are alike (trash 85 / 82 / 76%, medium 33 / 27 / 35%).
  The top bots slow-play the nuts more (bet 63% vs 96% for the rest, n=82) with the same profit (+106 vs +102).
- **Postflop profit per flop hand by class (chips won/lost from the flop on):** strong made us +102, top +75, rest +55; medium +48 / +19 / +19;
  weak draw +29 / +15 / +9; trash +11 / +5 / +2. We are at least as good in every class (only 391 flop hands of ours, and we reach the flop with
  better hands: trash is 16% of our flops vs 24% for the top bots, so some of this is selection).
- **The "top bots" are mostly a selection effect.** Split-half test (26 regulars, 2000 random splits of each bot's games): a bot's average place in one half predicts
  the other half with correlation only +0.45; the 5 best placers in half A averaged place 0.40 there but 0.48 in half B (field 0.51), so only about 30% of the
  apparent edge reappears. Average chips per game is a much better skill signal (split-half correlation +0.87; top 5 by chips: +168 in half A, +86 in half B,
  field -46).
- **By average chips per game we rank 1st of 26 regulars (+154 +/- 79 over 36 games)**, tied within error with the GOON (+148), yep (+146), Gladiators (+145),
  catherine (+125), merch where (+113). Field median +24.
- Conclusion: no postflop deficit found; the placement gap to some bots is mostly variance. No change made.
