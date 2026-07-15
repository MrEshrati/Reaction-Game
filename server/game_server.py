import random
import socket
import threading
import time

from shared.protocol import create_message, receive_message, send_message


SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5050
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600


# this function creates all shared server state in one place
def create_server_state(
    match_duration=15,
    shape_interval=0.8,
    shape_lifetime=1.5,
):
    return {
        "clients": {},
        "scores": {},
        "active_shapes": {},
        "next_player_id": 1,
        "next_shape_id": 1,
        "match_duration": match_duration,
        "shape_interval": shape_interval,
        "shape_lifetime": shape_lifetime,
        "match_started": False,
        "match_running": False,
        "state_lock": threading.Lock(),
        "match_stop_event": threading.Event(),
        "server_stop_event": threading.Event(),
        "match_thread": None,
        "client_threads": [],
    }


# JSON changes integer dictionary keys to strings, so do it explicitly
def copy_scores_for_message(server_state):
    message_scores = {}

    for player_id, score in server_state["scores"].items():
        message_scores[str(player_id)] = score

    return message_scores


# each client has a send lock so two server threads cannot mix message bytes
def safe_send(client, message):
    try:
        with client["send_lock"]:
            send_message(client["connection"], message)
        return True
    except (ConnectionError, OSError, ValueError):
        return False


# this function sends the same authoritative event to every connected player
def broadcast_message(server_state, message):
    with server_state["state_lock"]:
        clients = []
        for client in server_state["clients"].values():
            clients.append(client)

    disconnected_players = []

    for client in clients:
        if not safe_send(client, message):
            disconnected_players.append(client["player_id"])

    for player_id in disconnected_players:
        remove_client(server_state, player_id)


# a match accepts exactly two players and no late joins
def register_client(server_state, connection, address, player_name):
    with server_state["state_lock"]:
        if server_state["match_started"]:
            return None

        if len(server_state["clients"]) >= 2:
            return None

        player_id = server_state["next_player_id"]
        server_state["next_player_id"] += 1

        client = {
            "player_id": player_id,
            "name": player_name,
            "connection": connection,
            "address": address,
            "send_lock": threading.Lock(),
        }

        server_state["clients"][player_id] = client
        server_state["scores"][player_id] = 0
        return player_id


# closing the socket also wakes its client thread if it is blocked in recv
def remove_client(server_state, player_id):
    with server_state["state_lock"]:
        client = server_state["clients"].pop(player_id, None)

        if client is not None and server_state["match_running"]:
            server_state["match_stop_event"].set()

    if client is not None:
        try:
            client["connection"].close()
        except OSError:
            pass


# this function creates one simple normal shape for the minimal server
def create_random_shape(server_state):
    possible_points = [-3, -2, -1, 1, 2, 3, 4, 5, 6]

    with server_state["state_lock"]:
        shape_id = server_state["next_shape_id"]
        server_state["next_shape_id"] += 1

        shape = {
            "shape_id": shape_id,
            "shape_type": "normal",
            "x": random.randint(60, SCREEN_WIDTH - 60),
            "y": random.randint(120, SCREEN_HEIGHT - 60),
            "radius": 30,
            "points": random.choice(possible_points),
            "lifetime": server_state["shape_lifetime"],
            "expires_at": time.monotonic() + server_state["shape_lifetime"],
        }

        server_state["active_shapes"][shape_id] = shape
        return shape.copy()


# expired shapes are removed by the server, never by a client
def remove_expired_shapes(server_state):
    current_time = time.monotonic()
    expired_shape_ids = []

    with server_state["state_lock"]:
        for shape_id, shape in server_state["active_shapes"].items():
            if current_time >= shape["expires_at"]:
                expired_shape_ids.append(shape_id)

        for shape_id in expired_shape_ids:
            del server_state["active_shapes"][shape_id]

    return expired_shape_ids


