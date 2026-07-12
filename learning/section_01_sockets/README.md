# Section 1: TCP Socket Fundamentals

This section creates the smallest useful client/server program. The server
waits for one client, receives one short message, replies, and exits.

## Mental model

A **socket** is one endpoint of a network conversation. For this example:

- `127.0.0.1` means this computer (also called localhost).
- `5050` identifies the program on that computer.
- TCP provides an ordered, reliable stream of bytes.
- Text must be encoded into bytes before sending and decoded after receiving.

The connection flow is:

```text
Server                                      Client
socket()                                    socket()
bind()                                      |
listen()                                    |
accept() <------------------------------ connect()
recv()   <------------------------------ sendall()
sendall() ------------------------------> recv()
close()                                     close()
```

`accept()` and `recv()` are blocking operations: they wait until something
happens. This is why the final game will need threading. We will study that in
a dedicated section rather than hiding it inside this first example.

## Run the example

From the repository root, open two PowerShell terminals.

In terminal 1:

```powershell
python -m learning.section_01_sockets.server
```

In terminal 2:

```powershell
python -m learning.section_01_sockets.client
```

Enter a short message in the client. Both programs should print the message,
and the server will exit after replying.

Start the server first. If the client is started while no server is listening,
the operating system will reject the connection.

## Important limitation

Calling `recv(1024)` does **not** mean one complete application message will
always arrive. TCP only provides a stream of bytes; a message can be split or
combined with another message. This example works with one short exchange, but
it is not yet a safe game protocol. Section 2 will solve that with explicit
message framing.

