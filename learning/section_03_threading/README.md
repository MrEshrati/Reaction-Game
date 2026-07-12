# Section 3: Threading Fundamentals

The final client must wait for network messages, draw the Pygame window, and
handle mouse input at the same time. A single thread cannot wait inside
`recv()` and continue drawing frames because `recv()` is a blocking operation.

## What a thread is

A process is a running program. A thread is one path of execution inside that
process. Threads share the same variables and memory.

This project uses threads mainly for waiting on input/output:

- the main thread handles the window, rendering, and user input;
- a network thread waits for server messages;
- the server will later have separate threads for connected clients.

Python's Global Interpreter Lock means threads do not normally make
CPU-intensive Python calculations run in parallel. That is not a problem here:
our network thread spends most of its time waiting for socket data.

## Client thread model

```text
Socket
  |
  v
Network thread ---- puts messages ----> Queue
                                          |
                                          v
                                    Main/Pygame thread
                                    render and input
```

The network thread never draws to the screen. It only receives a complete
message and puts it into `incoming_messages`. The main thread checks that queue
while continuing its normal loop.

This ownership rule will matter in Pygame because graphical frameworks expect
window operations to happen on their main thread.

## Queue

`queue.Queue` safely transfers work between threads:

```python
incoming_messages.put(message)
message = incoming_messages.get()
```

The queue handles its own internal locking. It is better than having both
threads repeatedly change the same list.

The client uses `get(timeout=0.1)` instead of waiting forever. If the queue is
empty, `queue.Empty` is raised and the main loop continues to its next frame.

## Event

`threading.Event` is a shared yes/no signal:

```python
stop_event.set()
stop_event.is_set()
```

The network thread sets it after `game_over` or a connection failure. The main
thread uses it to know when the loop should finish.

An event does not automatically interrupt a blocking `recv()`. During manual
shutdown, the client closes the socket to wake the network thread and then
calls `join()` to wait for that thread to finish.

## Race conditions and locks

A race condition happens when the result depends on which thread happens to
run first. Imagine two server threads processing clicks on the same shape:

```text
Player 1 thread: shape is free -------- assign player 1
Player 2 thread:      shape is free -------- assign player 2
```

Both threads can see the shape as available before either update is complete.
Both players may incorrectly receive points.

A `Lock` lets only one thread enter the protected section at a time:

```python
with state_lock:
    if shared_shape["claimed_by"] is None:
        shared_shape["claimed_by"] = player_id
```

The check and the change must be inside the same lock. Protecting only the
assignment would still leave a race between the checks.

Keep locked sections short. A thread should not perform slow network operations
while holding the game-state lock.

## Starting and joining threads

`start()` asks the operating system to run the thread. Calling the target
function directly would run it on the current thread and would still block.

`join()` waits for a started thread to finish. We use normal non-daemon threads
and join them deliberately so socket and game cleanup cannot be abandoned when
the program exits.

## Run the network exercise

Open two PowerShell terminals in the repository root.

Terminal 1:

```powershell
python -m learning.section_03_threading.server
```

Terminal 2:

```powershell
python -m learning.section_03_threading.client
```

The server sends score updates every half second. The client network thread
receives them while the main thread keeps printing `Main loop frame`. The final
`game_over` message sets the stop event and both threads exit cleanly.

## Run the race-condition exercise

```powershell
python -m learning.section_03_threading.race_condition_demo
```

Two threads attempt to claim one shape. The winning player can vary because
thread scheduling is nondeterministic, but exactly one result must be `True`.

## Rules we will carry into the real game

1. Only the main client thread may render or handle Pygame events.
2. The network thread passes messages through a queue.
3. An event communicates shutdown.
4. Closing the socket wakes a thread blocked in `recv()`.
5. Threads are joined before the program exits.
6. The server protects shared match state with a lock.
7. Locks cover one complete check-and-change operation.
