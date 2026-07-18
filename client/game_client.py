import math
import queue
import random
import socket
import threading
import time

import pygame

from game.shapes import shape_from_message
from shared.protocol import create_message, send_message
from shared.threading_tools import receive_messages


SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5050
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
FRAMES_PER_SECOND = 60

BACKGROUND_COLOR = (18, 24, 38)
PANEL_COLOR = (30, 39, 58)
TEXT_COLOR = (240, 244, 255)
SECONDARY_TEXT_COLOR = (170, 181, 205)
ACCENT_COLOR = (64, 156, 255)
POSITIVE_COLOR = (63, 196, 112)
NEGATIVE_COLOR = (235, 83, 83)
SHIELD_COLOR = (58, 128, 246)
ICE_COLOR = (85, 210, 230)
STAMINA_COLOR = (245, 190, 65)
STAMINA_BACKGROUND_COLOR = (53, 63, 82)
STRESS_COLOR = (244, 100, 105)
STRESS_BACKGROUND_COLOR = (73, 52, 65)
BUTTON_COLOR = (44, 126, 224)
BUTTON_HOVER_COLOR = (75, 154, 245)
INPUT_COLOR = (40, 50, 72)

CONNECT_BUTTON = pygame.Rect(280, 370, 240, 55)
NAME_INPUT_BOX = pygame.Rect(220, 285, 360, 58)
MOUSE_CALIBRATION_DURATION = 2
MOUSE_JUMP_INTERVAL = 3
MOUSE_TRAIL_LENGTH = 8


# this function creates all client state in one place
def create_client_state():
    return {
        "running": True,
        "screen_name": "connect",
        "name_input": "",
        "player_name": "",
        "player_id": None,
        "connection": None,
        "network_thread": None,
        "incoming_messages": queue.Queue(),
        "stop_event": threading.Event(),
        "shapes": {},
        "pending_clicks": [],
        "scores": {},
        "player_states": {},
        "match_end_time": None,
        "winner": None,
        "game_over_reason": "",
        "status_message": "Enter your name and connect to the server.",
        "virtual_mouse_position": [SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2],
        "last_system_mouse_position": None,
        "mouse_calibration_end_time": None,
        "mouse_reference_total": 0,
        "mouse_reference_samples": 0,
        "mouse_reference_ratio": 1,
        "next_mouse_jump_time": 0,
        "mouse_trail": [],
    }


# the network thread starts only after the socket and join message are ready
def connect_to_server(
    client_state,
    host=SERVER_HOST,
    port=SERVER_PORT,
):
    player_name = client_state["name_input"].strip()

    if not player_name:
        client_state["status_message"] = "Please enter a player name."
        return False

    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.settimeout(3)

    try:
        client_socket.connect((host, port))
        client_socket.settimeout(None)

        join_message = create_message("join", {"name": player_name})
        send_message(client_socket, join_message)

        client_state["connection"] = client_socket
        client_state["player_name"] = player_name
        client_state["screen_name"] = "waiting"
        client_state["status_message"] = "Connected. Joining the match..."

        network_thread = threading.Thread(
            target=receive_messages,
            args=(
                client_socket,
                client_state["incoming_messages"],
                client_state["stop_event"],
            ),
        )
        client_state["network_thread"] = network_thread
        network_thread.start()
        return True
    except (ConnectionError, OSError, ValueError) as error:
        client_socket.close()
        client_state["status_message"] = "Connection failed: " + str(error)
        return False


# this function closes the socket before joining the blocked network thread
def disconnect_client(client_state):
    client_state["stop_event"].set()
    connection = client_state["connection"]

    if connection is not None:
        try:
            connection.close()
        except OSError:
            pass

    network_thread = client_state["network_thread"]
    if network_thread is not None:
        network_thread.join(timeout=2)


