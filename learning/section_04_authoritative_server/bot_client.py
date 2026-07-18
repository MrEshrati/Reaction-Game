import queue
import socket
import threading

from shared.protocol import create_message, send_message
from shared.threading_tools import receive_messages


HOST = "127.0.0.1"
PORT = 5050


player_name = input("Bot player name: ")
incoming_messages = queue.Queue()
stop_event = threading.Event()
client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

try:
    client_socket.connect((HOST, PORT))
    join_message = create_message("join", {"name": player_name})
    send_message(client_socket, join_message)

    network_thread = threading.Thread(
        target=receive_messages,
        args=(client_socket, incoming_messages, stop_event),
    )
    network_thread.start()

    while not stop_event.is_set() or not incoming_messages.empty():
        try:
            message = incoming_messages.get(timeout=0.1)
        except queue.Empty:
            continue

        print("Received:", message)

        if message["type"] == "shape_spawn":
            shape_data = message["data"]
            click_message = create_message(
                "click",
                {
                    "shape_id": shape_data["shape_id"],
                    "x": shape_data["x"],
                    "y": shape_data["y"],
                },
            )
            send_message(client_socket, click_message)
except KeyboardInterrupt:
    print("Stopping the bot client...")
    stop_event.set()
except (ConnectionError, OSError, ValueError) as error:
    print("Client error:", error)
finally:
    client_socket.close()

    if "network_thread" in locals():
        network_thread.join(timeout=2)
