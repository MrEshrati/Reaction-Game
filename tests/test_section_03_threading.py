import queue
import socket
import threading
import unittest

from shared.protocol import create_message, send_message
from shared.threading_tools import claim_shape, receive_messages


class ThreadingToolsTest(unittest.TestCase):
    def test_network_thread_passes_messages_to_queue(self):
        sender, receiver = socket.socketpair()
        incoming_messages = queue.Queue()
        stop_event = threading.Event()
        network_thread = threading.Thread(
            target=receive_messages,
            args=(receiver, incoming_messages, stop_event),
        )

        try:
            network_thread.start()
            score_message = create_message("score_update", {"score": 3})
            game_over_message = create_message("game_over", {"winner": 1})

            send_message(sender, score_message)
            send_message(sender, game_over_message)
            network_thread.join(timeout=2)

            self.assertFalse(network_thread.is_alive())
            self.assertTrue(stop_event.is_set())
            self.assertEqual(incoming_messages.get_nowait(), score_message)
            self.assertEqual(incoming_messages.get_nowait(), game_over_message)
        finally:
            sender.close()
            receiver.close()

    def test_socket_close_wakes_network_thread(self):
        sender, receiver = socket.socketpair()
        incoming_messages = queue.Queue()
        stop_event = threading.Event()
        network_thread = threading.Thread(
            target=receive_messages,
            args=(receiver, incoming_messages, stop_event),
        )

        try:
            network_thread.start()
            stop_event.set()
            receiver.close()
            network_thread.join(timeout=2)

            self.assertFalse(network_thread.is_alive())
            self.assertTrue(incoming_messages.empty())
        finally:
            sender.close()
            receiver.close()

    def test_lock_allows_only_one_player_to_claim_shape(self):
        shared_shape = {"claimed_by": None}
        state_lock = threading.Lock()
        start_event = threading.Event()
        results = queue.Queue()
        player_threads = []

        def player_click(player_id):
            start_event.wait()
            result = claim_shape(shared_shape, player_id, state_lock)
            results.put(result)

        player_id = 1
        while player_id <= 20:
            player_thread = threading.Thread(
                target=player_click,
                args=(player_id,),
            )
            player_threads.append(player_thread)
            player_thread.start()
            player_id += 1

        start_event.set()

        for player_thread in player_threads:
            player_thread.join(timeout=2)

        successful_claims = 0
        while not results.empty():
            if results.get():
                successful_claims += 1

        self.assertEqual(successful_claims, 1)
        self.assertIsNotNone(shared_shape["claimed_by"])
