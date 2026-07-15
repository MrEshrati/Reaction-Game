import os
import time
import unittest


os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame
from client.game_client import (
    create_client_state,
    find_clicked_shape,
    get_remaining_seconds,
    handle_server_message,
    initialize_pygame,
    remove_expired_visual_shapes,
    send_shape_click,
)
from shared.protocol import receive_message


class RecordingConnection:
    def __init__(self):
        self.sent_data = b""

    def sendall(self, data):
        self.sent_data += data

    def recv(self, byte_count):
        returned_data = self.sent_data[:byte_count]
        self.sent_data = self.sent_data[byte_count:]
        return returned_data


class BasicPygameClientTest(unittest.TestCase):
    def test_required_pygame_modules_can_poll_events(self):
        pygame.quit()
        initialize_pygame()
        pygame.display.set_mode((100, 100))
        pygame.event.clear()
        test_event = pygame.event.Event(pygame.USEREVENT, {"value": 1})
        pygame.event.post(test_event)

        events = pygame.event.get()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].value, 1)
        pygame.quit()

    def test_welcome_and_game_start_change_screens(self):
        client_state = create_client_state()
        welcome_message = {
            "type": "welcome",
            "data": {
                "player_id": 2,
                "waiting_for_players": 1,
            },
        }
        game_start_message = {
            "type": "game_start",
            "data": {
                "duration": 10,
                "scores": {"1": 0, "2": 0},
            },
        }

        handle_server_message(client_state, welcome_message)
        self.assertEqual(client_state["screen_name"], "waiting")
        self.assertEqual(client_state["player_id"], 2)

        handle_server_message(client_state, game_start_message)
        self.assertEqual(client_state["screen_name"], "game")
        self.assertGreater(client_state["match_end_time"], time.monotonic())

    def test_shape_can_be_found_and_removed(self):
        client_state = create_client_state()
        shape_message = {
            "type": "shape_spawn",
            "data": {
                "shape_id": 7,
                "shape_type": "normal",
                "x": 300,
                "y": 250,
                "radius": 30,
                "points": 4,
                "lifetime": 2,
            },
        }

        handle_server_message(client_state, shape_message)
        self.assertEqual(find_clicked_shape(client_state, (300, 250)), 7)
        self.assertIsNone(find_clicked_shape(client_state, (400, 250)))

        remove_message = {
            "type": "shape_remove",
            "data": {
                "shape_id": 7,
                "reason": "expired",
                "claimed_by": None,
            },
        }
        handle_server_message(client_state, remove_message)
        self.assertNotIn(7, client_state["shapes"])

    def test_click_sends_one_request_and_does_not_change_score(self):
        client_state = create_client_state()
        connection = RecordingConnection()
        client_state["connection"] = connection
        client_state["scores"] = {"1": 0, "2": 0}
        shape_message = {
            "type": "shape_spawn",
            "data": {
                "shape_id": 11,
                "shape_type": "normal",
                "x": 100,
                "y": 100,
                "radius": 25,
                "points": 6,
                "lifetime": 2,
            },
        }
        handle_server_message(client_state, shape_message)

        first_click = send_shape_click(client_state, (100, 100))
        second_click = send_shape_click(client_state, (100, 100))
        sent_message = receive_message(connection)

        self.assertTrue(first_click)
        self.assertFalse(second_click)
        self.assertEqual(sent_message["type"], "click")
        self.assertEqual(sent_message["data"]["shape_id"], 11)
        self.assertEqual(client_state["scores"], {"1": 0, "2": 0})

    def test_expired_visual_shape_is_removed(self):
        client_state = create_client_state()
        shape_message = {
            "type": "shape_spawn",
            "data": {
                "shape_id": 3,
                "shape_type": "normal",
                "x": 200,
                "y": 200,
                "radius": 25,
                "points": -2,
                "lifetime": 1,
            },
        }
        handle_server_message(client_state, shape_message)
        expires_at = client_state["shapes"][3].get_expires_at()

        remove_expired_visual_shapes(client_state, expires_at)

        self.assertNotIn(3, client_state["shapes"])

    def test_score_and_final_result_come_from_server(self):
        client_state = create_client_state()
        client_state["player_id"] = 1
        score_message = {
            "type": "score_update",
            "data": {"scores": {"1": 8, "2": 5}},
        }
        game_over_message = {
            "type": "game_over",
            "data": {
                "winner": 1,
                "scores": {"1": 8, "2": 5},
                "reason": "timer_finished",
            },
        }

        handle_server_message(client_state, score_message)
        handle_server_message(client_state, game_over_message)

        self.assertEqual(client_state["scores"]["1"], 8)
        self.assertEqual(client_state["winner"], 1)
        self.assertEqual(client_state["screen_name"], "final")

    def test_displayed_timer_never_becomes_negative(self):
        client_state = create_client_state()
        client_state["match_end_time"] = 50

        self.assertEqual(get_remaining_seconds(client_state, 40), 10)
        self.assertEqual(get_remaining_seconds(client_state, 60), 0)
