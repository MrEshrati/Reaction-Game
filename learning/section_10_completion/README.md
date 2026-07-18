# Section 10: Game Completion and Reliability

This section completes the required match lifecycle from the project PDF. The
first player to enter an empty lobby creates the match, chooses its duration,
and becomes the host. The second player joins the host's existing settings.

The game still has one authority: the server. A client may request a duration,
but only the server stores the duration, runs the timer, freezes the final
scores, and announces the winner.

## Match setup protocol

The client now includes a duration in its first message:

```json
{
  "type": "join",
  "data": {
    "name": "Arshia",
    "duration": 45
  }
}
```

The duration must be a whole number from 10 to 300 seconds. The server validates
the value instead of trusting the Pygame input field.

When the first player registers, the server copies that requested value into
shared match state. A later player's requested value is valid protocol input,
but it does not replace the host's choice.

The server's `welcome` response returns:

- the assigned player ID;
- whether that player is the host;
- the authoritative match duration;
- how many players are still needed.

Both clients therefore display the same timer setting before the game starts.

## Complete lifecycle

```text
Host connects and selects duration
              |
              v
Server validates and stores duration
              |
              v
Second player connects
              |
              v
Server starts one match thread
              |
              v
Timer ends -------- or -------- player disconnects
     |                              |
     v                              v
Highest score wins          Connected player wins
              \              /
               v            v
          Server sends game_over
```

The client timer is only a display estimate. `time.monotonic()` on the server is
the real clock because it cannot move backward when the computer's wall clock
changes.

## Why the server owns completion

If each client ended its own match, their clocks and network delays could
produce different final clicks and different winners. Instead, the match thread
changes `match_running` to false while holding the state lock. Any click checked
after that point is rejected.

The same lock protects final score copying. The server then sends one
`game_over` message containing the reason, final scores, and winner.

## Disconnect reliability

There are two distinct disconnect cases:

1. If the host leaves an otherwise empty waiting lobby, their player state is
   removed and the next player becomes player 1 and the new host.
2. If a player leaves after the match begins, the match stop event wakes the
   match thread and the connected player wins.

This is another use of threading events. An event is safer than repeatedly
checking a normal Boolean because it is thread-safe and its `wait()` method can
wake early.

## Stopping a blocked socket thread

The server's main thread normally blocks in `accept()` while waiting for a new
TCP connection. A stop event alone cannot interrupt an unlimited blocking call.

Section 10 gives the listening socket a short timeout. Every 0.2 seconds,
`accept()` temporarily wakes and the loop checks `server_stop_event`. This does
not mean the server disconnects clients every 0.2 seconds; it only gives the
accept loop a chance to notice shutdown.

Client threads still block in `recv()`. During shutdown, their sockets are
closed first, which wakes those calls, and only then are the threads joined.

## Pygame controls

On the connection screen:

- click the player-name or duration field to select it;
- press `Tab` to switch fields;
- enter a duration from 10 to 300 seconds;
- press `Enter` or click **Connect**.

The waiting screen identifies the host and shows the server-confirmed duration.
The final screen distinguishes a completed timer from a player disconnect.

## Bonus features not included

The PDF lists replay, multiplayer rooms, spectators, and a more advanced GUI as
bonus work. They are intentionally outside this required completion section so
the two-player match remains understandable and reliable.

## Run the tests

Run only this section:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_section_10_completion -v
```

Run the complete project:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

For a manual test, start the server, open two clients, and choose different
durations in them. The first connected client's choice should appear on both
waiting screens and should control when the match ends.
