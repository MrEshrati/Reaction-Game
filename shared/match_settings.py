DEFAULT_MATCH_DURATION = 15
MIN_MATCH_DURATION = 10
MAX_MATCH_DURATION = 300


def is_valid_match_duration(duration):
    if type(duration) is not int:
        return False

    return MIN_MATCH_DURATION <= duration <= MAX_MATCH_DURATION
