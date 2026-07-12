import queue
import socket
import threading

from shared.threading_tools import receive_messages


HOST = "127.0.0.1"
PORT = 5052


incoming_messages = queue.Queue()
stop_event = threading.Event()
client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

try:
    client_socket.connect((HOST, PORT))

    network_thread = threading.Thread(
        target=receive_messages,
        args=(client_socket, incoming_messages, stop_event),
    )
    network_thread.start()

    print("The main loop is responsive while the network thread waits.")

    while not stop_event.is_set() or not incoming_messages.empty():
        try:
            message = incoming_messages.get(timeout=0.1)
            print("Main thread handled:", message)
        except queue.Empty:
            print("Main loop frame")

    network_thread.join()
except KeyboardInterrupt:
    print("Stopping the client...")
    stop_event.set()
    client_socket.close()

    if "network_thread" in locals():
        network_thread.join(timeout=2)
except OSError as error:
    print("Client error:", error)
finally:
    client_socket.close()