# server messages are applied only by the main thread
def handle_server_message(client_state, message):
    message_type = message["type"]
    message_data = message["data"]

    if message_type == "welcome":
        client_state["player_id"] = message_data["player_id"]
        client_state["screen_name"] = "waiting"
        waiting_count = message_data.get("waiting_for_players", 0)

        if waiting_count > 0:
            client_state["status_message"] = "Waiting for one more player..."
        else:
            client_state["status_message"] = "Both players connected."

    elif message_type == "game_start":
        duration = message_data["duration"]
        client_state["screen_name"] = "game"
        client_state["scores"] = message_data.get("scores", {}).copy()
        client_state["shapes"].clear()
        client_state["pending_clicks"].clear()
        client_state["match_end_time"] = time.monotonic() + duration
        client_state["status_message"] = "Click a shape before your opponent."
        client_state["virtual_mouse_position"] = [
            SCREEN_WIDTH // 2,
            SCREEN_HEIGHT // 2,
        ]
        client_state["last_system_mouse_position"] = None
        client_state["mouse_calibration_end_time"] = (
            time.monotonic() + MOUSE_CALIBRATION_DURATION
        )
        client_state["mouse_reference_total"] = 0
        client_state["mouse_reference_samples"] = 0
        client_state["mouse_reference_ratio"] = 1
        client_state["next_mouse_jump_time"] = (
            time.monotonic() + MOUSE_JUMP_INTERVAL
        )
        client_state["mouse_trail"].clear()

    elif message_type == "shape_spawn":
        shape = shape_from_message(message_data)
        client_state["shapes"][shape.get_id()] = shape

    elif message_type == "shape_remove":
        shape_id = message_data["shape_id"]
        client_state["shapes"].pop(shape_id, None)

        if shape_id in client_state["pending_clicks"]:
            client_state["pending_clicks"].remove(shape_id)

        if message_data.get("reason") == "claimed":
            claimed_by = message_data.get("claimed_by")
            points = message_data.get("points", 0)
            shape_type = message_data.get("shape_type")

            if claimed_by == client_state["player_id"]:
                if shape_type == "shield":
                    client_state["status_message"] = "Shield activated."
                elif shape_type == "ice":
                    client_state["status_message"] = "Opponent frozen."
                elif message_data.get("shield_blocked_penalty"):
                    client_state["status_message"] = "Shield blocked the penalty."
                else:
                    client_state["status_message"] = (
                        "You claimed " + str(points) + " points."
                    )
            else:
                client_state["status_message"] = "Your opponent clicked first."

    elif message_type == "score_update":
        client_state["scores"] = message_data.get("scores", {}).copy()

    elif message_type == "player_state":
        current_time = time.monotonic()
        previous_local_state = client_state["player_states"].get(
            str(client_state["player_id"]),
            {},
        )
        previous_stamina = previous_local_state.get("stamina", 100)
        client_state["player_states"] = {}

        for player_id, player_state in message_data.get("players", {}).items():
            client_state["player_states"][player_id] = {
                "shield_until": current_time
                + player_state.get("shield_seconds", 0),
                "frozen_until": current_time
                + player_state.get("frozen_seconds", 0),
                "stamina": player_state.get("stamina", 100),
                "stress": player_state.get("stress", 0),
            }

        local_player_id = str(client_state["player_id"])
        local_player_state = client_state["player_states"].get(
            local_player_id,
            {},
        )
        current_stamina = local_player_state.get("stamina", 100)

        if previous_stamina <= 10 and current_stamina > 10:
            client_state["status_message"] = "Stamina recovered. You can play again."

    elif message_type == "game_over":
        client_state["screen_name"] = "final"
        client_state["winner"] = message_data.get("winner")
        client_state["scores"] = message_data.get("scores", {}).copy()
        client_state["game_over_reason"] = message_data.get("reason", "")
        client_state["shapes"].clear()
        client_state["pending_clicks"].clear()

    elif message_type == "error":
        client_state["status_message"] = message_data.get(
            "message",
            "Unknown server error.",
        )

        rejected_shape_id = message_data.get("shape_id")
        if rejected_shape_id in client_state["pending_clicks"]:
            client_state["pending_clicks"].remove(rejected_shape_id)

        if message_data.get("connection_closed"):
            client_state["screen_name"] = "disconnected"


# this function drains the thread-safe queue without blocking a Pygame frame
def process_incoming_messages(client_state):
    while True:
        try:
            message = client_state["incoming_messages"].get_nowait()
            handle_server_message(client_state, message)
        except queue.Empty:
            break