# this is the authoritative and atomic check-and-change click operation
def process_click(server_state, player_id, shape_id):
    with server_state["state_lock"]:
        if not server_state["match_running"]:
            return {
                "accepted": False,
                "error": "The match is not running.",
            }

        if player_id not in server_state["clients"]:
            return {
                "accepted": False,
                "error": "The player is not connected.",
            }

        shape = server_state["active_shapes"].get(shape_id)

        if shape is None:
            return {
                "accepted": False,
                "error": "The shape is no longer available.",
            }

        if time.monotonic() >= shape["expires_at"]:
            del server_state["active_shapes"][shape_id]
            return {
                "accepted": False,
                "error": "The shape has expired.",
            }

        del server_state["active_shapes"][shape_id]
        server_state["scores"][player_id] += shape["points"]
        scores = copy_scores_for_message(server_state)

        return {
            "accepted": True,
            "shape_id": shape_id,
            "claimed_by": player_id,
            "points": shape["points"],
            "scores": scores,
        }


# only click messages are accepted while the minimal match is running
def handle_client_message(server_state, client, message):
    if message["type"] != "click":
        error_message = create_message(
            "error",
            {"message": "Only click messages are allowed during the match."},
        )
        safe_send(client, error_message)
        return

    shape_id = message["data"].get("shape_id")

    if not isinstance(shape_id, int):
        error_message = create_message(
            "error",
            {"message": "A click needs an integer shape_id."},
        )
        safe_send(client, error_message)
        return

    result = process_click(server_state, client["player_id"], shape_id)

    if not result["accepted"]:
        error_message = create_message(
            "error",
            {"message": result["error"]},
        )
        safe_send(client, error_message)
        return

    remove_message = create_message(
        "shape_remove",
        {
            "shape_id": result["shape_id"],
            "reason": "claimed",
            "claimed_by": result["claimed_by"],
            "points": result["points"],
        },
    )
    broadcast_message(server_state, remove_message)

    score_message = create_message(
        "score_update",
        {"scores": result["scores"]},
    )
    broadcast_message(server_state, score_message)


# the winner is decided from server scores after the match finishes
def find_winner(server_state):
    connected_player_ids = []
    for player_id in server_state["clients"]:
        connected_player_ids.append(player_id)

    if len(connected_player_ids) == 1:
        return connected_player_ids[0]

    highest_score = None
    winning_player_ids = []

    for player_id, score in server_state["scores"].items():
        if highest_score is None or score > highest_score:
            highest_score = score
            winning_player_ids = [player_id]
        elif score == highest_score:
            winning_player_ids.append(player_id)

    if len(winning_player_ids) == 1:
        return winning_player_ids[0]

    return None


# the match thread owns the timer and shape generation schedule
def run_match(server_state):
    with server_state["state_lock"]:
        if len(server_state["clients"]) != 2:
            return

        server_state["match_running"] = True
        match_duration = server_state["match_duration"]
        match_end_time = time.monotonic() + match_duration
        starting_scores = copy_scores_for_message(server_state)

    start_message = create_message(
        "game_start",
        {
            "duration": match_duration,
            "scores": starting_scores,
        },
    )
    broadcast_message(server_state, start_message)

    while time.monotonic() < match_end_time:
        if server_state["match_stop_event"].is_set():
            break

        expired_shape_ids = remove_expired_shapes(server_state)
        for shape_id in expired_shape_ids:
            remove_message = create_message(
                "shape_remove",
                {
                    "shape_id": shape_id,
                    "reason": "expired",
                    "claimed_by": None,
                },
            )
            broadcast_message(server_state, remove_message)

        shape = create_random_shape(server_state)
        shape_message_data = shape.copy()
        del shape_message_data["expires_at"]
        shape_message = create_message("shape_spawn", shape_message_data)
        broadcast_message(server_state, shape_message)

        remaining_time = match_end_time - time.monotonic()
        wait_time = min(server_state["shape_interval"], remaining_time)

        if wait_time > 0:
            server_state["match_stop_event"].wait(wait_time)

    with server_state["state_lock"]:
        disconnected_early = server_state["match_stop_event"].is_set()
        server_state["match_running"] = False
        server_state["active_shapes"].clear()
        winner = find_winner(server_state)
        final_scores = copy_scores_for_message(server_state)

    if disconnected_early:
        reason = "player_disconnected"
    else:
        reason = "timer_finished"

    game_over_message = create_message(
        "game_over",
        {
            "winner": winner,
            "scores": final_scores,
            "reason": reason,
        },
    )
    broadcast_message(server_state, game_over_message)


