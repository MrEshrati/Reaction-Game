import random
import time
from abc import ABC, abstractmethod


NORMAL_POINTS = [-3, -2, -1, 1, 2, 3, 4, 5, 6]
SHIELD_DURATION = 5
ICE_DURATION = 3


# every shape stores common data and defines its own type through polymorphism
class Shape(ABC):
    def __init__(
        self,
        shape_id,
        name,
        x_position,
        y_position,
        radius,
        points,
        lifetime,
        created_at=None,
    ):
        if radius <= 0:
            raise ValueError("A shape radius must be positive.")

        if lifetime <= 0:
            raise ValueError("A shape lifetime must be positive.")

        if created_at is None:
            created_at = time.monotonic()

        self._shape_id = shape_id
        self._name = name
        self._x_position = x_position
        self._y_position = y_position
        self._radius = radius
        self._points = points
        self._lifetime = lifetime
        self._created_at = created_at
        self._expires_at = created_at + lifetime

    @abstractmethod
    def get_shape_type(self):
        pass

    def get_id(self):
        return self._shape_id

    def get_name(self):
        return self._name

    def get_position(self):
        return self._x_position, self._y_position

    def get_radius(self):
        return self._radius

    def get_points(self):
        return self._points

    def get_lifetime(self):
        return self._lifetime

    def get_expires_at(self):
        return self._expires_at

    def is_expired(self, current_time=None):
        if current_time is None:
            current_time = time.monotonic()

        return current_time >= self._expires_at

    def is_visible_to(self, player_id):
        return True

    def contains_point(self, x_position, y_position):
        x_distance = x_position - self._x_position
        y_distance = y_position - self._y_position
        distance_squared = x_distance * x_distance + y_distance * y_distance
        radius_squared = self._radius * self._radius
        return distance_squared <= radius_squared

    def get_click_result(self):
        return {
            "points": self._points,
            "effect": None,
            "stamina_cost": 5,
            "stress_change": 0,
        }

    def get_spawn_data(self):
        return {
            "shape_id": self._shape_id,
            "shape_type": self.get_shape_type(),
            "name": self._name,
            "x": self._x_position,
            "y": self._y_position,
            "radius": self._radius,
            "points": self._points,
            "lifetime": self._lifetime,
        }


class NormalShape(Shape):
    def __init__(
        self,
        shape_id,
        x_position,
        y_position,
        radius,
        points,
        lifetime,
        created_at=None,
    ):
        if points not in NORMAL_POINTS:
            raise ValueError("A normal shape needs a score from -3 to -1 or 1 to 6.")

        Shape.__init__(
            self,
            shape_id,
            "Normal",
            x_position,
            y_position,
            radius,
            points,
            lifetime,
            created_at,
        )

    def get_shape_type(self):
        return "normal"

    def get_score_category(self):
        if self._points < 0:
            return "negative"

        if self._points <= 2:
            return "low"

        return "high"

    def get_click_result(self):
        click_result = Shape.get_click_result(self)
        score_category = self.get_score_category()

        if score_category == "negative":
            click_result["stress_change"] = 30
        elif score_category == "low":
            click_result["stress_change"] = 10
        else:
            click_result["stress_change"] = -5

        return click_result


class ShieldShape(Shape):
    def __init__(
        self,
        shape_id,
        x_position,
        y_position,
        radius,
        lifetime,
        effect_duration=SHIELD_DURATION,
        created_at=None,
    ):
        Shape.__init__(
            self,
            shape_id,
            "Shield",
            x_position,
            y_position,
            radius,
            0,
            lifetime,
            created_at,
        )
        self._effect_duration = effect_duration

    def get_shape_type(self):
        return "shield"

    def get_click_result(self):
        return {
            "points": 0,
            "effect": {
                "type": "shield",
                "duration": self._effect_duration,
            },
            "stamina_cost": 0,
            "stress_change": 0,
        }

    def get_spawn_data(self):
        spawn_data = Shape.get_spawn_data(self)
        spawn_data["effect_duration"] = self._effect_duration
        return spawn_data


