import os
import socket
import unittest
from unittest.mock import patch


os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame
from client.game_client import (
    calculate_mouse_movement,
    create_client_state,
    handle_pygame_event,
    handle_server_message,
    send_shape_click,
    update_virtual_mouse,
)
from game.player import PlayerStamina, PlayerStress
from game.shapes import HallucinationShape, NormalShape, ShieldShape
from server.game_server import (
    create_server_state,
    process_click,
    process_empty_click,
    register_client,
    remove_client,
    spawn_due_hallucinations,
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


def create_running_stress_state(initial_stress=0, initial_stamina=60):
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
    server_state["player_stamina"] = {
        1: PlayerStamina(initial_stamina),
        2: PlayerStamina(initial_stamina),
    }
    server_state["player_stress"] = {
        1: PlayerStress(initial_stress),
        2: PlayerStress(initial_stress),
    }
    server_state["match_running"] = True
    return server_state


class StressSystemTest(unittest.TestCase):
    def test_stress_stays_between_zero_and_one_hundred(self):
        stress = PlayerStress(95)

        stress.change(30)
        maximum_value = stress.get_value()
        stress.change(-150)
        minimum_value = stress.get_value()

        self.assertEqual(maximum_value, 100)
        self.assertEqual(minimum_value, 0)

    def test_stress_levels_use_the_strongest_speed_reduction(self):
        calm_stress = PlayerStress(10)
        slowed_stress = PlayerStress(20)
        jumping_stress = PlayerStress(40)
        hallucinating_stress = PlayerStress(60)
        severe_stress = PlayerStress(75)

        self.assertEqual(calm_stress.get_mouse_speed_multiplier(), 1)
        self.assertEqual(slowed_stress.get_mouse_speed_multiplier(), 0.85)
        self.assertEqual(jumping_stress.get_mouse_speed_multiplier(), 0.85)
        self.assertEqual(hallucinating_stress.get_mouse_speed_multiplier(), 0.6)
        self.assertEqual(hallucinating_stress.get_hallucination_interval(), 3)
        self.assertEqual(severe_stress.get_hallucination_interval(), 1.5)

    def test_high_stamina_reduces_stress_every_two_seconds(self):
        stress = PlayerStress(40, current_time=0)

        stress.update(100, current_time=1.9)
        value_before_interval = stress.get_value()
        stress.update(100, current_time=2)
        value_after_interval = stress.get_value()

        self.assertEqual(value_before_interval, 40)
        self.assertEqual(value_after_interval, 30)

    def test_low_stamina_does_not_reduce_stress(self):
        stress = PlayerStress(40, current_time=0)

        stress.update(80, current_time=10)

        self.assertEqual(stress.get_value(), 40)

    def test_frozen_time_does_not_reduce_stress(self):
        stress = PlayerStress(40, current_time=0)

        stress.update(100, current_time=5, frozen_until=5)
        frozen_value = stress.get_value()
        stress.update(100, current_time=7, frozen_until=5)
        recovered_value = stress.get_value()

        self.assertEqual(frozen_value, 40)
        self.assertEqual(recovered_value, 30)

    def test_shape_categories_change_stress(self):
        server_state = create_running_stress_state()
        negative_shape = NormalShape(1, 100, 100, 30, -3, 2)
        low_shape = NormalShape(2, 200, 200, 30, 2, 2)
        high_shape = NormalShape(3, 300, 300, 30, 6, 2)
        server_state["active_shapes"] = {
            1: negative_shape,
            2: low_shape,
            3: high_shape,
        }

        process_click(server_state, 1, 1, (100, 100))
        negative_stress = server_state["player_stress"][1].get_value()
        process_click(server_state, 1, 2, (200, 200))
        low_stress = server_state["player_stress"][1].get_value()
        process_click(server_state, 1, 3, (300, 300))
        high_stress = server_state["player_stress"][1].get_value()

        self.assertEqual(negative_stress, 30)
        self.assertEqual(low_stress, 40)
        self.assertEqual(high_stress, 35)

    def test_shield_changes_neither_stamina_nor_stress(self):
        server_state = create_running_stress_state(25, 60)
        shape = ShieldShape(1, 200, 200, 30, 2)
        server_state["active_shapes"][1] = shape

        process_click(server_state, 1, 1, (200, 200))

        self.assertEqual(server_state["player_stamina"][1].get_value(), 60)
        self.assertEqual(server_state["player_stress"][1].get_value(), 25)

    def test_hallucination_uses_hidden_category_but_awards_no_score(self):
        server_state = create_running_stress_state(0, 60)
        shape = HallucinationShape(1, 200, 200, 30, -3, 2, 1)
        server_state["active_shapes"][1] = shape

        result = process_click(server_state, 1, 1, (200, 200))

        self.assertEqual(result["points"], 0)
        self.assertEqual(server_state["scores"][1], 0)
        self.assertEqual(server_state["player_stress"][1].get_value(), 30)
        self.assertEqual(server_state["player_stamina"][1].get_value(), 55)

    def test_empty_click_costs_stamina_and_adds_five_stress(self):
        server_state = create_running_stress_state(10, 60)

        result = process_empty_click(server_state, 1, (700, 500))

        self.assertTrue(result["accepted"])
        self.assertEqual(server_state["player_stamina"][1].get_value(), 55)
        self.assertEqual(server_state["player_stress"][1].get_value(), 15)
        self.assertEqual(server_state["scores"][1], 0)

    def test_empty_click_cannot_be_used_on_a_visible_shape(self):
        server_state = create_running_stress_state(0, 60)
        shape = NormalShape(1, 200, 200, 30, 4, 2)
        server_state["active_shapes"][1] = shape

        result = process_empty_click(server_state, 1, (200, 200))

        self.assertFalse(result["accepted"])
        self.assertEqual(server_state["player_stamina"][1].get_value(), 60)
        self.assertEqual(server_state["player_stress"][1].get_value(), 0)

    def test_client_sends_empty_click_to_the_server(self):
        client_state = create_client_state()
        connection = RecordingConnection()
        client_state["connection"] = connection
        client_state["player_id"] = 1
        client_state["player_states"] = {
            "1": {
                "shield_until": 0,
                "frozen_until": 0,
                "stamina": 60,
                "stress": 0,
            }
        }

        click_sent = send_shape_click(client_state, (700, 500))
        sent_message = receive_message(connection)

        self.assertTrue(click_sent)
        self.assertIsNone(sent_message["data"]["shape_id"])
        self.assertEqual(sent_message["data"]["x"], 700)
        self.assertEqual(sent_message["data"]["y"], 500)

    def test_pygame_click_uses_virtual_cursor_position(self):
        client_state = create_client_state()
        connection = RecordingConnection()
        client_state["connection"] = connection
        client_state["player_id"] = 1
        client_state["screen_name"] = "game"
        client_state["virtual_mouse_position"] = [700, 500]
        client_state["player_states"] = {
            "1": {
                "shield_until": 0,
                "frozen_until": 0,
                "stamina": 60,
                "stress": 0,
            }
        }
        mouse_event = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"button": 1, "pos": (10, 10)},
        )

        handle_pygame_event(mouse_event, client_state)
        sent_message = receive_message(connection)

        self.assertEqual(sent_message["data"]["x"], 700)
        self.assertEqual(sent_message["data"]["y"], 500)

    def test_calibrated_mouse_movement_uses_stress_multiplier(self):
        self.assertEqual(calculate_mouse_movement((10, -10), 1, 0), (10, -10))
        self.assertEqual(
            calculate_mouse_movement((10, -10), 1, 20),
            (8.5, -8.5),
        )
        self.assertEqual(calculate_mouse_movement((10, -10), 1, 55), (6, -6))

    def test_saved_mouse_baseline_ignores_a_later_speed_change(self):
        client_state = create_client_state()
        client_state["screen_name"] = "game"
        client_state["player_id"] = 1
        client_state["player_states"] = {
            "1": {
                "shield_until": 0,
                "frozen_until": 0,
                "stamina": 100,
                "stress": 0,
            }
        }
        client_state["virtual_mouse_position"] = [100, 100]
        client_state["last_system_mouse_position"] = (0, 0)
        client_state["mouse_calibration_end_time"] = 5

        calibrated_position = update_virtual_mouse(
            client_state,
            current_time=1,
            raw_movement=(10, 0),
            system_position=(20, 0),
        )
        protected_position = update_virtual_mouse(
            client_state,
            current_time=10,
            raw_movement=(10, 0),
            system_position=(120, 0),
        )

        self.assertEqual(client_state["mouse_reference_ratio"], 2)
        self.assertEqual(calibrated_position, (120, 100))
        self.assertEqual(protected_position, (140, 100))

    def test_high_stress_creates_mouse_jumps_and_a_trail(self):
        client_state = create_client_state()
        client_state["screen_name"] = "game"
        client_state["player_id"] = 1
        client_state["player_states"] = {
            "1": {
                "shield_until": 0,
                "frozen_until": 0,
                "stamina": 100,
                "stress": 60,
            }
        }
        client_state["mouse_calibration_end_time"] = 0
        client_state["last_system_mouse_position"] = (0, 0)
        client_state["next_mouse_jump_time"] = 0

        with patch("client.game_client.random.randint", side_effect=[400, 300]):
            mouse_position = update_virtual_mouse(
                client_state,
                current_time=10,
                raw_movement=(0, 0),
                system_position=(0, 0),
            )

        self.assertEqual(mouse_position, (400, 300))
        self.assertEqual(client_state["mouse_trail"], [(400, 300)])

    def test_hallucination_spawn_is_private_to_stressed_player(self):
        server_state = create_server_state()
        server_one, client_one = socket.socketpair()
        server_two, client_two = socket.socketpair()

        try:
            register_client(server_state, server_one, ("local", 1), "One")
            register_client(server_state, server_two, ("local", 2), "Two")
            server_state["player_stress"][1] = PlayerStress(60)
            server_state["next_hallucination_times"][1] = 0

            new_shapes = spawn_due_hallucinations(server_state)

            hallucination_message = receive_message(client_one)
            client_two.settimeout(0.05)

            with self.assertRaises(socket.timeout):
                receive_message(client_two)

            self.assertEqual(len(new_shapes), 1)
            self.assertEqual(
                hallucination_message["data"]["shape_type"],
                "hallucination",
            )
        finally:
            remove_client(server_state, 1)
            remove_client(server_state, 2)
            client_one.close()
            client_two.close()
