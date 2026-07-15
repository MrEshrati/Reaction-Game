from shared.protocol import receive_message


# the network thread receives messages and gives them to the main thread
def receive_messages(connection, incoming_messages, stop_event):
    while not stop_event.is_set():
        try:
            message = receive_message(connection)
        except (ConnectionError, OSError, ValueError) as error:
            if not stop_event.is_set():
                error_message = {
                    "type": "error",
                    "data": {
                        "message": str(error),
                        "connection_closed": True,
                    },
                }
                incoming_messages.put(error_message)

            stop_event.set()
            break

        incoming_messages.put(message)

        if message["type"] == "game_over":
            stop_event.set()
            break


# the lock keeps the check and the change together as one safe operation
def claim_shape(shared_shape, player_id, state_lock):
    with state_lock:
        if shared_shape["claimed_by"] is not None:
            return False

        shared_shape["claimed_by"] = player_id
        return True