# the second successful registration starts exactly one match thread
def start_match_if_ready(server_state):
    with server_state["state_lock"]:
        
        if len(server_state["clients"]) != 2 or server_state["match_started"]:
            return None

        server_state["match_started"] = True
        server_state["match_stop_event"].clear()
        match_thread = threading.Thread(target=run_match, args=(server_state,))
        server_state["match_thread"] = match_thread

    match_thread.start()
    return match_thread


# every connected client has one thread that receives its requests
def handle_client(server_state, connection, address):
    player_id = None

    try:
        first_message = receive_message(connection)

        if first_message["type"] != "join":
            error_message = create_message(
                "error",
                {"message": "The first message must be join."},
            )
            send_message(connection, error_message)
            return

        player_name = str(first_message["data"].get("name", "")).strip()

        if not player_name:
            error_message = create_message(
                "error",
                {"message": "A player name is required."},
            )
            send_message(connection, error_message)
            return

        player_id = register_client(
            server_state,
            connection,
            address,
            player_name,
        )

        if player_id is None:
            error_message = create_message(
                "error",
                {"message": "The match already has two players."},
            )
            send_message(connection, error_message)
            return

        with server_state["state_lock"]:
            client = server_state["clients"][player_id]
            waiting_for_players = 2 - len(server_state["clients"])

        welcome_message = create_message(
            "welcome",
            {
                "player_id": player_id,
                "name": player_name,
                "waiting_for_players": waiting_for_players,
            },
        )
        safe_send(client, welcome_message)
        print(f"Player {player_id} joined as {player_name}")

        start_match_if_ready(server_state)

        while not server_state["server_stop_event"].is_set():
            message = receive_message(connection)
            handle_client_message(server_state, client, message)
    except (ConnectionError, OSError, ValueError) as error:
        if not server_state["server_stop_event"].is_set():
            print("Client connection ended:", error)
    finally:
        if player_id is not None:
            print(f"Player {player_id} disconnected")
            remove_client(server_state, player_id)
        else:
            try:
                connection.close()
            except OSError:
                pass


# the main server accepts connections and gives each one a client thread
def run_server(server_state, host=SERVER_HOST, port=SERVER_PORT):
    listening_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listening_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listening_socket.bind((host, port))
    listening_socket.listen()

    print(f"Game server listening on {host}:{port}")

    try:
        while not server_state["server_stop_event"].is_set():
            connection, address = listening_socket.accept()
            client_thread = threading.Thread(
                target=handle_client,
                args=(server_state, connection, address),
            )

            with server_state["state_lock"]:
                server_state["client_threads"].append(client_thread)

            client_thread.start()
    except KeyboardInterrupt:
        print("Stopping the server...")
    finally:
        server_state["server_stop_event"].set()
        server_state["match_stop_event"].set()
        listening_socket.close()

        with server_state["state_lock"]:
            player_ids = []
            for player_id in server_state["clients"]:
                player_ids.append(player_id)

            client_threads = server_state["client_threads"].copy()
            match_thread = server_state["match_thread"]

        for player_id in player_ids:
            remove_client(server_state, player_id)

        if match_thread is not None:
            match_thread.join(timeout=2)

        for client_thread in client_threads:
            client_thread.join(timeout=2)
