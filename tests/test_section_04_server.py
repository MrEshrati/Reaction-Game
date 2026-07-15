import queue
import socket
import threading
import time
import unittest

from server.game_server import (
    create_random_shape,
    create_server_state,
    process_click,
    register_client,
    remove_client,
    run_match,
)
from shared.protocol import receive_message


class AuthoritativeServerTest(unittest.TestCase):
    def test_server_accepts_only_two_players(self):
        server_state = create_server_state()
        server_sockets = []
        client_sockets = []

        try:
            player_number = 1
            while player_number <= 3:
                server_socket, client_socket = socket.socketpair()
                server_sockets.append(server_socket)
                client_sockets.append(client_socket)
                player_id = register_client(
                    server_state,
                    server_socket,
                    ("local", player_number),
                    "Player " + str(player_number),
                )

                if player_number <= 2:
                    self.assertEqual(player_id, player_number)
                else:
                    self.assertIsNone(player_id)

                player_number += 1
        finally:
            remove_client(server_state, 1)
            remove_client(server_state, 2)

            for server_socket in server_sockets:
                server_socket.close()

            for client_socket in client_sockets:
                client_socket.close()

    def test_two_simultaneous_clicks_have_one_winner(self):
        server_state = create_server_state()
        server_state["clients"] = {
            1: {"player_id": 1},
            2: {"player_id": 2},
        }
        server_state["scores"] = {1: 0, 2: 0}
        server_state["match_running"] = True
        shape = create_random_shape(server_state)
        shape_id = shape["shape_id"]
        start_event = threading.Event()
        results = queue.Queue()

        def click_shape(player_id):
            start_event.wait()
            result = process_click(server_state, player_id, shape_id)
            results.put(result)

        player_one_thread = threading.Thread(target=click_shape, args=(1,))
        player_two_thread = threading.Thread(target=click_shape, args=(2,))
        player_one_thread.start()
        player_two_thread.start()
        start_event.set()
        player_one_thread.join(timeout=2)
        player_two_thread.join(timeout=2)

        accepted_clicks = 0
        while not results.empty():
            if results.get()["accepted"]:
                accepted_clicks += 1

        total_score = server_state["scores"][1]
        total_score += server_state["scores"][2]

        self.assertEqual(accepted_clicks, 1)
        self.assertEqual(total_score, shape["points"])
        self.assertNotIn(shape_id, server_state["active_shapes"])

    def test_match_broadcasts_start_shapes_and_game_over(self):
        server_state = create_server_state(
            match_duration=0.12,
            shape_interval=0.03,
            shape_lifetime=0.05,
        )
        server_one, client_one = socket.socketpair()
        server_two, client_two = socket.socketpair()

        try:
            register_client(server_state, server_one, ("local", 1), "One")
            register_client(server_state, server_two, ("local", 2), "Two")
            server_state["match_started"] = True

            run_match(server_state)

            for client_socket in [client_one, client_two]:
                client_socket.settimeout(1)
                message_types = []

                while "game_over" not in message_types:
                    message = receive_message(client_socket)
                    message_types.append(message["type"])

                self.assertEqual(message_types[0], "game_start")
                self.assertIn("shape_spawn", message_types)
                self.assertEqual(message_types[-1], "game_over")
        finally:
            remove_client(server_state, 1)
            remove_client(server_state, 2)
            client_one.close()
            client_two.close()

    def test_expired_shape_click_is_rejected(self):
        server_state = create_server_state()
        server_state["clients"] = {1: {"player_id": 1}}
        server_state["scores"] = {1: 0}
        server_state["match_running"] = True
        shape = create_random_shape(server_state)
        server_state["active_shapes"][shape["shape_id"]]["expires_at"] = 0

        result = process_click(server_state, 1, shape["shape_id"])

        self.assertFalse(result["accepted"])
        self.assertEqual(server_state["scores"][1], 0)
        self.assertNotIn(shape["shape_id"], server_state["active_shapes"])
