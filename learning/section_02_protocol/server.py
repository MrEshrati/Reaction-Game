import socket

from shared.protocol import create_message, receive_message, send_message


HOST = "127.0.0.1"
PORT = 5051


server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_socket.bind((HOST, PORT))
server_socket.listen(1)

print(f"Protocol server listening on {HOST}:{PORT}")

try:
    connection, address = server_socket.accept()
    print(f"Client connected from {address[0]}:{address[1]}")

    with connection:
        message = receive_message(connection)
        print("Received message:", message)

        if message["type"] == "join":
            player_name = message["data"].get("name", "Unknown player")
            response = create_message(
                "welcome",
                {
                    "player_id": 1,
                    "message": "Welcome " + player_name,
                },
            )
        else:
            response = create_message(
                "error",
                {"message": "The first message must be join."},
            )

        send_message(connection, response)
except (ConnectionError, OSError, ValueError) as error:
    print("Server error:", error)
finally:
    server_socket.close()
