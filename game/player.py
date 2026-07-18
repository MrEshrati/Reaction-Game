import time


MAX_STAMINA = 100
MIN_STAMINA = 0
CLICK_STAMINA_COST = 5
STAMINA_RECOVERY_AMOUNT = 10
STAMINA_RECOVERY_INTERVAL = 2
DEPLETED_STAMINA_LIMIT = 10
HIGH_STAMINA_LIMIT = 90


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
