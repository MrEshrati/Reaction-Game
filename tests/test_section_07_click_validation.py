import os
import queue
import socket
import threading
import unittest


os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

from client.game_client import create_client_state, handle_server_message
from game.shapes import NormalShape
from server.game_server import (
    create_server_state,
    handle_client_message,
    process_click,
    register_client,
    remove_client,
)
from shared.protocol import create_message, receive_message


def create_running_server_state():
    server_state = create_server_state()
    server_state["clients"] = {
        1: {"player_id": 1},
        2: {"player_id": 2},
    }
    server_state["scores"] = {1: 0, 2: 0}
    server_state["player_effects"] = {
        1: {"shield_until": 0, "frozen_until": 0},
        2: {"shield_until": 0, "frozen_until": 0},
    }
    server_state["match_running"] = True
    return server_state


class ClickValidationTest(unittest.TestCase):
    def test_circle_edge_counts_as_a_hit(self):
        shape = NormalShape(1, 200, 200, 30, 3, 2)

        self.assertTrue(shape.contains_point(230, 200))
        self.assertFalse(shape.contains_point(231, 200))

    def test_server_rejects_a_click_that_misses_the_shape(self):
        server_state = create_running_server_state()
        shape = NormalShape(1, 200, 200, 30, 4, 2)
        server_state["active_shapes"][1] = shape

        result = process_click(server_state, 1, 1, (400, 400))

        self.assertFalse(result["accepted"])
        self.assertIn("did not hit", result["error"])
        self.assertIn(1, server_state["active_shapes"])
        self.assertEqual(server_state["scores"][1], 0)

    def test_server_rejects_coordinates_outside_the_window(self):
        server_state = create_running_server_state()
        shape = NormalShape(1, 20, 200, 30, 4, 2)
        server_state["active_shapes"][1] = shape

        result = process_click(server_state, 1, 1, (-1, 200))

        self.assertFalse(result["accepted"])
        self.assertIn("outside", result["error"])
        self.assertIn(1, server_state["active_shapes"])

    def test_boolean_coordinates_are_not_accepted_as_integers(self):
        server_state = create_running_server_state()
        shape = NormalShape(1, 200, 200, 30, 4, 2)
        server_state["active_shapes"][1] = shape

        result = process_click(server_state, 1, 1, (True, 200))

        self.assertFalse(result["accepted"])
        self.assertIn("integers", result["error"])
        self.assertIn(1, server_state["active_shapes"])

    def test_network_rejection_identifies_the_pending_shape(self):
        server_state = create_server_state()
        server_socket, client_socket = socket.socketpair()

        try:
            player_id = register_client(
                server_state,
                server_socket,
                ("local", 1),
                "Player One",
            )
            server_state["match_running"] = True
            shape = NormalShape(8, 200, 200, 30, 5, 2)
            server_state["active_shapes"][8] = shape
            client = server_state["clients"][player_id]
            click_message = create_message(
                "click",
                {"shape_id": 8, "x": 400, "y": 400},
            )

            handle_client_message(server_state, client, click_message)
            response = receive_message(client_socket)

            self.assertEqual(response["type"], "error")
            self.assertEqual(response["data"]["shape_id"], 8)
            self.assertIn(8, server_state["active_shapes"])
        finally:
            remove_client(server_state, 1)
            client_socket.close()

    def test_network_message_requires_both_coordinates(self):
        server_state = create_server_state()
        server_socket, client_socket = socket.socketpair()

        try:
            player_id = register_client(
                server_state,
                server_socket,
                ("local", 1),
                "Player One",
            )
            server_state["match_running"] = True
            shape = NormalShape(8, 200, 200, 30, 5, 2)
            server_state["active_shapes"][8] = shape
            client = server_state["clients"][player_id]
            incomplete_click = create_message(
                "click",
                {"shape_id": 8, "x": 200},
            )

            handle_client_message(server_state, client, incomplete_click)
            response = receive_message(client_socket)

            self.assertEqual(response["type"], "error")
            self.assertIn("coordinates", response["data"]["message"])
            self.assertIn(8, server_state["active_shapes"])
        finally:
            remove_client(server_state, 1)
            client_socket.close()

    def test_client_releases_a_rejected_pending_click(self):
        client_state = create_client_state()
        client_state["pending_clicks"] = [8]
        error_message = create_message(
            "error",
            {
                "message": "The click did not hit the shape.",
                "shape_id": 8,
            },
        )

        handle_server_message(client_state, error_message)

        self.assertNotIn(8, client_state["pending_clicks"])
        self.assertIn("did not hit", client_state["status_message"])

    def test_repeated_simultaneous_clicks_have_one_winner_each(self):
        server_state = create_running_server_state()
        round_count = 20
        shape_id = 1

        while shape_id <= round_count:
            shape = NormalShape(shape_id, 250, 250, 30, 3, 2)
            server_state["active_shapes"][shape_id] = shape
            start_event = threading.Event()
            results = queue.Queue()

            def click_shape(player_id):
                start_event.wait()
                result = process_click(
                    server_state,
                    player_id,
                    shape_id,
                    (250, 250),
                )
                results.put(result)

            player_one_thread = threading.Thread(target=click_shape, args=(1,))
            player_two_thread = threading.Thread(target=click_shape, args=(2,))
            player_one_thread.start()
            player_two_thread.start()
            start_event.set()
            player_one_thread.join(timeout=2)
            player_two_thread.join(timeout=2)

            accepted_count = 0
            while not results.empty():
                if results.get()["accepted"]:
                    accepted_count += 1

            self.assertEqual(accepted_count, 1)
            self.assertNotIn(shape_id, server_state["active_shapes"])
            shape_id += 1

        total_score = server_state["scores"][1] + server_state["scores"][2]
        self.assertEqual(total_score, round_count * 3)
