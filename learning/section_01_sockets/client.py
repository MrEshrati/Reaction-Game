"""A minimal TCP client for the Section 1 server."""

import socket

# support running the client as a module or directly from its folder
try:
    from learning.section_01_sockets.server import BUFFER_SIZE, HOST, PORT
except ModuleNotFoundError:
    from server import BUFFER_SIZE, HOST, PORT


def exchange_message(
    message: str,
    host: str = HOST,
    port: int = PORT,
) -> str:
    """Connect to the server, send one message, and return its response."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
        client_socket.connect((host, port))
        client_socket.sendall(message.encode("utf-8"))

        response_bytes = client_socket.recv(BUFFER_SIZE)
        return response_bytes.decode("utf-8")


def run_client() -> None:
    """Read a terminal message and exchange it with the example server."""

    message = input("Message for the server: ")
    response = exchange_message(message)
    print(response)


if __name__ == "__main__":
    run_client()
