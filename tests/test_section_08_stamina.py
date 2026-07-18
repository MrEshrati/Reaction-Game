import os
import socket
import unittest
from unittest.mock import patch


os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

from client.game_client import (
    create_client_state,
    get_stamina_darkness,
    handle_server_message,
    send_shape_click,
)
from game.player import PlayerStamina, PlayerStress
from game.shapes import HallucinationShape, NormalShape, ShieldShape
from server.game_server import (
    broadcast_shape_spawn,
    create_server_state,
    process_click,
    register_client,
    remove_client,
)
from shared.protocol import receive_message


def create_running_stamina_state(initial_stamina=100):
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
        1: PlayerStress(),
        2: PlayerStress(),
    }
    server_state["match_running"] = True
    return server_state


class StaminaSystemTest(unittest.TestCase):
    def test_click_costs_five_stamina(self):
        stamina = PlayerStamina(current_time=0)

        stamina.spend_for_click(current_time=0)

        self.assertEqual(stamina.get_value(0), 95)

    def test_ten_stamina_recovers_every_two_inactive_seconds(self):
        stamina = PlayerStamina(50, current_time=0)

        stamina.update(1.9)
        value_before_interval = stamina.get_value(1.9)
        stamina.update(2)
        value_after_one_interval = stamina.get_value(2)
        stamina.update(6)
        value_after_three_intervals = stamina.get_value(6)

        self.assertEqual(value_before_interval, 50)
        self.assertEqual(value_after_one_interval, 60)
        self.assertEqual(value_after_three_intervals, 80)

    def test_a_new_click_restarts_the_recovery_timer(self):
        stamina = PlayerStamina(50, current_time=0)
        stamina.spend_for_click(current_time=0)
        stamina.update(1.9)
        stamina.spend_for_click(current_time=1.9)

        self.assertEqual(stamina.get_value(3.8), 40)
        self.assertEqual(stamina.get_value(3.9), 50)

    def test_frozen_time_does_not_recover_stamina(self):
        stamina = PlayerStamina(50, current_time=0)

        frozen_value = stamina.get_value(5, frozen_until=5)
        recovered_value = stamina.get_value(7, frozen_until=5)

        self.assertEqual(frozen_value, 50)
        self.assertEqual(recovered_value, 60)

    def test_high_stamina_doubles_rewards_and_halves_penalties(self):
        server_state = create_running_stamina_state()
        positive_shape = NormalShape(1, 100, 100, 30, 4, 2)
        negative_shape = NormalShape(2, 200, 200, 30, -3, 2)
        server_state["active_shapes"] = {
            1: positive_shape,
            2: negative_shape,
        }

        positive_result = process_click(server_state, 1, 1, (100, 100))
        negative_result = process_click(server_state, 1, 2, (200, 200))

        self.assertEqual(positive_result["points"], 8)
        self.assertEqual(negative_result["points"], -1.5)
        self.assertEqual(server_state["scores"][1], 6.5)
        self.assertEqual(server_state["player_stamina"][1].get_value(), 90)

    def test_shield_does_not_use_stamina(self):
        server_state = create_running_stamina_state(60)
        normal_shape = NormalShape(1, 100, 100, 30, 2, 2)
        shield_shape = ShieldShape(2, 200, 200, 30, 2)
        server_state["active_shapes"] = {
            1: normal_shape,
            2: shield_shape,
        }

        process_click(server_state, 1, 1, (100, 100))
        stamina_before_shield = server_state["player_stamina"][1].get_value()
        process_click(server_state, 1, 2, (200, 200))
        stamina_after_shield = server_state["player_stamina"][1].get_value()

        self.assertEqual(stamina_before_shield, 55)
        self.assertEqual(stamina_after_shield, 55)

    def test_hallucination_uses_stamina_but_awards_no_points(self):
        server_state = create_running_stamina_state(60)
        shape = HallucinationShape(1, 200, 200, 30, 6, 2, 1)
        server_state["active_shapes"][1] = shape

        result = process_click(server_state, 1, 1, (200, 200))

        self.assertTrue(result["accepted"])
        self.assertEqual(result["points"], 0)
        self.assertEqual(server_state["scores"][1], 0)
        self.assertEqual(server_state["player_stamina"][1].get_value(), 55)

    def test_depleted_player_cannot_claim_a_shape(self):
        server_state = create_running_stamina_state(10)
        shape = NormalShape(1, 200, 200, 30, 4, 2)
        server_state["active_shapes"][1] = shape

        result = process_click(server_state, 1, 1, (200, 200))

        self.assertFalse(result["accepted"])
        self.assertIn("stamina", result["error"])
        self.assertIn(1, server_state["active_shapes"])
        self.assertEqual(server_state["scores"][1], 0)

    def test_low_stamina_can_hide_a_shape_from_one_player(self):
        server_state = create_server_state()
        server_one, client_one = socket.socketpair()
        server_two, client_two = socket.socketpair()

        try:
            register_client(server_state, server_one, ("local", 1), "One")
            register_client(server_state, server_two, ("local", 2), "Two")
            server_state["player_stamina"][1] = PlayerStamina(20)
            server_state["player_stamina"][2] = PlayerStamina(60)
            server_state["match_running"] = True
            shape = NormalShape(1, 200, 200, 30, 4, 2)
            server_state["active_shapes"][1] = shape

            with patch("server.game_server.random.random", return_value=0):
                broadcast_shape_spawn(server_state, shape)

            client_one.settimeout(0.05)
            normal_message = receive_message(client_two)
            hidden_click = process_click(server_state, 1, 1, (200, 200))

            with self.assertRaises(socket.timeout):
                receive_message(client_one)

            self.assertEqual(normal_message["type"], "shape_spawn")
            self.assertFalse(hidden_click["accepted"])
            self.assertIn(1, server_state["active_shapes"])
        finally:
            remove_client(server_state, 1)
            remove_client(server_state, 2)
            client_one.close()
            client_two.close()

    def test_client_blocks_clicks_when_stamina_is_depleted(self):
        client_state = create_client_state()
        client_state["player_id"] = 1
        player_state_message = {
            "type": "player_state",
            "data": {
                "players": {
                    "1": {
                        "shield_seconds": 0,
                        "frozen_seconds": 0,
                        "stamina": 10,
                    }
                }
            },
        }
        handle_server_message(client_state, player_state_message)

        click_sent = send_shape_click(client_state, (200, 200))

        self.assertFalse(click_sent)
        self.assertIn("depleted", client_state["status_message"])

    def test_darkness_applies_only_in_the_forty_to_sixty_band(self):
        self.assertEqual(get_stamina_darkness(60), 0)
        self.assertEqual(get_stamina_darkness(50), 70)
        self.assertEqual(get_stamina_darkness(40), 140)
        self.assertEqual(get_stamina_darkness(30), 0)
