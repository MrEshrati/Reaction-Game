# Reaction Game - Final Version

## Folder structure

```text
Reaction-Game/
|-- client.py              Start one Pygame client
|-- server.py              Start the authoritative game server
|-- requirements.txt       Python dependency list
|-- client/                Pygame screens and client networking
|-- server/                Match state, validation, and server networking
|-- game/                  Shape and player classes
`-- shared/                Protocol, settings, and threading helpers
```

## Install

Open PowerShell in the cloned project folder and install the dependency:

```powershell
python -m pip install pygame
```

## Run the game

Start the server in the first terminal:

```powershell
python server.py
```

Start one client in a second terminal:

```powershell
python client.py
```

Start another client in a third terminal with the same command. The first
connected player is the host and selects the match duration. The match begins
automatically after the second player connects.

The default address is `127.0.0.1:5050`, so both clients run on the same
computer. To play across different computers, change `SERVER_HOST` in
`client/game_client.py` to the server computer's local IP address and allow TCP
port `5050` through the server computer's firewall.
