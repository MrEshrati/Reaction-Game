import socket

from shared.protocol import create_message, receive_message, send_message


HOST = "127.0.0.1"
PORT = 5051


player_name = input("Your player name: ")
join_message = create_message("join", {"name": player_name})

try:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
        client_socket.connect((HOST, PORT))
        send_message(client_socket, join_message)

        response = receive_message(client_socket)
        print("Server response:", response)
except (ConnectionError, OSError, ValueError) as error:
    print("Client error:", error)
