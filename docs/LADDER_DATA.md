# Using real ladder games

Every ladder game is saved as a JSON hand history with **all players' hole
cards, including folded hands**. That makes it the best test data we have:
our own test bots are much softer than the ladder.

## 1. Download games: `tools/scrape_ladder.py`

```bash
python tools/scrape_ladder.py            # all recent ladder games
python tools/scrape_ladder.py --delay 2  # slower, gentler on the server
```

- Saves `games/<match id>.json` plus `games/index.json` (names, chips, time).
- Re-running only fetches new games, so run it as often as you like.
- The site only returns **recent** matches (about the last 45 minutes), so
  scrape regularly if you want a longer history.
- Organisers OK'd scraping. It uses the same public queries as the website,
  one request per `--delay` seconds. Don't lower the delay.
- `games/` is gitignored. **Never commit it.**

Each file adds `names` (bot names in bot-index order), `result`, `elo` and
`at` to the raw history.

Without the scraper you can grab one game by hand: open a game's
**Watch ▸** page, DevTools → Network → filter `storage`, and save the
`/api/storage/<id>` response.

## 2. File format

```text
hands[i].seat_map[seat] = bot index      (bot index = order of `names`)
hands[i].holes[str(seat)]  = ["As","Kd"]  (every seat, folded or not)
hands[i].deltas_by_bot[bot] = chips won/lost that hand
hands[i].events = blinds / action / street / hand_end
```

- Our seat in a hand: `seat_map.index(our_bot_index)`.
- `action.amount`: **raise-to** total for the street on raises, chips added on calls.
- The button is always seat 0.

## 3. Replay a game through any build: `tools/ladder_replay.py`

```bash
python tools/ladder_replay.py macpoker-scaffold/main.py <our index>:games/<id>.json [more ...]
```

It feeds the bot the exact messages it saw on the ladder and lists every
decision where this build would act differently. Our live bot reproduces at
96-99%, so:

- **Which version played?** The build with the highest match % is the one
  that was uploaded. (This is how we found the first upload was the template.)
- **What would a change have done?** "net chips from folds that differ" is
  exact: if the new build folds where we put more in, our result would have
  been minus what we'd already committed. Calls and raises after a divergence
  aren't exact, because opponents' later actions are fixed by the recording.
- An all-in shows as `raise1000000000` in the replay column. That's the same
  action as a ladder `raise` to our full stack.

## 4. Analysis ideas that paid off

- **Luck-adjust before judging.** For every all-in before the river, replace
  the result with our equity at that moment. Four "terrible" games were
  mostly AA/KK coolers.
- **Profile bots**: VPIP, PFR, postflop aggression, bet sizes, profit by
  street (`tools/analyze_game.py`).
- **Check folds against the real cards**: when we fold to a bet, the file
  shows whether we folded the winner.
- **Group calls by hand strength**: calling big river bets with two pair+
  made +33/call on the ladder, one pair or less lost -43/call. That one
  number drove v3.5.

See [EXPERIMENTS.md](EXPERIMENTS.md) for what each finding turned into.
