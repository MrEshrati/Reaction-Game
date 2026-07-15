import math
import queue
import socket
import threading
import time

import pygame

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
BUTTON_COLOR = (44, 126, 224)
BUTTON_HOVER_COLOR = (75, 154, 245)
INPUT_COLOR = (40, 50, 72)

CONNECT_BUTTON = pygame.Rect(280, 370, 240, 55)
NAME_INPUT_BOX = pygame.Rect(220, 285, 360, 58)


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
        "match_end_time": None,
        "winner": None,
        "game_over_reason": "",
        "status_message": "Enter your name and connect to the server.",
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

    elif message_type == "shape_spawn":
        shape = message_data.copy()
        shape_id = shape["shape_id"]
        shape["visual_expires_at"] = time.monotonic() + shape["lifetime"]
        client_state["shapes"][shape_id] = shape

    elif message_type == "shape_remove":
        shape_id = message_data["shape_id"]
        client_state["shapes"].pop(shape_id, None)

        if shape_id in client_state["pending_clicks"]:
            client_state["pending_clicks"].remove(shape_id)

        if message_data.get("reason") == "claimed":
            claimed_by = message_data.get("claimed_by")
            points = message_data.get("points", 0)

            if claimed_by == client_state["player_id"]:
                client_state["status_message"] = (
                    "You claimed " + str(points) + " points."
                )
            else:
                client_state["status_message"] = "Your opponent clicked first."

    elif message_type == "score_update":
        client_state["scores"] = message_data.get("scores", {}).copy()

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
        if current_time >= shape["visual_expires_at"]:
            expired_shape_ids.append(shape_id)

    for shape_id in expired_shape_ids:
        del client_state["shapes"][shape_id]

        if shape_id in client_state["pending_clicks"]:
            client_state["pending_clicks"].remove(shape_id)


# this function returns the shape under the mouse cursor
def find_clicked_shape(client_state, mouse_position):
    mouse_x, mouse_y = mouse_position

    for shape_id, shape in client_state["shapes"].items():
        x_distance = mouse_x - shape["x"]
        y_distance = mouse_y - shape["y"]
        distance_squared = x_distance * x_distance + y_distance * y_distance
        radius_squared = shape["radius"] * shape["radius"]

        if distance_squared <= radius_squared:
            return shape_id

    return None


# a click is only a request; the client never changes its own score
def send_shape_click(client_state, mouse_position):
    shape_id = find_clicked_shape(client_state, mouse_position)

    if shape_id is None or shape_id in client_state["pending_clicks"]:
        return False

    click_message = create_message("click", {"shape_id": shape_id})

    try:
        send_message(client_state["connection"], click_message)
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

    for shape in client_state["shapes"].values():
        if shape["points"] >= 0:
            shape_color = POSITIVE_COLOR
        else:
            shape_color = NEGATIVE_COLOR

        center = (shape["x"], shape["y"])
        pygame.draw.circle(surface, shape_color, center, shape["radius"])
        pygame.draw.circle(surface, TEXT_COLOR, center, shape["radius"], 3)

        points_text = fonts["shape"].render(
            str(shape["points"]),
            True,
            TEXT_COLOR,
        )
        points_rectangle = points_text.get_rect(center=center)
        surface.blit(points_text, points_rectangle)

    status_bar = pygame.Rect(20, SCREEN_HEIGHT - 52, SCREEN_WIDTH - 40, 34)
    pygame.draw.rect(surface, PANEL_COLOR, status_bar, border_radius=8)
    status_text = fonts["small"].render(
        client_state["status_message"],
        True,
        SECONDARY_TEXT_COLOR,
    )
    surface.blit(status_text, (status_bar.x + 12, status_bar.y + 7))


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
            send_shape_click(client_state, event.pos)


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

    while client_state["running"]:
        for event in pygame.event.get():
            handle_pygame_event(event, client_state)

        process_incoming_messages(client_state)

        if client_state["screen_name"] == "game":
            remove_expired_visual_shapes(client_state)

        draw_current_screen(surface, fonts, client_state)
        pygame.display.flip()
        clock.tick(FRAMES_PER_SECOND)

    disconnect_client(client_state)
    pygame.quit()
