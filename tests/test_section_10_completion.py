import os
import socket
import threading
import time
import unittest


os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

from client.game_client import create_client_state, handle_server_message
from server.game_server import (
    create_server_state,
    handle_client,
    register_client,
    remove_client,
    run_match,
    run_server,
)
from shared.match_settings import is_valid_match_duration
from shared.protocol import create_message, receive_message, send_message


class GameCompletionTest(unittest.TestCase):
    def test_duration_validation_accepts_only_allowed_whole_seconds(self):
        self.assertTrue(is_valid_match_duration(10))
        self.assertTrue(is_valid_match_duration(300))
        self.assertFalse(is_valid_match_duration(9))
        self.assertFalse(is_valid_match_duration(301))
        self.assertFalse(is_valid_match_duration(15.0))
        self.assertFalse(is_valid_match_duration(True))

    def test_first_player_controls_authoritative_duration(self):
        server_state = create_server_state()
        server_one, client_one = socket.socketpair()
        server_two, client_two = socket.socketpair()

        try:
            player_one = register_client(
                server_state,
                server_one,
                ("local", 1),
                "One",
                45,
            )
            player_two = register_client(
                server_state,
                server_two,
                ("local", 2),
                "Two",
                120,
            )

            self.assertEqual(player_one, 1)
            self.assertEqual(player_two, 2)
            self.assertTrue(server_state["clients"][1]["is_host"])
            self.assertFalse(server_state["clients"][2]["is_host"])
            self.assertEqual(server_state["match_duration"], 45)
        finally:
            remove_client(server_state, 1)
            remove_client(server_state, 2)
            client_one.close()
            client_two.close()

    def test_empty_lobby_resets_after_host_disconnects(self):
        server_state = create_server_state()
        first_server, first_client = socket.socketpair()
        second_server, second_client = socket.socketpair()

        try:
            register_client(
                server_state,
                first_server,
                ("local", 1),
                "Old host",
                60,
            )
            remove_client(server_state, 1)

            new_player_id = register_client(
                server_state,
                second_server,
                ("local", 2),
                "New host",
                25,
            )

            self.assertEqual(new_player_id, 1)
            self.assertTrue(server_state["clients"][1]["is_host"])
            self.assertEqual(server_state["scores"], {1: 0})
            self.assertEqual(server_state["match_duration"], 25)
        finally:
            remove_client(server_state, 1)
            first_client.close()
            second_client.close()

    def test_invalid_network_duration_is_rejected_before_registration(self):
        server_state = create_server_state()
        server_socket, client_socket = socket.socketpair()
        client_thread = threading.Thread(
            target=handle_client,
            args=(server_state, server_socket, ("local", 1)),
        )
        client_thread.start()

        try:
            invalid_join = create_message(
                "join",
                {"name": "Player", "duration": 9},
            )
            send_message(client_socket, invalid_join)
            response = receive_message(client_socket)

            self.assertEqual(response["type"], "error")
            self.assertIn("10 and 300", response["data"]["message"])
            self.assertEqual(server_state["clients"], {})
        finally:
            client_socket.close()
            client_thread.join(timeout=1)

        self.assertFalse(client_thread.is_alive())

    def test_welcome_identifies_host_and_selected_duration(self):
        server_state = create_server_state()
        server_socket, client_socket = socket.socketpair()
        client_thread = threading.Thread(
            target=handle_client,
            args=(server_state, server_socket, ("local", 1)),
        )
        client_thread.start()

        try:
            join_message = create_message(
                "join",
                {"name": "Host", "duration": 75},
            )
            send_message(client_socket, join_message)
            welcome = receive_message(client_socket)

            self.assertEqual(welcome["type"], "welcome")
            self.assertTrue(welcome["data"]["is_host"])
            self.assertEqual(welcome["data"]["match_duration"], 75)
        finally:
            server_state["server_stop_event"].set()
            client_socket.close()
            client_thread.join(timeout=1)

        self.assertFalse(client_thread.is_alive())

    def test_timer_finish_uses_highest_score(self):
        server_state = create_server_state(
            match_duration=0.06,
            shape_interval=0.02,
            shape_lifetime=0.02,
        )
        server_one, client_one = socket.socketpair()
        server_two, client_two = socket.socketpair()

        try:
            register_client(server_state, server_one, ("local", 1), "One")
            register_client(server_state, server_two, ("local", 2), "Two")
            server_state["scores"] = {1: 4, 2: 9}

            run_match(server_state)
            client_one.settimeout(1)
            message = receive_message(client_one)

            while message["type"] != "game_over":
                message = receive_message(client_one)

            self.assertEqual(message["data"]["reason"], "timer_finished")
            self.assertEqual(message["data"]["winner"], 2)
            self.assertEqual(message["data"]["scores"], {"1": 4, "2": 9})
        finally:
            remove_client(server_state, 1)
            remove_client(server_state, 2)
            client_one.close()
            client_two.close()

    def test_disconnect_ends_match_and_awards_connected_player(self):
        server_state = create_server_state(
            match_duration=2,
            shape_interval=0.1,
            shape_lifetime=0.1,
        )
        server_one, client_one = socket.socketpair()
        server_two, client_two = socket.socketpair()
        register_client(server_state, server_one, ("local", 1), "One")
        register_client(server_state, server_two, ("local", 2), "Two")
        server_state["match_started"] = True
        match_thread = threading.Thread(target=run_match, args=(server_state,))
        match_thread.start()

        try:
            client_one.settimeout(1)
            start_message = receive_message(client_one)
            self.assertEqual(start_message["type"], "game_start")

            remove_client(server_state, 2)
            message = receive_message(client_one)

            while message["type"] != "game_over":
                message = receive_message(client_one)

            self.assertEqual(message["data"]["reason"], "player_disconnected")
            self.assertEqual(message["data"]["winner"], 1)
        finally:
            match_thread.join(timeout=1)
            remove_client(server_state, 1)
            client_one.close()
            client_two.close()

        self.assertFalse(match_thread.is_alive())

    def test_server_stop_event_wakes_timed_accept_loop(self):
        server_state = create_server_state()
        server_thread = threading.Thread(
            target=run_server,
            args=(server_state, "127.0.0.1", 0),
        )
        server_thread.start()

        time.sleep(0.05)
        server_state["server_stop_event"].set()
        server_thread.join(timeout=1)

        self.assertFalse(server_thread.is_alive())

    def test_client_stores_authoritative_lobby_settings(self):
        client_state = create_client_state()
        welcome_message = {
            "type": "welcome",
            "data": {
                "player_id": 1,
                "waiting_for_players": 1,
                "is_host": True,
                "match_duration": 90,
            },
        }

        handle_server_message(client_state, welcome_message)

        self.assertTrue(client_state["is_host"])
        self.assertEqual(client_state["match_duration"], 90)
        self.assertEqual(client_state["screen_name"], "waiting")
