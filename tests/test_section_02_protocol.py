import socket
import struct
import unittest

from shared.protocol import (
    HEADER_FORMAT,
    MAX_MESSAGE_SIZE,
    create_message,
    encode_message,
    receive_message,
    send_message,
)


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.sender, self.receiver = socket.socketpair()

    def tearDown(self):
        self.sender.close()
        self.receiver.close()

    def test_message_can_be_sent_and_received(self):
        message = create_message("join", {"name": "Arshia"})

        send_message(self.sender, message)

        self.assertEqual(receive_message(self.receiver), message)

    def test_back_to_back_messages_stay_separate(self):
        first_message = create_message("click", {"shape_id": 7})
        second_message = create_message("score_update", {"score": 10})

        combined_bytes = encode_message(first_message)
        combined_bytes += encode_message(second_message)
        self.sender.sendall(combined_bytes)

        self.assertEqual(receive_message(self.receiver), first_message)
        self.assertEqual(receive_message(self.receiver), second_message)

    def test_message_can_arrive_in_small_pieces(self):
        message = create_message("player_state", {"stamina": 95})
        message_bytes = encode_message(message)

        for byte_value in message_bytes:
            self.sender.sendall(bytes([byte_value]))

        self.assertEqual(receive_message(self.receiver), message)

    def test_unknown_message_type_is_rejected(self):
        with self.assertRaises(ValueError):
            create_message("not_a_real_type", {})

    def test_oversized_message_header_is_rejected(self):
        invalid_header = struct.pack(HEADER_FORMAT, MAX_MESSAGE_SIZE + 1)
        self.sender.sendall(invalid_header)

        with self.assertRaises(ValueError):
            receive_message(self.receiver)

    def test_disconnect_during_message_is_reported(self):
        incomplete_header = struct.pack(HEADER_FORMAT, 10)
        self.sender.sendall(incomplete_header + b"short")
        self.sender.close()

        with self.assertRaises(ConnectionError):
            receive_message(self.receiver)