# local expiry only hides old visuals; the server still decides valid clicks
def remove_expired_visual_shapes(client_state, current_time=None):
    if current_time is None:
        current_time = time.monotonic()

    expired_shape_ids = []

    for shape_id, shape in client_state["shapes"].items():
        if shape.is_expired(current_time):
            expired_shape_ids.append(shape_id)

    for shape_id in expired_shape_ids:
        del client_state["shapes"][shape_id]

        if shape_id in client_state["pending_clicks"]:
            client_state["pending_clicks"].remove(shape_id)


# this function returns the shape under the mouse cursor
def find_clicked_shape(client_state, mouse_position):
    mouse_x, mouse_y = mouse_position

    for shape_id, shape in client_state["shapes"].items():
        shape_x, shape_y = shape.get_position()
        x_distance = mouse_x - shape_x
        y_distance = mouse_y - shape_y
        distance_squared = x_distance * x_distance + y_distance * y_distance
        radius_squared = shape.get_radius() * shape.get_radius()

        if distance_squared <= radius_squared:
            return shape_id

    return None


def get_local_player_effects(client_state, current_time=None):
    if current_time is None:
        current_time = time.monotonic()

    player_id = str(client_state["player_id"])
    player_state = client_state["player_states"].get(player_id, {})
    shield_seconds = max(0, player_state.get("shield_until", 0) - current_time)
    frozen_seconds = max(0, player_state.get("frozen_until", 0) - current_time)

    return {
        "shield_seconds": shield_seconds,
        "frozen_seconds": frozen_seconds,
        "stamina": player_state.get("stamina", 100),
        "stress": player_state.get("stress", 0),
    }


def get_stamina_darkness(stamina_value):
    if stamina_value < 40 or stamina_value >= 60:
        return 0

    darkness_progress = (60 - stamina_value) / 20
    return int(darkness_progress * 140)


def get_stress_speed_multiplier(stress_value):
    if stress_value <= 10:
        return 1

    if stress_value <= 50:
        return 0.85

    return 0.6


def calculate_mouse_movement(raw_movement, reference_ratio, stress_value):
    speed_multiplier = get_stress_speed_multiplier(stress_value)
    x_movement = raw_movement[0] * reference_ratio * speed_multiplier
    y_movement = raw_movement[1] * reference_ratio * speed_multiplier
    return x_movement, y_movement


# raw movement is converted into a protected virtual cursor position
def update_virtual_mouse(
    client_state,
    current_time=None,
    raw_movement=None,
    system_position=None,
):
    if client_state["screen_name"] != "game":
        return tuple(client_state["virtual_mouse_position"])

    if current_time is None:
        current_time = time.monotonic()

    if raw_movement is None:
        raw_movement = pygame.mouse.get_rel()

    if system_position is None:
        system_position = pygame.mouse.get_pos()

    previous_system_position = client_state["last_system_mouse_position"]
    calibration_end_time = client_state["mouse_calibration_end_time"]

    if calibration_end_time is None:
        calibration_end_time = current_time + MOUSE_CALIBRATION_DURATION
        client_state["mouse_calibration_end_time"] = calibration_end_time

    if previous_system_position is not None:
        raw_distance = math.hypot(raw_movement[0], raw_movement[1])
        system_x_change = system_position[0] - previous_system_position[0]
        system_y_change = system_position[1] - previous_system_position[1]
        system_distance = math.hypot(system_x_change, system_y_change)

        if current_time <= calibration_end_time and raw_distance > 0:
            movement_ratio = system_distance / raw_distance

            if 0.1 <= movement_ratio <= 5:
                client_state["mouse_reference_total"] += movement_ratio
                client_state["mouse_reference_samples"] += 1
                sample_count = client_state["mouse_reference_samples"]
                client_state["mouse_reference_ratio"] = (
                    client_state["mouse_reference_total"] / sample_count
                )

    client_state["last_system_mouse_position"] = system_position
    player_effects = get_local_player_effects(client_state, current_time)
    stress_value = player_effects["stress"]
    mouse_movement = calculate_mouse_movement(
        raw_movement,
        client_state["mouse_reference_ratio"],
        stress_value,
    )
    mouse_x = client_state["virtual_mouse_position"][0] + mouse_movement[0]
    mouse_y = client_state["virtual_mouse_position"][1] + mouse_movement[1]
    mouse_x = max(0, min(SCREEN_WIDTH - 1, mouse_x))
    mouse_y = max(0, min(SCREEN_HEIGHT - 1, mouse_y))

    if stress_value >= 31:
        if current_time >= client_state["next_mouse_jump_time"]:
            mouse_x = random.randint(20, SCREEN_WIDTH - 20)
            mouse_y = random.randint(110, SCREEN_HEIGHT - 20)
            client_state["next_mouse_jump_time"] = (
                current_time + MOUSE_JUMP_INTERVAL
            )
    else:
        client_state["next_mouse_jump_time"] = (
            current_time + MOUSE_JUMP_INTERVAL
        )

    client_state["virtual_mouse_position"] = [mouse_x, mouse_y]

    if stress_value >= 51:
        client_state["mouse_trail"].append((round(mouse_x), round(mouse_y)))
        client_state["mouse_trail"] = client_state["mouse_trail"][
            -MOUSE_TRAIL_LENGTH:
        ]
    else:
        client_state["mouse_trail"].clear()

    return round(mouse_x), round(mouse_y)


