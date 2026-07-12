"""A minimal TCP server that handles one client and then exits.

This example is intentionally small. It demonstrates the lifecycle of a TCP
server before the game adds message framing, multiple clients, and threads.
"""

import socket


HOST = "127.0.0.1"
PORT = 5050
BUFFER_SIZE = 1024


def create_server_socket(host: str = HOST, port: int = PORT) -> socket.socket:
    """Create a listening TCP socket.

    Passing port 0 asks the operating system to choose an available port. That
    option is useful in automated tests.
    """

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(1)
    return server_socket


def handle_one_client(server_socket: socket.socket) -> None:
    """Accept one connection, receive one message, and send one response."""

    connection, address = server_socket.accept()
    print(f"Client connected from {address[0]}:{address[1]}")

    with connection:
        received_bytes = connection.recv(BUFFER_SIZE)
        if not received_bytes:
            print("The client disconnected without sending a message.")
            return

        message = received_bytes.decode("utf-8")
        print(f"Client said: {message}")

        response = f"Server received: {message}"
        connection.sendall(response.encode("utf-8"))


def run_server(host: str = HOST, port: int = PORT) -> None:
    """Run the example server and close it after the first client."""

    with create_server_socket(host, port) as server_socket:
        actual_host, actual_port = server_socket.getsockname()
        print(f"Server listening on {actual_host}:{actual_port}")
        handle_one_client(server_socket)


if __name__ == "__main__":
    run_server()

