# Section 7: Click Validation and Race-Condition Protection

The Pygame client knows which circle is under its mouse, but the server must
not trust that decision. A modified client could send any shape ID without
actually clicking its circle.

Section 7 makes the complete click operation authoritative on the server.

## The complete click request

The client now sends the shape ID and the actual mouse position:

```json
{
  "type": "click",
  "data": {
    "shape_id": 7,
    "x": 310,
    "y": 245
  }
}
```

The client still does not remove the shape or change a score. These changes
happen only after a server response.

## Server validation order

`process_click()` performs every important check before changing shared state:

1. The match must be running.
2. The player must still be connected.
3. The shape ID and coordinates must be real integers.
4. The coordinates must be inside the game window.
5. The player must not be frozen.
6. The shape must still exist.
7. The shape must be visible to this player.
8. The shape must not be expired.
9. The coordinates must be inside the shape's circle.

If any check fails, the shape remains active and the score stays unchanged.

Using `type(value) is int` is intentional. In Python, `bool` inherits from
`int`, so `isinstance(True, int)` returns `True`. Network input such as
`true` must not be accepted as a coordinate or shape ID.

## Circle hit testing

Every shape owns its hit-test behavior through `contains_point()`:

```text
x_distance = click_x - shape_x
y_distance = click_y - shape_y

x_distance^2 + y_distance^2 <= radius^2
```

The left side is the squared distance from the click to the circle center.
Comparing squared values avoids an unnecessary square-root operation.

A point exactly on the circle edge is accepted because the comparison uses
`<=`.

## Why the state lock matters

Each connected player has a different client thread. Both threads can receive
a click for the same shape at nearly the same moment.

Without a lock, this sequence is possible:

```text
Player 1 thread: sees shape 7
Player 2 thread: sees shape 7
Player 1 thread: awards points and removes shape 7
Player 2 thread: awards points and tries to remove shape 7 again
```

That is a race condition. The result depends on thread timing instead of the
game rules.

`process_click()` holds `state_lock` across the entire check-and-change
operation:

```text
acquire lock
    validate player, shape, time, visibility, and coordinates
    remove the shape
    update the score and effects
    copy the new public state
release lock
```

The second thread cannot inspect the shape until the first thread has finished
removing it. It therefore receives "The shape is no longer available" and
cannot receive points.

This is called an atomic operation: other threads see either the state before
the operation or the state after it, never a half-finished state.

## Stale and duplicate clicks

A valid request can still arrive too late because of network delay. The server
rejects it if:

- the shape already expired;
- the opponent already claimed it;
- the same client already claimed it;
- the match already ended.

The client uses `pending_clicks` to avoid sending the same request repeatedly.
An accepted request is cleared by `shape_remove`. A rejected response includes
the related `shape_id`, allowing the client to clear it immediately too.

## What the tests prove

`tests/test_section_07_click_validation.py` checks:

- points on and outside the circle edge;
- forged clicks that miss the claimed shape;
- incomplete requests with a missing coordinate;
- coordinates outside the game window;
- boolean values disguised as integers;
- rejection messages and pending-click cleanup;
- twenty rounds of simultaneous two-player clicks.

In every simultaneous round, exactly one request succeeds and exactly one
shape score is added.

Run only this section:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_section_07_click_validation -v
```

Run the entire project:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

You can also run the server and two graphical clients normally. The wire
protocol now carries the click coordinates, but the visible controls remain
the same.