class IceShape(Shape):
    def __init__(
        self,
        shape_id,
        x_position,
        y_position,
        radius,
        lifetime,
        effect_duration=ICE_DURATION,
        created_at=None,
    ):
        Shape.__init__(
            self,
            shape_id,
            "Ice",
            x_position,
            y_position,
            radius,
            0,
            lifetime,
            created_at,
        )
        self._effect_duration = effect_duration

    def get_shape_type(self):
        return "ice"

    def get_click_result(self):
        return {
            "points": 0,
            "effect": {
                "type": "ice",
                "duration": self._effect_duration,
            },
            "stamina_cost": 5,
            "stress_change": 0,
        }

    def get_spawn_data(self):
        spawn_data = Shape.get_spawn_data(self)
        spawn_data["effect_duration"] = self._effect_duration
        return spawn_data


# a hallucination follows normal scoring but is visible to only one player
class HallucinationShape(NormalShape):
    def __init__(
        self,
        shape_id,
        x_position,
        y_position,
        radius,
        points,
        lifetime,
        visible_to_player,
        created_at=None,
    ):
        NormalShape.__init__(
            self,
            shape_id,
            x_position,
            y_position,
            radius,
            points,
            lifetime,
            created_at,
        )
        self._name = "Hallucination"
        self._visible_to_player = visible_to_player

    def get_shape_type(self):
        return "hallucination"

    def is_visible_to(self, player_id):
        return player_id == self._visible_to_player

    def get_click_result(self):
        click_result = NormalShape.get_click_result(self)
        click_result["points"] = 0
        return click_result

    def get_spawn_data(self):
        spawn_data = NormalShape.get_spawn_data(self)
        spawn_data["visible_to_player"] = self._visible_to_player
        return spawn_data


# the server uses this factory without caring which concrete class is returned
def create_random_shape(
    shape_id,
    screen_width,
    screen_height,
    lifetime,
):
    x_position = random.randint(60, screen_width - 60)
    y_position = random.randint(120, screen_height - 60)
    radius = 30
    shape_roll = random.randint(1, 100)

    if shape_roll <= 70:
        points = random.choice(NORMAL_POINTS)
        return NormalShape(
            shape_id,
            x_position,
            y_position,
            radius,
            points,
            lifetime,
        )

    if shape_roll <= 85:
        return ShieldShape(
            shape_id,
            x_position,
            y_position,
            radius,
            lifetime,
        )

    return IceShape(
        shape_id,
        x_position,
        y_position,
        radius,
        lifetime,
    )


# hallucinations look normal but are sent only to the stressed player
def create_hallucination_shape(
    shape_id,
    screen_width,
    screen_height,
    lifetime,
    visible_to_player,
):
    x_position = random.randint(60, screen_width - 60)
    y_position = random.randint(120, screen_height - 60)
    points = random.choice(NORMAL_POINTS)
    return HallucinationShape(
        shape_id,
        x_position,
        y_position,
        30,
        points,
        lifetime,
        visible_to_player,
    )


# the client reconstructs the correct concrete class from server message data
def shape_from_message(message_data):
    shape_type = message_data["shape_type"]
    shape_id = message_data["shape_id"]
    x_position = message_data["x"]
    y_position = message_data["y"]
    radius = message_data["radius"]
    lifetime = message_data["lifetime"]

    if shape_type == "normal":
        return NormalShape(
            shape_id,
            x_position,
            y_position,
            radius,
            message_data["points"],
            lifetime,
        )

    if shape_type == "shield":
        return ShieldShape(
            shape_id,
            x_position,
            y_position,
            radius,
            lifetime,
            message_data.get("effect_duration", SHIELD_DURATION),
        )

    if shape_type == "ice":
        return IceShape(
            shape_id,
            x_position,
            y_position,
            radius,
            lifetime,
            message_data.get("effect_duration", ICE_DURATION),
        )

    if shape_type == "hallucination":
        return HallucinationShape(
            shape_id,
            x_position,
            y_position,
            radius,
            message_data["points"],
            lifetime,
            message_data["visible_to_player"],
        )

    raise ValueError("Unknown shape type: " + str(shape_type))