# a click is only a request; the client never changes its own score
def send_shape_click(client_state, mouse_position):
    player_effects = get_local_player_effects(client_state)

    if player_effects["stamina"] <= 10:
        client_state["status_message"] = "Stamina depleted. Wait for recovery."
        return False

    if player_effects["frozen_seconds"] > 0:
        client_state["status_message"] = "You are frozen and cannot click."
        return False

    shape_id = find_clicked_shape(client_state, mouse_position)

    if shape_id in client_state["pending_clicks"]:
        return False

    mouse_x, mouse_y = mouse_position
    click_message = create_message(
        "click",
        {
            "shape_id": shape_id,
            "x": mouse_x,
            "y": mouse_y,
        },
    )

    try:
        send_message(client_state["connection"], click_message)
        if shape_id is not None:
            client_state["pending_clicks"].append(shape_id)
        return True
    except (ConnectionError, OSError, ValueError) as error:
        client_state["status_message"] = "Could not send click: " + str(error)
        return False


# the displayed timer is an estimate based on the server-provided duration
def get_remaining_seconds(client_state, current_time=None):
    if client_state["match_end_time"] is None:
        return 0

    if current_time is None:
        current_time = time.monotonic()

    remaining_time = client_state["match_end_time"] - current_time
    return max(0, math.ceil(remaining_time))


