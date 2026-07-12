import socket
import time

from shared.protocol import create_message, send_message


HOST = "127.0.0.1"
PORT = 5052


server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_socket.bind((HOST, PORT))
server_socket.listen(1)

print(f"Threading server listening on {HOST}:{PORT}")

try:
    connection, address = server_socket.accept()
    print(f"Client connected from {address[0]}:{address[1]}")

    with connection:
        score = 0

        while score < 5:
            score += 1
            message = create_message("score_update", {"score": score})
            send_message(connection, message)
            print("Sent score update:", score)
            time.sleep(0.5)

        game_over_message = create_message(
            "game_over",
            {
                "winner": "Player 1",
                "final_score": score,
            },
        )
        send_message(connection, game_over_message)
except (ConnectionError, OSError, ValueError) as error:
    print("Server error:", error)
finally:
    server_socket.close()
