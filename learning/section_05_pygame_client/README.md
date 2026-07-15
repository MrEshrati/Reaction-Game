# Section 5: Basic Pygame Client

This section replaces the automatic bot with the first graphical game client.
It connects to the authoritative server from Section 4 and turns server events
into a live two-player interface.

## Install the dependency

The project now uses an isolated `.venv`. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Use `.venv\Scripts\python.exe` for the remaining commands in this lesson.

## The main rule

Only the main thread uses Pygame:

```text
Server socket
     |
     v
Network thread ----> incoming_messages Queue
                              |
                              v
                     Pygame main thread
                     events, state, drawing
```

The network thread calls `receive_message()` and puts complete messages into a
queue. The Pygame loop drains that queue once per frame and changes the client
state.

The network thread never calls `pygame.draw`, `pygame.display`, or
`pygame.event`. This avoids unpredictable window behavior.

## Client screens

The client state has a `screen_name` value:

| Screen | Purpose |
| --- | --- |
| `connect` | Enter a player name and connect |
| `waiting` | Wait until two players have joined |
| `game` | Render shapes, scores, status, and timer |
| `final` | Show the winner and final scores |
| `disconnected` | Explain an unexpected connection loss |

The program uses one Pygame loop and chooses a drawing function from this
value. It does not create a separate window for each screen.

## Server messages become client state

`handle_server_message()` applies events:

- `welcome` stores the assigned player ID;
- `game_start` clears old state and starts the displayed timer;
- `shape_spawn` adds a circle to the visual dictionary;
- `shape_remove` removes the confirmed shape;
- `score_update` replaces the displayed authoritative scores;
- `game_over` opens the final screen;
- `error` displays server or connection feedback.

All state changes happen on the main thread after a queue read.

## Click handling

For every circle, the client checks:

```text
(mouse_x - shape_x)^2 + (mouse_y - shape_y)^2 <= radius^2
```

If this is true, the mouse is inside the circle. The client sends:

```json
{
  "type": "click",
  "data": {
    "shape_id": 7
  }
}
```

The client does not remove the shape or add points immediately. It waits for
the server's `shape_remove` and `score_update` events. This preserves the
authoritative design.

`pending_clicks` prevents the same client from sending many requests for one
shape while waiting for the server response.

## Visual expiration

The client estimates when a shape should disappear using the lifetime sent by
the server. Removing an expired visual does not change server state or scores.
If a late click reaches the server, the server independently checks its own
monotonic expiration time.

## Run the graphical match

Open three PowerShell terminals in the repository root.

Terminal 1:

```powershell
.\.venv\Scripts\python.exe -m server.run_server
```

Terminal 2:

```powershell
.\.venv\Scripts\python.exe -m client.run_client
```

Terminal 3:

```powershell
.\.venv\Scripts\python.exe -m client.run_client
```

Enter a different name in each client. The match begins automatically after
both players connect.

## What remains intentionally simple

- Shapes are basic circles drawn directly with Pygame.
- Only normal positive and negative score shapes exist.
- The displayed timer is estimated from the server-provided duration.
- There is no stamina, stress, shield, ice, or hallucination behavior yet.

Section 6 will replace the simple shape dictionaries with the required OOP
shape hierarchy.