def draw_centered_text(surface, text, font, color, y_position):
    rendered_text = font.render(text, True, color)
    text_rectangle = rendered_text.get_rect(
        center=(SCREEN_WIDTH // 2, y_position),
    )
    surface.blit(rendered_text, text_rectangle)


def draw_connect_screen(surface, fonts, client_state):
    surface.fill(BACKGROUND_COLOR)
    draw_centered_text(
        surface,
        "REACTION GAME",
        fonts["title"],
        TEXT_COLOR,
        120,
    )
    draw_centered_text(
        surface,
        "Two players. One shared board. Click first.",
        fonts["normal"],
        SECONDARY_TEXT_COLOR,
        175,
    )

    input_color = INPUT_COLOR
    pygame.draw.rect(surface, input_color, NAME_INPUT_BOX, border_radius=10)
    pygame.draw.rect(surface, ACCENT_COLOR, NAME_INPUT_BOX, 2, border_radius=10)

    if client_state["name_input"]:
        input_text = client_state["name_input"]
        text_color = TEXT_COLOR
    else:
        input_text = "Player name"
        text_color = SECONDARY_TEXT_COLOR

    rendered_input = fonts["normal"].render(input_text, True, text_color)
    surface.blit(rendered_input, (NAME_INPUT_BOX.x + 18, NAME_INPUT_BOX.y + 15))

    mouse_position = pygame.mouse.get_pos()
    if CONNECT_BUTTON.collidepoint(mouse_position):
        button_color = BUTTON_HOVER_COLOR
    else:
        button_color = BUTTON_COLOR

    pygame.draw.rect(surface, button_color, CONNECT_BUTTON, border_radius=10)
    draw_centered_text(
        surface,
        "CONNECT",
        fonts["button"],
        TEXT_COLOR,
        CONNECT_BUTTON.centery,
    )
    draw_centered_text(
        surface,
        client_state["status_message"],
        fonts["small"],
        SECONDARY_TEXT_COLOR,
        480,
    )


def draw_waiting_screen(surface, fonts, client_state):
    surface.fill(BACKGROUND_COLOR)
    draw_centered_text(
        surface,
        "CONNECTED",
        fonts["title"],
        ACCENT_COLOR,
        170,
    )
    draw_centered_text(
        surface,
        "Welcome, " + client_state["player_name"],
        fonts["large"],
        TEXT_COLOR,
        245,
    )
    draw_centered_text(
        surface,
        client_state["status_message"],
        fonts["normal"],
        SECONDARY_TEXT_COLOR,
        315,
    )
    draw_centered_text(
        surface,
        "The match starts automatically when player two joins.",
        fonts["small"],
        SECONDARY_TEXT_COLOR,
        365,
    )


def get_cursor_points(mouse_position):
    mouse_x, mouse_y = mouse_position
    return [
        (mouse_x, mouse_y),
        (mouse_x, mouse_y + 22),
        (mouse_x + 6, mouse_y + 16),
        (mouse_x + 11, mouse_y + 25),
        (mouse_x + 15, mouse_y + 23),
        (mouse_x + 10, mouse_y + 14),
        (mouse_x + 18, mouse_y + 14),
    ]


def draw_virtual_mouse(surface, client_state):
    trail_overlay = pygame.Surface(
        (SCREEN_WIDTH, SCREEN_HEIGHT),
        pygame.SRCALPHA,
    )
    mouse_trail = client_state["mouse_trail"]

    for trail_index, trail_position in enumerate(mouse_trail):
        alpha = round(120 * (trail_index + 1) / max(1, len(mouse_trail)))
        pygame.draw.polygon(
            trail_overlay,
            (TEXT_COLOR[0], TEXT_COLOR[1], TEXT_COLOR[2], alpha),
            get_cursor_points(trail_position),
        )

    surface.blit(trail_overlay, (0, 0))
    mouse_position = client_state["virtual_mouse_position"]
    pygame.draw.polygon(
        surface,
        TEXT_COLOR,
        get_cursor_points(mouse_position),
    )
    pygame.draw.lines(
        surface,
        BACKGROUND_COLOR,
        True,
        get_cursor_points(mouse_position),
        2,
    )


def draw_game_screen(surface, fonts, client_state):
    surface.fill(BACKGROUND_COLOR)
    pygame.draw.rect(surface, PANEL_COLOR, (0, 0, SCREEN_WIDTH, 92))

    player_one_score = client_state["scores"].get("1", 0)
    player_two_score = client_state["scores"].get("2", 0)
    remaining_seconds = get_remaining_seconds(client_state)

    player_one_text = fonts["normal"].render(
        "PLAYER 1: " + str(player_one_score),
        True,
        TEXT_COLOR,
    )
    player_two_text = fonts["normal"].render(
        "PLAYER 2: " + str(player_two_score),
        True,
        TEXT_COLOR,
    )
    timer_text = fonts["large"].render(
        str(remaining_seconds),
        True,
        ACCENT_COLOR,
    )

    surface.blit(player_one_text, (28, 30))
    surface.blit(player_two_text, (SCREEN_WIDTH - player_two_text.get_width() - 28, 30))
    surface.blit(
        timer_text,
        (SCREEN_WIDTH // 2 - timer_text.get_width() // 2, 20),
    )

    player_effects = get_local_player_effects(client_state)
    effect_parts = []
    stamina_value = player_effects["stamina"]
    stress_value = player_effects["stress"]

    stamina_label = fonts["small"].render(
        "STAMINA " + str(round(stamina_value)) + "%",
        True,
        STAMINA_COLOR,
    )
    surface.blit(stamina_label, (28, 65))
    stamina_bar_background = pygame.Rect(145, 70, 110, 10)
    pygame.draw.rect(
        surface,
        STAMINA_BACKGROUND_COLOR,
        stamina_bar_background,
        border_radius=5,
    )
    stamina_width = round(stamina_bar_background.width * stamina_value / 100)
    stamina_bar = pygame.Rect(
        stamina_bar_background.x,
        stamina_bar_background.y,
        stamina_width,
        stamina_bar_background.height,
    )
    pygame.draw.rect(
        surface,
        STAMINA_COLOR,
        stamina_bar,
        border_radius=5,
    )

    stress_label = fonts["small"].render(
        "STRESS " + str(round(stress_value)) + "%",
        True,
        STRESS_COLOR,
    )
    surface.blit(stress_label, (545, 65))
    stress_bar_background = pygame.Rect(650, 70, 110, 10)
    pygame.draw.rect(
        surface,
        STRESS_BACKGROUND_COLOR,
        stress_bar_background,
        border_radius=5,
    )
    stress_width = round(stress_bar_background.width * stress_value / 100)
    stress_bar = pygame.Rect(
        stress_bar_background.x,
        stress_bar_background.y,
        stress_width,
        stress_bar_background.height,
    )
    pygame.draw.rect(
        surface,
        STRESS_COLOR,
        stress_bar,
        border_radius=5,
    )

    if player_effects["shield_seconds"] > 0:
        shield_time = math.ceil(player_effects["shield_seconds"])
        effect_parts.append("SHIELD " + str(shield_time) + "s")

    if player_effects["frozen_seconds"] > 0:
        frozen_time = math.ceil(player_effects["frozen_seconds"])
        effect_parts.append("FROZEN " + str(frozen_time) + "s")

    if effect_parts:
        effect_text = " | ".join(effect_parts)
        rendered_effect = fonts["small"].render(
            effect_text,
            True,
            ICE_COLOR,
        )
        surface.blit(
            rendered_effect,
            (SCREEN_WIDTH // 2 - rendered_effect.get_width() // 2, 65),
        )

    for shape in client_state["shapes"].values():
        shape_type = shape.get_shape_type()
        shape_points = shape.get_points()

        if shape_type == "shield":
            shape_color = SHIELD_COLOR
            shape_label = "S"
        elif shape_type == "ice":
            shape_color = ICE_COLOR
            shape_label = "ICE"
        elif shape_points >= 0:
            shape_color = POSITIVE_COLOR
            shape_label = str(shape_points)
        else:
            shape_color = NEGATIVE_COLOR
            shape_label = str(shape_points)

        center = shape.get_position()
        radius = shape.get_radius()
        pygame.draw.circle(surface, shape_color, center, radius)
        pygame.draw.circle(surface, TEXT_COLOR, center, radius, 3)

        points_text = fonts["shape"].render(
            shape_label,
            True,
            TEXT_COLOR,
        )
        points_rectangle = points_text.get_rect(center=center)
        surface.blit(points_text, points_rectangle)

    darkness = get_stamina_darkness(stamina_value)
    if darkness > 0:
        dark_overlay = pygame.Surface(
            (SCREEN_WIDTH, SCREEN_HEIGHT - 92),
            pygame.SRCALPHA,
        )
        dark_overlay.fill((0, 0, 0, darkness))
        surface.blit(dark_overlay, (0, 92))

    status_bar = pygame.Rect(20, SCREEN_HEIGHT - 52, SCREEN_WIDTH - 40, 34)
    pygame.draw.rect(surface, PANEL_COLOR, status_bar, border_radius=8)
    status_text = fonts["small"].render(
        client_state["status_message"],
        True,
        SECONDARY_TEXT_COLOR,
    )
    surface.blit(status_text, (status_bar.x + 12, status_bar.y + 7))
    draw_virtual_mouse(surface, client_state)


def draw_final_screen(surface, fonts, client_state):
    surface.fill(BACKGROUND_COLOR)
    winner = client_state["winner"]
    player_id = client_state["player_id"]

    if winner is None:
        result_text = "DRAW"
        result_color = SECONDARY_TEXT_COLOR
    elif winner == player_id:
        result_text = "YOU WIN"
        result_color = POSITIVE_COLOR
    else:
        result_text = "PLAYER " + str(winner) + " WINS"
        result_color = NEGATIVE_COLOR

    draw_centered_text(surface, "GAME OVER", fonts["title"], TEXT_COLOR, 130)
    draw_centered_text(surface, result_text, fonts["large"], result_color, 220)

    player_one_score = client_state["scores"].get("1", 0)
    player_two_score = client_state["scores"].get("2", 0)
    score_text = "Player 1: " + str(player_one_score)
    score_text += "     Player 2: " + str(player_two_score)
    draw_centered_text(
        surface,
        score_text,
        fonts["normal"],
        TEXT_COLOR,
        300,
    )
    draw_centered_text(
        surface,
        "Close this window and restart the server for another match.",
        fonts["small"],
        SECONDARY_TEXT_COLOR,
        390,
    )


def draw_disconnected_screen(surface, fonts, client_state):
    surface.fill(BACKGROUND_COLOR)
    draw_centered_text(
        surface,
        "CONNECTION LOST",
        fonts["title"],
        NEGATIVE_COLOR,
        190,
    )
    draw_centered_text(
        surface,
        client_state["status_message"],
        fonts["normal"],
        TEXT_COLOR,
        280,
    )
    draw_centered_text(
        surface,
        "Close the window, check the server, and try again.",
        fonts["small"],
        SECONDARY_TEXT_COLOR,
        345,
    )


def draw_current_screen(surface, fonts, client_state):
    screen_name = client_state["screen_name"]

    if screen_name == "connect":
        draw_connect_screen(surface, fonts, client_state)
    elif screen_name == "waiting":
        draw_waiting_screen(surface, fonts, client_state)
    elif screen_name == "game":
        draw_game_screen(surface, fonts, client_state)
    elif screen_name == "final":
        draw_final_screen(surface, fonts, client_state)
    else:
        draw_disconnected_screen(surface, fonts, client_state)


def handle_pygame_event(event, client_state):
    if event.type == pygame.QUIT:
        client_state["running"] = False
        return

    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
        client_state["running"] = False
        return

    if client_state["screen_name"] == "connect":
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                connect_to_server(client_state)
            elif event.key == pygame.K_BACKSPACE:
                client_state["name_input"] = client_state["name_input"][:-1]
            elif len(client_state["name_input"]) < 20:
                if event.unicode.isprintable():
                    client_state["name_input"] += event.unicode

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if CONNECT_BUTTON.collidepoint(event.pos):
                connect_to_server(client_state)

    elif client_state["screen_name"] == "game":
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mouse_position = client_state["virtual_mouse_position"]
            send_shape_click(client_state, mouse_position)


# initialize only the display and font modules used by this client
def initialize_pygame():
    pygame.display.init()
    pygame.font.init()


def run_game_client():
    initialize_pygame()
    surface = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Reaction Game")
    clock = pygame.time.Clock()
    fonts = {
        "title": pygame.font.SysFont("arial", 48, bold=True),
        "large": pygame.font.SysFont("arial", 34, bold=True),
        "normal": pygame.font.SysFont("arial", 24),
        "button": pygame.font.SysFont("arial", 22, bold=True),
        "shape": pygame.font.SysFont("arial", 22, bold=True),
        "small": pygame.font.SysFont("arial", 17),
    }
    client_state = create_client_state()
    mouse_is_hidden = False

    while client_state["running"]:
        process_incoming_messages(client_state)

        if client_state["screen_name"] == "game":
            if not mouse_is_hidden:
                pygame.mouse.set_visible(False)
                pygame.event.set_grab(True)
                pygame.mouse.get_rel()
                mouse_is_hidden = True

            update_virtual_mouse(client_state)
        elif mouse_is_hidden:
            pygame.mouse.set_visible(True)
            pygame.event.set_grab(False)
            mouse_is_hidden = False

        for event in pygame.event.get():
            handle_pygame_event(event, client_state)

        if client_state["screen_name"] == "game":
            remove_expired_visual_shapes(client_state)

        draw_current_screen(surface, fonts, client_state)
        pygame.display.flip()
        clock.tick(FRAMES_PER_SECOND)

    pygame.mouse.set_visible(True)
    pygame.event.set_grab(False)
    disconnect_client(client_state)
    pygame.quit()
