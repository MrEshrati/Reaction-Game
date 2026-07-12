# Section 2: Message Framing and the Game Protocol

Section 1 sent one short piece of text with `recv(1024)`. That was useful for
learning the socket lifecycle, but it is not safe for a real game.

## Why framing is necessary

TCP is a stream of bytes. It does not preserve the boundaries between calls to
`sendall()`. For example, sending `ABC` and then `DEF` can be received as:

```text
ABCDEF
```

It can also arrive in smaller pieces:

```text
A | BC | D | EF
```

The receiver therefore needs a rule for finding the beginning and end of each
message. That rule is called **message framing**.

## Our frame format

Every message has two parts:

```text
+----------------------+--------------------------------+
| 4-byte payload size  | UTF-8 JSON payload             |
+----------------------+--------------------------------+
```

If the JSON payload is 57 bytes long, the sender first writes the number 57 as
a four-byte unsigned integer and then writes exactly 57 payload bytes.

The `!I` format passed to `struct.pack()` means:

- `!` uses network byte order, which is the standard order used across a
  network.
- `I` stores an unsigned four-byte integer.

`receive_exact()` is important because one call to `recv()` may return fewer
bytes than requested. It loops until the complete header or payload arrives.

## Message structure

Every JSON message follows the same structure:

```json
{
  "type": "click",
  "data": {
    "shape_id": 7
  }
}
```

- `type` tells the receiver what happened.
- `data` contains the information needed for that event.

The current protocol reserves these message types:

| Message type | Direction | Purpose |
| --- | --- | --- |
| `join` | Client to server | Request to join a game |
| `welcome` | Server to client | Assign a player identity |
| `game_start` | Server to client | Start a match |
| `shape_spawn` | Server to client | Display a new shape |
| `shape_remove` | Server to client | Remove an expired or claimed shape |
| `click` | Client to server | Report a click attempt |
| `score_update` | Server to client | Broadcast current scores |
| `player_state` | Server to client | Update stamina, stress, or effects |
| `game_over` | Server to client | Report the final result |
| `error` | Either direction | Report an invalid request or state |

The server remains authoritative. A `click` message is only a request; the
server will later decide whether it is valid.

## Run the exercise

Open two PowerShell terminals in the repository root.

Terminal 1:

```powershell
python -m learning.section_02_protocol.server
```

Terminal 2:

```powershell
python -m learning.section_02_protocol.client
```

The client sends a framed `join` message. The server decodes it and returns a
framed `welcome` message.

## What the safety checks do

The protocol rejects:

- messages without `type` and `data`;
- unknown message types;
- a `data` value that is not a dictionary;
- empty messages;
- messages larger than one megabyte;
- invalid UTF-8 or JSON;
- connections that close before a message is complete.

The one-megabyte limit prevents a faulty or malicious client from claiming
that an impossibly large message is about to arrive.
