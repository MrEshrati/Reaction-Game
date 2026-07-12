"""Integration test for the first TCP client/server exercise."""

import threading
import unittest

from learning.section_01_sockets.client import exchange_message
from learning.section_01_sockets.server import (
    HOST,
    create_server_socket,
    handle_one_client,
)


class SocketFundamentalsTest(unittest.TestCase):
    def test_client_and_server_exchange_a_message(self) -> None:
        # Port 0 lets the operating system choose an unused test port.
        with create_server_socket(HOST, 0) as server_socket:
            _, port = server_socket.getsockname()
            server_thread = threading.Thread(
                target=handle_one_client,
                args=(server_socket,),
            )
            server_thread.start()

            response = exchange_message("hello sockets", HOST, port)

            server_thread.join(timeout=2)
            self.assertFalse(server_thread.is_alive())
            self.assertEqual(response, "Server received: hello sockets")


if __name__ == "__main__":
    unittest.main()
