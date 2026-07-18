import time


MAX_STAMINA = 100
MIN_STAMINA = 0
CLICK_STAMINA_COST = 5
STAMINA_RECOVERY_AMOUNT = 10
STAMINA_RECOVERY_INTERVAL = 2
DEPLETED_STAMINA_LIMIT = 10
HIGH_STAMINA_LIMIT = 90
MAX_STRESS = 100
MIN_STRESS = 0
HIGH_STAMINA_STRESS_RECOVERY = 10
STRESS_RECOVERY_INTERVAL = 2


# this class owns stamina timing and keeps its value between zero and one hundred
class PlayerStamina:
    def __init__(self, initial_value=MAX_STAMINA, current_time=None):
        if not MIN_STAMINA <= initial_value <= MAX_STAMINA:
            raise ValueError("Stamina must be between 0 and 100.")

        if current_time is None:
            current_time = time.monotonic()

        self._value = initial_value
        self._last_update_time = current_time
        self._inactive_seconds = 0

    def update(self, current_time=None, frozen_until=0):
        if current_time is None:
            current_time = time.monotonic()

        if current_time < self._last_update_time:
            self._last_update_time = current_time
            return False

        active_start_time = self._last_update_time
        if active_start_time < frozen_until:
            active_start_time = min(current_time, frozen_until)

        active_seconds = current_time - active_start_time
        self._last_update_time = current_time

        if self._value >= MAX_STAMINA:
            self._inactive_seconds = 0
            return False

        self._inactive_seconds += active_seconds
        recovery_steps = int(
            self._inactive_seconds // STAMINA_RECOVERY_INTERVAL
        )

        if recovery_steps == 0:
            return False

        old_value = self._value
        recovered_stamina = recovery_steps * STAMINA_RECOVERY_AMOUNT
        self._value = min(MAX_STAMINA, self._value + recovered_stamina)
        used_seconds = recovery_steps * STAMINA_RECOVERY_INTERVAL
        self._inactive_seconds -= used_seconds

        if self._value == MAX_STAMINA:
            self._inactive_seconds = 0

        return self._value != old_value

    def get_value(self, current_time=None, frozen_until=0):
        self.update(current_time, frozen_until)
        return self._value

    def get_stored_value(self):
        return self._value

    def can_play(self, current_time=None, frozen_until=0):
        current_value = self.get_value(current_time, frozen_until)
        return current_value > DEPLETED_STAMINA_LIMIT

    def spend_for_click(
        self,
        stamina_cost=CLICK_STAMINA_COST,
        current_time=None,
        frozen_until=0,
    ):
        self.update(current_time, frozen_until)

        if stamina_cost <= 0:
            return self._value

        self._value = max(MIN_STAMINA, self._value - stamina_cost)
        self._inactive_seconds = 0
        return self._value

    def adjust_shape_points(self, points, current_time=None, frozen_until=0):
        current_value = self.get_value(current_time, frozen_until)

        if current_value < HIGH_STAMINA_LIMIT:
            return points

        if points > 0:
            return points * 2

        if points < 0:
            return points / 2

        return 0

    def get_level(self, current_time=None, frozen_until=0):
        current_value = self.get_value(current_time, frozen_until)

        if current_value >= HIGH_STAMINA_LIMIT:
            return "high"

        if current_value >= 60:
            return "normal"

        if current_value >= 40:
            return "darkened"

        if current_value > DEPLETED_STAMINA_LIMIT:
            return "limited_visibility"

        return "depleted"


# stress uses the same server clock and pauses during an ice effect
class PlayerStress:
    def __init__(self, initial_value=MIN_STRESS, current_time=None):
        if not MIN_STRESS <= initial_value <= MAX_STRESS:
            raise ValueError("Stress must be between 0 and 100.")

        if current_time is None:
            current_time = time.monotonic()

        self._value = initial_value
        self._last_update_time = current_time
        self._high_stamina_seconds = 0

    def update(
        self,
        stamina_value,
        current_time=None,
        frozen_until=0,
    ):
        if current_time is None:
            current_time = time.monotonic()

        if current_time < self._last_update_time:
            self._last_update_time = current_time
            return False

        active_start_time = self._last_update_time
        if active_start_time < frozen_until:
            active_start_time = min(current_time, frozen_until)

        active_seconds = current_time - active_start_time
        self._last_update_time = current_time

        if stamina_value < HIGH_STAMINA_LIMIT or self._value <= MIN_STRESS:
            self._high_stamina_seconds = 0
            return False

        self._high_stamina_seconds += active_seconds
        recovery_steps = int(
            self._high_stamina_seconds // STRESS_RECOVERY_INTERVAL
        )

        if recovery_steps == 0:
            return False

        old_value = self._value
        recovered_stress = recovery_steps * HIGH_STAMINA_STRESS_RECOVERY
        self._value = max(MIN_STRESS, self._value - recovered_stress)
        used_seconds = recovery_steps * STRESS_RECOVERY_INTERVAL
        self._high_stamina_seconds -= used_seconds

        if self._value == MIN_STRESS:
            self._high_stamina_seconds = 0

        return self._value != old_value

    def get_value(self):
        return self._value

    def change(self, stress_change):
        old_value = self._value
        self._value = max(
            MIN_STRESS,
            min(MAX_STRESS, self._value + stress_change),
        )
        return self._value != old_value

    def get_level(self):
        if self._value <= 10:
            return "calm"

        if self._value <= 30:
            return "slowed"

        if self._value <= 50:
            return "jumping"

        if self._value < 70:
            return "hallucinating"

        return "severe"

    def get_mouse_speed_multiplier(self):
        if self._value <= 10:
            return 1

        if self._value <= 50:
            return 0.85

        return 0.6

    def get_hallucination_interval(self):
        if self._value < 51:
            return None

        if self._value < 70:
            return 3

        return 1.5
