import socket
import unittest

from game.shapes import (
    HallucinationShape,
    IceShape,
    NormalShape,
    Shape,
    ShieldShape,
    shape_from_message,
)
from server.game_server import (
    broadcast_shape_spawn,
    create_server_state,
    process_click,
    register_client,
    remove_client,
)
from shared.protocol import receive_message


def create_two_player_state():
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


class ShapeHierarchyTest(unittest.TestCase):
    def test_base_shape_is_abstract(self):
        with self.assertRaises(TypeError):
            Shape(1, "Shape", 100, 100, 30, 1, 2)

    def test_normal_shape_score_categories(self):
        negative_shape = NormalShape(1, 100, 100, 30, -2, 2)
        low_shape = NormalShape(2, 100, 100, 30, 2, 2)
        high_shape = NormalShape(3, 100, 100, 30, 6, 2)

        self.assertEqual(negative_shape.get_score_category(), "negative")
        self.assertEqual(low_shape.get_score_category(), "low")
        self.assertEqual(high_shape.get_score_category(), "high")

    def test_special_shapes_return_polymorphic_effects(self):
        shapes = [
            NormalShape(1, 100, 100, 30, 4, 2),
            ShieldShape(2, 100, 100, 30, 2),
            IceShape(3, 100, 100, 30, 2),
        ]

        click_results = []
        for shape in shapes:
            click_results.append(shape.get_click_result())

        self.assertIsNone(click_results[0]["effect"])
        self.assertEqual(click_results[1]["effect"]["type"], "shield")
        self.assertEqual(click_results[2]["effect"]["type"], "ice")

    def test_message_factory_recreates_concrete_shape(self):
        original_shape = ShieldShape(5, 230, 320, 30, 2)

        recreated_shape = shape_from_message(original_shape.get_spawn_data())

        self.assertIsInstance(recreated_shape, ShieldShape)
        self.assertEqual(recreated_shape.get_id(), 5)
        self.assertEqual(recreated_shape.get_position(), (230, 320))

    def test_hallucination_inherits_normal_scoring_and_visibility(self):
        shape = HallucinationShape(4, 200, 200, 30, 3, 2, 1)

        self.assertIsInstance(shape, NormalShape)
        self.assertEqual(shape.get_score_category(), "high")
        self.assertTrue(shape.is_visible_to(1))
        self.assertFalse(shape.is_visible_to(2))

    def test_shields_stack_and_block_negative_points(self):
        server_state = create_two_player_state()
        first_shield = ShieldShape(1, 100, 100, 30, 2)
        second_shield = ShieldShape(2, 100, 100, 30, 2)
        negative_shape = NormalShape(3, 100, 100, 30, -3, 2)
        server_state["active_shapes"] = {
            1: first_shield,
            2: second_shield,
            3: negative_shape,
        }

        process_click(server_state, 1, 1)
        first_end_time = server_state["player_effects"][1]["shield_until"]
        process_click(server_state, 1, 2)
        second_end_time = server_state["player_effects"][1]["shield_until"]
        negative_result = process_click(server_state, 1, 3)

        self.assertGreaterEqual(second_end_time - first_end_time, 4.9)
        self.assertTrue(negative_result["shield_blocked_penalty"])
        self.assertEqual(negative_result["points"], 0)
        self.assertEqual(server_state["scores"][1], 0)

    def test_ice_stacks_on_opponent_and_prevents_clicks(self):
        server_state = create_two_player_state()
        first_ice = IceShape(1, 100, 100, 30, 2)
        second_ice = IceShape(2, 100, 100, 30, 2)
        normal_shape = NormalShape(3, 100, 100, 30, 4, 2)
        server_state["active_shapes"] = {
            1: first_ice,
            2: second_ice,
            3: normal_shape,
        }

        process_click(server_state, 1, 1)
        first_end_time = server_state["player_effects"][2]["frozen_until"]
        process_click(server_state, 1, 2)
        second_end_time = server_state["player_effects"][2]["frozen_until"]
        frozen_result = process_click(server_state, 2, 3)

        self.assertGreaterEqual(second_end_time - first_end_time, 2.9)
        self.assertFalse(frozen_result["accepted"])
        self.assertIn("frozen", frozen_result["error"])
        self.assertIn(3, server_state["active_shapes"])

    def test_hallucination_is_sent_only_to_its_player(self):
        server_state = create_server_state()
        server_one, client_one = socket.socketpair()
        server_two, client_two = socket.socketpair()

        try:
            register_client(server_state, server_one, ("local", 1), "One")
            register_client(server_state, server_two, ("local", 2), "Two")
            shape = HallucinationShape(1, 200, 200, 30, 4, 2, 1)
            server_state["active_shapes"][1] = shape

            broadcast_shape_spawn(server_state, shape)

            first_message = receive_message(client_one)
            client_two.settimeout(0.05)
            self.assertEqual(first_message["type"], "shape_spawn")

            with self.assertRaises(socket.timeout):
                receive_message(client_two)
        finally:
            remove_client(server_state, 1)
            remove_client(server_state, 2)
            client_one.close()
            client_two.close()

    def test_hidden_hallucination_cannot_be_claimed_by_opponent(self):
        server_state = create_two_player_state()
        shape = HallucinationShape(1, 200, 200, 30, 4, 2, 1)
        server_state["active_shapes"][1] = shape

        result = process_click(server_state, 2, 1)

        self.assertFalse(result["accepted"])
        self.assertIn(1, server_state["active_shapes"])
