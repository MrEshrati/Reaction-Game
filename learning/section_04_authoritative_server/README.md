# Section 4: Minimal Authoritative Game Server

This section turns the networking, protocol, and threading exercises into the
first real part of the project. Two clients can join one match and compete for
server-generated shapes.

The server is **authoritative**: it owns the true game state and makes every
important decision. Clients only display events and request actions.

## Why the server must be authoritative

An unsafe client could send this claim:

```json
{
  "type": "score_update",
  "data": {
    "score": 999999
  }
}
```

Our server rejects that message. A client is only allowed to send a `click`
request containing a shape ID. The server checks whether the shape exists,
whether it has expired, and whether another player already claimed it. Only the
server changes scores.

## Server-owned state

The server keeps these values:

| State | Purpose |
| --- | --- |
| `clients` | Connected player records and sockets |
| `scores` | Authoritative score for every player |
| `active_shapes` | Shapes that can still be claimed |
| `next_shape_id` | Unique ID for the next shape |
| `match_running` | Whether clicks are currently accepted |
| `state_lock` | Protection for shared match state |
| `match_stop_event` | Early match-stop signal |

The server uses `time.monotonic()` for expiration and the match timer. A
monotonic clock cannot move backward if the computer's wall clock changes.

## Server threads

```text
Main server thread
  |
  +-- Player 1 client thread -- receive click requests
  |
  +-- Player 2 client thread -- receive click requests
  |
  +-- Match thread ---------- timer and shape generation
```

The main thread accepts sockets. Each client thread waits for messages from one
player. The match thread creates shapes and owns the match schedule.

These threads share the match dictionaries, so every click uses the same
`state_lock`.

## Atomic click validation

The following steps happen while one lock is held:

1. Confirm that the match is running.
2. Confirm that the player is connected.
3. Find the requested shape.
4. Confirm that the shape has not expired.
5. Delete the shape so nobody else can claim it.
6. Change the player's score.

If two client threads request the same shape, the first thread deletes it. The
second thread then receives an error because the shape is no longer available.

The server releases the state lock before broadcasting messages. Slow network
operations must not freeze the entire game state.

## Per-client send locks

The match thread and both client threads may send events at nearly the same
time. If two threads write to one socket together, their bytes could be mixed.

Each client record therefore has its own `send_lock`. One complete framed
message is written before another thread can write to that socket.

## Match message flow

```text
Client                         Server
  |------ join ----------------->|
  |<----- welcome ---------------|
  |<----- game_start ------------|  after two players join
  |<----- shape_spawn -----------|
  |------ click ---------------->|
  |<----- shape_remove ----------|  sent to both players
  |<----- score_update ----------|  sent to both players
  |<----- game_over -------------|  when the timer finishes
```

All clients receive the same shape ID, position, point value, and lifetime.
This keeps both screens synchronized.

## Run the minimal match

Open three PowerShell terminals in the repository root.

Terminal 1:

```powershell
python -m server.run_server
```

Terminal 2:

```powershell
python -m learning.section_04_authoritative_server.bot_client
```

Terminal 3:

```powershell
python -m learning.section_04_authoritative_server.bot_client
```

Give the two bots different names. Both automatically request every spawned
shape. Only one click is accepted for each shape, and both clients receive the
same score updates.

Stop the server with `Ctrl+C` after the match.

## Current limitations

This is intentionally the smallest authoritative match:

- it supports exactly two players and one match per server run;
- all shapes are simple normal circles;
- it has no graphical client yet;
- it has no stamina or stress effects;
- it has no lobby, replay, or spectator mode.

The next sections add these features without changing the central rule that
the server owns the truth.
