import json
import struct


HEADER_FORMAT = "!I"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
MAX_MESSAGE_SIZE = 1024 * 1024

MESSAGE_TYPES = [
    "join",
    "welcome",
    "game_start",
    "shape_spawn",
    "shape_remove",
    "click",
    "score_update",
    "player_state",
    "game_over",
    "error",
]


# this function checks that every message follows our game protocol
def validate_message(message):
    if not isinstance(message, dict):
        raise ValueError("A protocol message must be a dictionary.")

    if "type" not in message or "data" not in message:
        raise ValueError("A protocol message needs type and data fields.")

    if message["type"] not in MESSAGE_TYPES:
        raise ValueError("Unknown message type: " + str(message["type"]))

    if not isinstance(message["data"], dict):
        raise ValueError("The data field must be a dictionary.")


# this function creates a message with the same structure everywhere
def create_message(message_type, data=None):
    if data is None:
        data = {}

    message = {
        "type": message_type,
        "data": data,
    }
    validate_message(message)
    return message


# this function changes a message into a header followed by JSON bytes
def encode_message(message):
    validate_message(message)

    json_text = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    message_bytes = json_text.encode("utf-8")

    if len(message_bytes) > MAX_MESSAGE_SIZE:
        raise ValueError("The message is too large.")

    header = struct.pack(HEADER_FORMAT, len(message_bytes))
    return header + message_bytes


# recv can return fewer bytes than requested, so keep receiving until complete
def receive_exact(connection, byte_count):
    received_data = b""

    while len(received_data) < byte_count:
        remaining_bytes = byte_count - len(received_data)
        new_data = connection.recv(remaining_bytes)

        if not new_data:
            raise ConnectionError("The connection closed during a message.")

        received_data += new_data

    return received_data


# this function sends one complete framed message
def send_message(connection, message):
    complete_message = encode_message(message)
    connection.sendall(complete_message)


# this function receives one complete framed message
def receive_message(connection):
    header = receive_exact(connection, HEADER_SIZE)
    message_size = struct.unpack(HEADER_FORMAT, header)[0]

    if message_size == 0:
        raise ValueError("An empty message is not valid.")

    if message_size > MAX_MESSAGE_SIZE:
        raise ValueError("The received message is too large.")

    message_bytes = receive_exact(connection, message_size)

    try:
        json_text = message_bytes.decode("utf-8")
        message = json.loads(json_text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("The received message is not valid JSON.")

    validate_message(message)
    return message
