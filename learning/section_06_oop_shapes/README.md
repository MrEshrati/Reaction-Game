# Section 6: Object-Oriented Shape System

The previous server stored each shape as a dictionary. That worked for normal
circles, but adding shield, ice, and hallucination behavior would create many
type checks throughout the server and client.

Section 6 replaces those dictionaries with a shared class hierarchy.

## The hierarchy

```text
Shape (abstract base class)
├── NormalShape
│   └── HallucinationShape
├── ShieldShape
└── IceShape
```

All classes are in `game/shapes.py`, which is imported by both the server and
client. They contain no Pygame or socket code.

## Why Shape is abstract

Every shape must have a concrete type such as `normal`, `shield`, or `ice`.
Creating a plain `Shape` would leave that behavior undefined.

`Shape` therefore inherits from `ABC`, and `get_shape_type()` uses
`@abstractmethod`. Python prevents a plain `Shape` from being created until a
subclass implements that method.

This is one of the rare cases where a decorator is required by the project
design rather than added for convenience.

## Encapsulation

Common values are stored with underscore-prefixed names:

```python
self._shape_id = shape_id
self._points = points
self._expires_at = created_at + lifetime
```

Other parts of the project use methods such as:

```python
shape.get_id()
shape.get_points()
shape.is_expired()
```

This keeps expiration and validation rules inside the shape object. The server
no longer needs to know how the expiration time was calculated.

## Inheritance

`Shape` implements data and behavior shared by every type:

- ID, name, position, radius, score, and lifetime;
- expiration checking;
- visibility checking;
- network spawn data;
- the default click result.

`NormalShape` adds the required score categories:

| Points | Category |
| --- | --- |
| `-3` to `-1` | Negative |
| `1` to `2` | Low |
| `3` to `6` | High |

`HallucinationShape` inherits from `NormalShape`, so it follows the same score
rules. It overrides visibility so only its affected player can receive or
claim it. Automatic hallucination generation will be connected to stress in
Section 9.

## Polymorphism

The server asks every clicked object the same question:

```python
click_result = shape.get_click_result()
```

The result depends on the concrete object:

- `NormalShape` returns its points and no effect;
- `ShieldShape` returns a five-second shield effect;
- `IceShape` returns a three-second freeze effect;
- `HallucinationShape` uses normal scoring.

The server does not need a large `if shape_type == ...` block to discover the
effect. Each class provides its own implementation.

## Factory functions

The server calls `create_random_shape()` and receives a concrete object. The
current configured frequency is:

- 70% normal;
- 15% shield;
- 15% ice.

The client calls `shape_from_message()` to reconstruct the corresponding class
from a `shape_spawn` message. Both sides then use the same object methods.

## Shield behavior

Clicking a shield grants five seconds of protection from negative shape
points. A protected negative click is accepted and removes the shape, but its
awarded score becomes zero.

Repeated shield clicks stack:

```text
first shield:  5 seconds
second shield: 10 seconds total
```

The server stores the shield end time. The client only displays the remaining
time and cannot decide whether a penalty is blocked.

Shield effects on stamina and stress will be completed when those systems are
implemented.

## Ice behavior

Clicking ice freezes every opponent for three seconds. A frozen player's click
request is rejected by the server. The Pygame client also blocks the local
request immediately to give faster feedback, but the server check remains the
authoritative protection.

Repeated ice clicks add to the existing freeze end time.

The requirement that stamina and stress remain fixed during a freeze will be
connected when those player systems exist.

## Per-player state messages

After each accepted click, the server broadcasts a `player_state` message:

```json
{
  "type": "player_state",
  "data": {
    "players": {
      "1": {
        "shield_seconds": 5,
        "frozen_seconds": 0
      }
    }
  }
}
```

The server keeps absolute monotonic end times private. Clients convert the
remaining seconds into local display end times.

## Shape rendering

- Normal positive circles are green.
- Normal negative circles are red.
- Shield circles are blue and display `S`.
- Ice circles are cyan and display `ICE`.
- Hallucinations deliberately look like normal shapes so the affected player
  cannot identify them visually.

## Run the match

Open one server and two client terminals:

```powershell
.\.venv\Scripts\python.exe -m server.run_server
```

```powershell
.\.venv\Scripts\python.exe -m client.run_client
```

The server now generates normal, shield, and ice objects. Watch the effect
countdown below the game timer after a special shape is claimed.
