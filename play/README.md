# Fold A2 poker room

Play no-limit hold'em in the browser against our bots, alone or with friends.

```bash
pip install https://poker.monashcoding.com/dl/macpoker-0.1.0-py3-none-any.whl numpy
python play/server.py                          # open http://localhost:8000
python play/server.py --host 0.0.0.0           # friends on the same Wi-Fi can join
```

- **Two game types**, both on the official `macpoker` hand engine, tables of 5 to 8:
  - **Knockout (normal poker)**: stacks carry over (200 / 500 / 1000 to start), players keep their seats and
    the dealer button and blinds move round the table, blinds go up every 10 or 20 hands (or never), busted
    players are out, and the last player with chips wins.
  - **MAC tournament format**: 200-chip stacks reset every hand, blinds 1/2, everyone moves one seat each hand.
- **Standings** show the chips each player has left (knockout), or net chips won or lost (MAC format).
- **Rewatch hands**: step through any finished hand action by action (or press Play). You see your own
  cards, every bot's cards, and other people's cards only if they were shown at showdown.
- Split pots are reported as splits ("A and B split the pot of 120"), with side pots named only when
  different players win them.
- **Opponents:** Fold-A2 v4.2 (our tournament entry), v3.5, the house bots, and copies of real ladder bots.
  The copies only appear if `opponents/clone_data.json` exists; rebuild it with `python tools/v4/fit.py`.
- **Multiplayer:** choose *Multiplayer (host)* and pick how many human seats, then share the invite link.
  Friends open it, enter a name and take a seat; the host presses Start. Seats nobody claims become
  Fold-A2 v4.2. Each player only sees their own cards until showdown. There's a 45-second turn timer in
  multiplayer; when it runs out, the player checks if they can, otherwise folds.
- Keys: `F` fold, `C` check/call, `R` raise, `Space` next hand.
- To reopen your seat in another browser, add `#t=<your token>` to the room link. The token is stored in
  your browser's localStorage.

How it works: `server.py` runs each table's game in a thread. Bots are in-process transports with a short
think pause, and each human seat is a transport that waits for that player's click. The browser polls
`/api/state` about three times a second. It uses only the standard library, so moving to WebSockets or a
hosted server later only changes the transport layer, not the game.

## Running it for other people

```bash
python play/server.py --host 0.0.0.0 --port 8000 --max-rooms 100 --idle-minutes 10
```

- `--max-rooms`: most tables hosted at once. Beyond that, "create" answers 503 and the page shows
  "The server is full right now."
- `--idle-minutes`: a table nobody has talked to for this long (closed tab, abandoned game) is closed, which
  also stops its game thread. Without this, every abandoned table kept a thread alive forever.
- Shuffles use the operating system's randomness. The seed that drives bots is private to the server and is never
  sent to a browser. Names are escaped before display.
- Not included: HTTPS (use a host or reverse proxy that provides it), per-visitor rate limiting, accounts, or
  keeping games across a restart (tables live in memory, so run a single instance).
- The server needs the `macpoker` SDK (`pip install https://poker.monashcoding.com/dl/macpoker-0.1.0-py3-none-any.whl`).
  Check that link will stay up, and the SDK's licence, before depending on it for a public deployment.
- Opponent copies of real ladder bots only appear if `opponents/clone_data.json` exists. It is built from
  scraped games, is not in git, and so will not be on a deployment unless you add it.

## Tests

```bash
python play/tests/privacy.py                       # in-process, no server needed
python play/tests/hardening.py                     # starts its own small server; ~1 minute
python play/server.py --port 8000 &                # then, against a running server:
python play/tests/suite.py http://127.0.0.1:8000   # 73 end-to-end checks; ~4 minutes
python play/tests/attack.py http://127.0.0.1:8000  # must print 0/18 for both modes
```

`suite.py` and `attack.py` accept any base URL, so they can smoke-test a deployment (they create many throwaway tables).
