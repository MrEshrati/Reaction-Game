# Section 8: Stamina System

Every player now has server-authoritative stamina between 0% and 100%. The
client displays it, but cannot choose its value or apply its effects.

The implementation is split between:

- `game/player.py`, which owns stamina values and timing;
- `server/game_server.py`, which applies stamina to clicks and visibility;
- `client/game_client.py`, which displays the server state.

## Stamina bands

The project PDF defines these states:

| Stamina | Effect |
| --- | --- |
| 90% to 100% | Positive points are doubled and negative points are halved |
| 60% to below 90% | No extra effect |
| 40% to below 60% | The game area becomes darker |
| Above 10% to below 40% | Some shapes are randomly hidden |
| 0% to 10% | The player cannot click until stamina recovers |

Using one clear boundary for each exact value avoids overlapping ranges. For
example, 90% receives the high-stamina effect, 60% is normal, and 10% is
depleted.

The high-stamina effect uses the value immediately before the click cost is
removed. At 90 stamina, clicking a four-point shape awards eight points and
then reduces stamina to 85.

Negative scores may become decimal values. A `-3` shape at high stamina is
worth `-1.5` because the requirement says its effect is halved.

## The PlayerStamina class

`PlayerStamina` encapsulates:

- the current value;
- the last time it was updated;
- accumulated active inactivity;
- recovery, spending, level selection, and score adjustment.

Its public methods include:

```python
stamina.get_value()
stamina.can_play()
stamina.spend_for_click()
stamina.adjust_shape_points(points)
stamina.get_level()
```

The value stays between zero and one hundred. Other project code does not
directly modify its private fields.

## Click cost and recovery

Every accepted non-shield shape click costs 5 stamina. A rejected click does
not cost stamina because it did not change the game state.

After two seconds without another stamina-using click, 10 stamina returns.
Every additional two active seconds restores another 10:

```text
time after click: 0s   2s   4s   6s
stamina:         50   60   70   80
```

A new click resets this recovery timer.

The match thread checks recovery every tenth of a second. It sends a new
`player_state` message only when a stamina value actually changes, avoiding
unnecessary network messages every frame.

## Freeze pauses stamina

The PDF says stamina and stress remain fixed while a player is frozen by ice.
`PlayerStamina.update()` therefore excludes frozen time from the inactivity
counter.

If a player is frozen for five seconds and then remains inactive for another
two seconds, only those final two seconds count and 10 stamina is restored.

## Special shapes

The polymorphic click result now includes `stamina_cost`:

- normal shapes cost 5;
- ice costs 5;
- shield costs 0 because the PDF says shield does not affect stamina;
- hallucinations cost 5 but award no points.

Hallucinations still inherit a normal shape's hidden point category for the
future stress rules, but their click result changes the awarded points to
zero, matching the PDF requirement.

## Low-stamina visibility

At more than 10 and less than 40 stamina, each new shape has a 50% chance of
being hidden from that player. The PDF requires random hiding but does not
specify a percentage, so the project uses an explicit 50% constant.

The server records which players received every shape. A player cannot bypass
the visual restriction by guessing a hidden shape ID because `process_click()`
checks that visibility record before awarding points.

The other player can still receive and claim the same shape normally.

## Client feedback

The top panel now displays the local player's stamina percentage and a yellow
bar.

Between 40 and below 60 stamina, a transparent black layer gradually darkens
the game area. At 60 it is clear; at 40 it reaches the configured maximum
darkness.

At 10 or below, the client immediately blocks the local click and displays a
recovery message. The server performs the same check, so changing the client
cannot bypass it.

## Run the tests

Run only the stamina section:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_section_08_stamina -v
```

Run every section:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

For a manual test, run one server and two clients. Click several non-shield
shapes and watch the stamina bar decrease. Stop clicking and it will recover
in ten-point steps every two seconds.
