# Fold A2 poker room

Play no-limit hold'em in the browser against our bots, alone or with friends.

```bash
pip install https://poker.monashcoding.com/dl/macpoker-0.1.0-py3-none-any.whl numpy
python play/server.py                          # open http://localhost:8000
python play/server.py --host 0.0.0.0           # friends on the same Wi-Fi can join
```

- **Tables of 5 to 8**, with the same rules as the MAC tournament (official `macpoker` engine): 200-chip
  stacks reset every hand, blinds 1/2, and everyone moves one seat each hand.
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
