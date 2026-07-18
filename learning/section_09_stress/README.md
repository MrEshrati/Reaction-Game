# Section 9: Stress System

Stress is the second server-authoritative player attribute. It stays between
0% and 100% and changes according to the player's decisions.

The server owns the stress number and hallucination schedule. The client uses
received stress only to apply visual and mouse-control effects.

## Stress changes

The PDF defines these click results:

| Action | Stress change |
| --- | --- |
| Click empty space | `+5` |
| Click a low positive shape (`1` or `2`) | `+10` |
| Click a negative shape (`-3` to `-1`) | `+30` |
| Click a high positive shape (`3` to `6`) | `-5` |
| Click shield or ice | No change |

Every accepted empty click also costs 5 stamina. The server first verifies
that the reported coordinate does not contain a shape visible to that player.
This prevents a modified client from describing a real shape click as empty.

Shield itself changes neither stamina nor stress. An active shield still
blocks negative score points, but a later negative-shape click follows its
normal stamina and stress rules.

Hallucinations award no points, but their hidden normal category still changes
stress. Clicking a negative hallucination therefore adds 30 stress and costs 5
stamina without changing the score.

## Passive stress recovery

While stamina remains between 90% and 100%, stress decreases by 10 every two
active seconds.

The `PlayerStress` object tracks this time using the server's monotonic clock.
Dropping below 90 stamina resets the recovery interval. Ice time is excluded,
so stress and stamina both remain fixed while frozen.

## Cumulative stress effects

Higher stress keeps all applicable earlier effects:

| Stress | Active effects |
| --- | --- |
| 0% to 10% | None |
| 11% to 30% | Mouse speed reduced by 15% |
| 31% to 50% | 15% reduction and random mouse jumps |
| 51% to below 70% | 40% reduction, jumps, trail, and hallucinations |
| 70% to 100% | All effects and twice the hallucination rate |

Percentage reductions are not added together. At 60 stress, the strongest
40% reduction is used instead of combining 15% and 40% into 55%.

## Protected virtual mouse

The client uses a virtual in-game cursor rather than clicking directly with
the operating-system cursor.

During the first two seconds, it compares raw relative movement from
`pygame.mouse.get_rel()` with actual cursor displacement and saves their
average ratio. After calibration, movement always uses that saved baseline:

```text
virtual movement = raw movement * saved baseline * stress multiplier
```

If the player changes operating-system mouse speed later, the observed ratio
may change, but the game continues using the original value. This preserves
the stress slowdown.

The real cursor is hidden and captured during the match. Click requests use
the virtual cursor position, which is also drawn by Pygame.

## Mouse jumps and trail

At 31 stress or above, the server-provided stress causes the virtual cursor to
jump to a random game position once every three seconds.

At 51 stress or above, the client also keeps the last eight cursor positions
and draws fading cursor silhouettes behind the current one.

These are client presentation effects. Scores and click validity still come
from the server.

## Hallucinations

At 51 stress, the server creates one hallucination every three seconds. At 70
or above, the interval becomes 1.5 seconds, producing twice as many.

Each hallucination:

- looks exactly like a normal scoring circle;
- is sent only to its affected player;
- is stored in the server's active shape collection;
- cannot be claimed by the opponent by guessing its ID;
- costs stamina and changes stress when clicked;
- awards no score.

The affected client cannot distinguish a hallucination visually, which is the
purpose of the mechanic.

## Player state messages

The existing `player_state` message now contains both values:

```json
{
  "players": {
    "1": {
      "stamina": 65,
      "stress": 55,
      "shield_seconds": 0,
      "frozen_seconds": 0
    }
  }
}
```

The top panel displays a yellow stamina bar and a red stress bar.

## Run the tests

Run only this section:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_section_09_stress -v
```

Run the complete project:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

For a manual demonstration, click low, negative, and empty areas to raise
stress. Once it reaches 31, watch for three-second cursor jumps. At 51, the
cursor trail and private hallucinations begin.
