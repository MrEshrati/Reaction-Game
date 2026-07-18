import random
import socket
import threading
import time

from game.player import PlayerStamina, PlayerStress
from game.shapes import create_hallucination_shape
from game.shapes import create_random_shape as create_shape_object
from shared.match_settings import is_valid_match_duration
from shared.protocol import create_message, receive_message, send_message


SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5050
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
LOW_STAMINA_HIDE_CHANCE = 0.5
STAMINA_UPDATE_INTERVAL = 0.1
EMPTY_CLICK_STRESS = 5
HALLUCINATION_CHECK_INTERVAL = 3
SERVER_ACCEPT_TIMEOUT = 0.2


# this function creates all shared server state in one place
def create_server_state(
    match_duration=15,
    shape_interval=0.8,
    shape_lifetime=1.5,
):
    return {
        "clients": {},
        "scores": {},
        "player_effects": {},
        "player_stamina": {},
        "player_stress": {},
        "active_shapes": {},
        "shape_visibility": {},
        "next_hallucination_times": {},
        "next_player_id": 1,
        "next_shape_id": 1,
        "match_duration": match_duration,
        "shape_interval": shape_interval,
        "shape_lifetime": shape_lifetime,
        "match_started": False,
        "match_running": False,
        "match_end_time": None,
        "player_disconnected_early": False,
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


# private effect times and stamina objects become simple client state values
def copy_player_effects_for_message(server_state, current_time=None):
    if current_time is None:
        current_time = time.monotonic()

    message_effects = {}

    for player_id, effects in server_state["player_effects"].items():
        shield_seconds = max(0, effects["shield_until"] - current_time)
        frozen_seconds = max(0, effects["frozen_until"] - current_time)
        stamina = server_state["player_stamina"][player_id]
        stamina_value = stamina.get_value(
            current_time,
            effects["frozen_until"],
        )
        stress_value = server_state["player_stress"][player_id].get_value()
        message_effects[str(player_id)] = {
            "shield_seconds": shield_seconds,
            "frozen_seconds": frozen_seconds,
            "stamina": stamina_value,
            "stress": stress_value,
        }

    return message_effects


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


# recovery is calculated on the server and sent only when a value changes
def broadcast_player_state_if_changed(server_state):
    current_time = time.monotonic()

    with server_state["state_lock"]:
        player_state_changed = False

        for player_id, stamina in server_state["player_stamina"].items():
            frozen_until = server_state["player_effects"][player_id][
                "frozen_until"
            ]
            stress = server_state["player_stress"][player_id]
            if stress.update(
                stamina.get_stored_value(),
                current_time,
                frozen_until,
            ):
                player_state_changed = True

            if stamina.update(current_time, frozen_until):
                player_state_changed = True

        if not player_state_changed:
            return False

        player_states = copy_player_effects_for_message(
            server_state,
            current_time,
        )

    player_state_message = create_message(
        "player_state",
        {"players": player_states},
    )
    broadcast_message(server_state, player_state_message)
    return True


# stressed players receive private fake normal shapes on the server schedule
def spawn_due_hallucinations(server_state):
    current_time = time.monotonic()
    new_shapes = []

    with server_state["state_lock"]:
        for player_id in server_state["clients"]:
            stress = server_state["player_stress"][player_id]
            hallucination_interval = stress.get_hallucination_interval()

            if hallucination_interval is None:
                server_state["next_hallucination_times"][player_id] = (
                    current_time + HALLUCINATION_CHECK_INTERVAL
                )
                continue

            next_spawn_time = server_state["next_hallucination_times"].get(
                player_id,
                current_time + hallucination_interval,
            )

            if current_time < next_spawn_time:
                continue

            shape_id = server_state["next_shape_id"]
            server_state["next_shape_id"] += 1
            shape = create_hallucination_shape(
                shape_id,
                SCREEN_WIDTH,
                SCREEN_HEIGHT,
                server_state["shape_lifetime"],
                player_id,
            )
            server_state["active_shapes"][shape_id] = shape
            server_state["next_hallucination_times"][player_id] = (
                current_time + hallucination_interval
            )
            new_shapes.append(shape)

    for shape in new_shapes:
        broadcast_shape_spawn(server_state, shape)

    return new_shapes


# hallucinations can use this function to target only their affected player
def broadcast_shape_spawn(server_state, shape):
    with server_state["state_lock"]:
        clients = []
        visible_player_ids = set()
        current_time = time.monotonic()

        for client in server_state["clients"].values():
            player_id = client["player_id"]

            if not shape.is_visible_to(player_id):
                continue

            effects = server_state["player_effects"][player_id]
            stamina = server_state["player_stamina"][player_id]
            stamina_level = stamina.get_level(
                current_time,
                effects["frozen_until"],
            )

            if stamina_level == "limited_visibility":
                if random.random() < LOW_STAMINA_HIDE_CHANCE:
                    continue

            clients.append(client)
            visible_player_ids.add(player_id)

        server_state["shape_visibility"][shape.get_id()] = visible_player_ids

    shape_message = create_message("shape_spawn", shape.get_spawn_data())
    disconnected_players = []

    for client in clients:
        if not safe_send(client, shape_message):
            disconnected_players.append(client["player_id"])

    for player_id in disconnected_players:
        remove_client(server_state, player_id)


# the first player is the host and chooses the authoritative match duration
def register_client(
    server_state,
    connection,
    address,
    player_name,
    requested_duration=None,
):
    with server_state["state_lock"]:
        if server_state["match_started"]:
            return None

        if len(server_state["clients"]) >= 2:
            return None

        is_host = len(server_state["clients"]) == 0
        player_id = server_state["next_player_id"]
        server_state["next_player_id"] += 1

        if is_host and requested_duration is not None:
            server_state["match_duration"] = requested_duration

        client = {
            "player_id": player_id,
            "name": player_name,
            "is_host": is_host,
            "connection": connection,
            "address": address,
            "send_lock": threading.Lock(),
        }

        server_state["clients"][player_id] = client
        server_state["scores"][player_id] = 0
        server_state["player_effects"][player_id] = {
            "shield_until": 0,
            "frozen_until": 0,
        }
        server_state["player_stamina"][player_id] = PlayerStamina()
        server_state["player_stress"][player_id] = PlayerStress()
        server_state["next_hallucination_times"][player_id] = (
            time.monotonic() + HALLUCINATION_CHECK_INTERVAL
        )
        return player_id


# closing the socket also wakes its client thread if it is blocked in recv
def remove_client(server_state, player_id):
    with server_state["state_lock"]:
        client = server_state["clients"].pop(player_id, None)

        if client is not None and server_state["match_started"]:
            match_end_time = server_state["match_end_time"]
            if match_end_time is None or time.monotonic() < match_end_time:
                server_state["player_disconnected_early"] = True
            server_state["match_stop_event"].set()

        if client is not None and not server_state["match_started"]:
            server_state["scores"].pop(player_id, None)
            server_state["player_effects"].pop(player_id, None)
            server_state["player_stamina"].pop(player_id, None)
            server_state["player_stress"].pop(player_id, None)
            server_state["next_hallucination_times"].pop(player_id, None)

            if not server_state["clients"]:
                server_state["next_player_id"] = 1

    if client is not None:
        try:
            client["connection"].close()
        except OSError:
            pass


# this function stores whichever concrete shape the polymorphic factory creates
def create_random_shape(server_state):
    with server_state["state_lock"]:
        shape_id = server_state["next_shape_id"]
        server_state["next_shape_id"] += 1

        shape = create_shape_object(
            shape_id,
            SCREEN_WIDTH,
            SCREEN_HEIGHT,
            server_state["shape_lifetime"],
        )
        server_state["active_shapes"][shape_id] = shape
        return shape


# expired shapes are removed by the server, never by a client
def remove_expired_shapes(server_state):
    current_time = time.monotonic()
    expired_shape_ids = []

    with server_state["state_lock"]:
        for shape_id, shape in server_state["active_shapes"].items():
            if shape.is_expired(current_time):
                expired_shape_ids.append(shape_id)

        for shape_id in expired_shape_ids:
            del server_state["active_shapes"][shape_id]
            server_state["shape_visibility"].pop(shape_id, None)

    return expired_shape_ids


# special effects are applied while the same state lock protects the click
def apply_shape_effect(server_state, player_id, effect, current_time):
    if effect is None:
        return

    effect_type = effect["type"]
    effect_duration = effect["duration"]

    if effect_type == "shield":
        current_end_time = server_state["player_effects"][player_id]["shield_until"]
        start_time = max(current_time, current_end_time)
        server_state["player_effects"][player_id]["shield_until"] = (
            start_time + effect_duration
        )

    elif effect_type == "ice":
        for opponent_id in server_state["clients"]:
            if opponent_id == player_id:
                continue

            current_end_time = server_state["player_effects"][opponent_id][
                "frozen_until"
            ]
            opponent_stamina = server_state["player_stamina"][opponent_id]
            opponent_stress = server_state["player_stress"][opponent_id]
            opponent_stress.update(
                opponent_stamina.get_stored_value(),
                current_time,
                current_end_time,
            )
            opponent_stamina.update(current_time, current_end_time)
            start_time = max(current_time, current_end_time)
            server_state["player_effects"][opponent_id]["frozen_until"] = (
                start_time + effect_duration
            )


# this is the authoritative and atomic check-and-change click operation
def process_click(server_state, player_id, shape_id, click_position):
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

        if type(shape_id) is not int:
            return {
                "accepted": False,
                "error": "A click needs an integer shape_id.",
            }

        if not isinstance(click_position, (list, tuple)):
            return {
                "accepted": False,
                "error": "A click needs an x and y position.",
            }

        if len(click_position) != 2:
            return {
                "accepted": False,
                "error": "A click needs an x and y position.",
            }

        click_x, click_y = click_position

        if type(click_x) is not int or type(click_y) is not int:
            return {
                "accepted": False,
                "error": "Click coordinates must be integers.",
            }

        if not 0 <= click_x < SCREEN_WIDTH or not 0 <= click_y < SCREEN_HEIGHT:
            return {
                "accepted": False,
                "error": "Click coordinates are outside the game window.",
            }

        current_time = time.monotonic()
        player_effects = server_state["player_effects"][player_id]
        player_stamina = server_state["player_stamina"][player_id]
        player_stress = server_state["player_stress"][player_id]
        player_stress.update(
            player_stamina.get_stored_value(),
            current_time,
            player_effects["frozen_until"],
        )

        if current_time < player_effects["frozen_until"]:
            return {
                "accepted": False,
                "error": "The player is frozen.",
            }

        if not player_stamina.can_play(
            current_time,
            player_effects["frozen_until"],
        ):
            return {
                "accepted": False,
                "error": "The player's stamina is too low.",
            }

        shape = server_state["active_shapes"].get(shape_id)

        if shape is None:
            return {
                "accepted": False,
                "error": "The shape is no longer available.",
            }

        if not shape.is_visible_to(player_id):
            return {
                "accepted": False,
                "error": "The shape is not available to this player.",
            }

        visible_player_ids = server_state["shape_visibility"].get(shape_id)
        if visible_player_ids is not None and player_id not in visible_player_ids:
            return {
                "accepted": False,
                "error": "The shape is not available to this player.",
            }

        if shape.is_expired(current_time):
            del server_state["active_shapes"][shape_id]
            server_state["shape_visibility"].pop(shape_id, None)
            return {
                "accepted": False,
                "error": "The shape has expired.",
            }

        if not shape.contains_point(click_x, click_y):
            return {
                "accepted": False,
                "error": "The click did not hit the shape.",
            }

        click_result = shape.get_click_result()
        awarded_points = click_result["points"]
        shield_blocked_penalty = False

        if awarded_points < 0 and current_time < player_effects["shield_until"]:
            awarded_points = 0
            shield_blocked_penalty = True
        else:
            awarded_points = player_stamina.adjust_shape_points(
                awarded_points,
                current_time,
                player_effects["frozen_until"],
            )

        del server_state["active_shapes"][shape_id]
        server_state["shape_visibility"].pop(shape_id, None)
        stamina_cost = click_result["stamina_cost"]
        player_stress.change(click_result["stress_change"])
        if stamina_cost > 0:
            player_stamina.spend_for_click(
                stamina_cost,
                current_time,
                player_effects["frozen_until"],
            )
        server_state["scores"][player_id] += awarded_points
        apply_shape_effect(
            server_state,
            player_id,
            click_result["effect"],
            current_time,
        )
        scores = copy_scores_for_message(server_state)
        player_states = copy_player_effects_for_message(server_state, current_time)

        return {
            "accepted": True,
            "shape_id": shape_id,
            "claimed_by": player_id,
            "shape_type": shape.get_shape_type(),
            "points": awarded_points,
            "shield_blocked_penalty": shield_blocked_penalty,
            "scores": scores,
            "player_states": player_states,
        }


# an empty click changes stamina and stress but never changes a score
def process_empty_click(server_state, player_id, click_position):
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

        if not isinstance(click_position, (list, tuple)):
            return {
                "accepted": False,
                "error": "A click needs an x and y position.",
            }

        if len(click_position) != 2:
            return {
                "accepted": False,
                "error": "A click needs an x and y position.",
            }

        click_x, click_y = click_position
        if type(click_x) is not int or type(click_y) is not int:
            return {
                "accepted": False,
                "error": "Click coordinates must be integers.",
            }

        if not 0 <= click_x < SCREEN_WIDTH or not 0 <= click_y < SCREEN_HEIGHT:
            return {
                "accepted": False,
                "error": "Click coordinates are outside the game window.",
            }

        current_time = time.monotonic()
        player_effects = server_state["player_effects"][player_id]
        player_stamina = server_state["player_stamina"][player_id]
        player_stress = server_state["player_stress"][player_id]
        player_stress.update(
            player_stamina.get_stored_value(),
            current_time,
            player_effects["frozen_until"],
        )

        if current_time < player_effects["frozen_until"]:
            return {
                "accepted": False,
                "error": "The player is frozen.",
            }

        if not player_stamina.can_play(
            current_time,
            player_effects["frozen_until"],
        ):
            return {
                "accepted": False,
                "error": "The player's stamina is too low.",
            }

        for shape_id, shape in server_state["active_shapes"].items():
            if shape.is_expired(current_time):
                continue

            if not shape.is_visible_to(player_id):
                continue

            visible_player_ids = server_state["shape_visibility"].get(shape_id)
            if visible_player_ids is not None:
                if player_id not in visible_player_ids:
                    continue

            if shape.contains_point(click_x, click_y):
                return {
                    "accepted": False,
                    "error": "The click position is not empty.",
                }

        player_stamina.spend_for_click(
            current_time=current_time,
            frozen_until=player_effects["frozen_until"],
        )
        player_stress.change(EMPTY_CLICK_STRESS)
        player_states = copy_player_effects_for_message(server_state, current_time)

        return {
            "accepted": True,
            "player_states": player_states,
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

    click_data = message["data"]

    if "shape_id" not in click_data:
        error_message = create_message(
            "error",
            {"message": "A click needs a shape_id field."},
        )
        safe_send(client, error_message)
        return

    shape_id = click_data.get("shape_id")
    click_x = click_data.get("x")
    click_y = click_data.get("y")

    if shape_id is not None and type(shape_id) is not int:
        error_message = create_message(
            "error",
            {"message": "A click needs an integer shape_id."},
        )
        safe_send(client, error_message)
        return

    if type(click_x) is not int or type(click_y) is not int:
        error_message = create_message(
            "error",
            {
                "message": "Click coordinates must be integers.",
                "shape_id": shape_id,
            },
        )
        safe_send(client, error_message)
        return

    if shape_id is None:
        result = process_empty_click(
            server_state,
            client["player_id"],
            (click_x, click_y),
        )

        if not result["accepted"]:
            error_message = create_message(
                "error",
                {"message": result["error"]},
            )
            safe_send(client, error_message)
            return

        player_state_message = create_message(
            "player_state",
            {"players": result["player_states"]},
        )
        broadcast_message(server_state, player_state_message)
        return

    result = process_click(
        server_state,
        client["player_id"],
        shape_id,
        (click_x, click_y),
    )

    if not result["accepted"]:
        error_message = create_message(
            "error",
            {
                "message": result["error"],
                "shape_id": shape_id,
            },
        )
        safe_send(client, error_message)
        return

    remove_message = create_message(
        "shape_remove",
        {
            "shape_id": result["shape_id"],
            "reason": "claimed",
            "claimed_by": result["claimed_by"],
            "shape_type": result["shape_type"],
            "points": result["points"],
            "shield_blocked_penalty": result["shield_blocked_penalty"],
        },
    )
    broadcast_message(server_state, remove_message)

    score_message = create_message(
        "score_update",
        {"scores": result["scores"]},
    )
    broadcast_message(server_state, score_message)

    player_state_message = create_message(
        "player_state",
        {"players": result["player_states"]},
    )
    broadcast_message(server_state, player_state_message)


# the winner is decided from server scores after the match finishes
def find_winner(server_state, player_disconnected=False):
    connected_player_ids = []
    for player_id in server_state["clients"]:
        connected_player_ids.append(player_id)

    if player_disconnected and len(connected_player_ids) == 1:
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
            winner = find_winner(server_state, player_disconnected=True)
            final_scores = copy_scores_for_message(server_state)
            game_can_start = False
        else:
            server_state["match_running"] = True
            match_duration = server_state["match_duration"]
            match_end_time = time.monotonic() + match_duration
            server_state["match_end_time"] = match_end_time
            server_state["player_disconnected_early"] = False
            starting_scores = copy_scores_for_message(server_state)
            starting_player_states = copy_player_effects_for_message(server_state)
            game_can_start = True

    if not game_can_start:
        game_over_message = create_message(
            "game_over",
            {
                "winner": winner,
                "scores": final_scores,
                "reason": "player_disconnected",
            },
        )
        broadcast_message(server_state, game_over_message)
        return

    start_message = create_message(
        "game_start",
        {
            "duration": match_duration,
            "scores": starting_scores,
        },
    )
    broadcast_message(server_state, start_message)
    player_state_message = create_message(
        "player_state",
        {"players": starting_player_states},
    )
    broadcast_message(server_state, player_state_message)

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
        broadcast_shape_spawn(server_state, shape)

        remaining_time = match_end_time - time.monotonic()
        wait_time = min(server_state["shape_interval"], remaining_time)

        if wait_time > 0:
            wait_end_time = time.monotonic() + wait_time

            while time.monotonic() < wait_end_time:
                remaining_wait = wait_end_time - time.monotonic()
                short_wait = min(STAMINA_UPDATE_INTERVAL, remaining_wait)

                if server_state["match_stop_event"].wait(short_wait):
                    break

                broadcast_player_state_if_changed(server_state)
                spawn_due_hallucinations(server_state)

    with server_state["state_lock"]:
        disconnected_early = server_state["player_disconnected_early"]
        server_state["match_running"] = False
        server_state["active_shapes"].clear()
        server_state["shape_visibility"].clear()
        winner = find_winner(server_state, disconnected_early)
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
        requested_duration = first_message["data"].get("duration")

        if not player_name:
            error_message = create_message(
                "error",
                {"message": "A player name is required."},
            )
            send_message(connection, error_message)
            return

        if not is_valid_match_duration(requested_duration):
            error_message = create_message(
                "error",
                {
                    "message": (
                        "Match duration must be a whole number "
                        "between 10 and 300 seconds."
                    ),
                },
            )
            send_message(connection, error_message)
            return

        player_id = register_client(
            server_state,
            connection,
            address,
            player_name,
            requested_duration,
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
            match_duration = server_state["match_duration"]

        welcome_message = create_message(
            "welcome",
            {
                "player_id": player_id,
                "name": player_name,
                "waiting_for_players": waiting_for_players,
                "is_host": client["is_host"],
                "match_duration": match_duration,
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
    listening_socket.settimeout(SERVER_ACCEPT_TIMEOUT)

    actual_port = listening_socket.getsockname()[1]
    print(f"Game server listening on {host}:{actual_port}")

    try:
        while not server_state["server_stop_event"].is_set():
            try:
                connection, address = listening_socket.accept()
            except socket.timeout:
                continue

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
