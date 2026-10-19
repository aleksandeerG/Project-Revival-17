# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

DEFAULT_STARTING_CREDITS = 1_000_000
DEFAULT_STARTING_POINTS = 10_000

DEFAULT_COIN_REWARD_MULTIPLIER = 25
DEFAULT_OFFLINE_COMPETITION_REWARD_MULTIPLIER = 15
DEFAULT_ONLINE_COMPETITION_REWARD_MULTIPLIER = 25

MAX_BALANCE = 2_147_483_647
MIN_MULTIPLIER = 1
MAX_MULTIPLIER = 1_000

# Set from the [economy] table of state/config.toml at startup; every reader
# looks these up at call time.
STARTING_CREDITS = DEFAULT_STARTING_CREDITS
STARTING_POINTS = DEFAULT_STARTING_POINTS
COIN_REWARD_MULTIPLIER = DEFAULT_COIN_REWARD_MULTIPLIER
OFFLINE_COMPETITION_REWARD_MULTIPLIER = DEFAULT_OFFLINE_COMPETITION_REWARD_MULTIPLIER
ONLINE_COMPETITION_REWARD_MULTIPLIER = DEFAULT_ONLINE_COMPETITION_REWARD_MULTIPLIER

REWARD_MODE_OFFLINE = "OFFLINE"
REWARD_MODE_ONLINE = "ONLINE"
REWARD_MODES = frozenset({REWARD_MODE_OFFLINE, REWARD_MODE_ONLINE})


def configure(*,
              starting_credits: int = DEFAULT_STARTING_CREDITS,
              starting_points: int = DEFAULT_STARTING_POINTS,
              coin_reward_multiplier: int = DEFAULT_COIN_REWARD_MULTIPLIER,
              offline_competition_reward_multiplier: int =
              DEFAULT_OFFLINE_COMPETITION_REWARD_MULTIPLIER,
              online_competition_reward_multiplier: int =
              DEFAULT_ONLINE_COMPETITION_REWARD_MULTIPLIER) -> None:
    global STARTING_CREDITS, STARTING_POINTS, COIN_REWARD_MULTIPLIER
    global OFFLINE_COMPETITION_REWARD_MULTIPLIER
    global ONLINE_COMPETITION_REWARD_MULTIPLIER
    for name, value in (("starting_credits", starting_credits),
                        ("starting_points", starting_points)):
        check_whole_number(name, value, 0, MAX_BALANCE)
    for name, value in (
            ("coin_reward_multiplier", coin_reward_multiplier),
            ("offline_competition_reward_multiplier",
             offline_competition_reward_multiplier),
            ("online_competition_reward_multiplier",
             online_competition_reward_multiplier)):
        check_whole_number(name, value, MIN_MULTIPLIER, MAX_MULTIPLIER)
    STARTING_CREDITS = starting_credits
    STARTING_POINTS = starting_points
    COIN_REWARD_MULTIPLIER = coin_reward_multiplier
    OFFLINE_COMPETITION_REWARD_MULTIPLIER = offline_competition_reward_multiplier
    ONLINE_COMPETITION_REWARD_MULTIPLIER = online_competition_reward_multiplier


def check_whole_number(name: str, value: object, low: int, high: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be a whole number, not %r" % (name, value))
    if not low <= value <= high:
        raise ValueError("%s must be between %d and %d, not %d"
                         % (name, low, high, value))


def coins(value: int) -> int:
    amount = int(value)
    return amount * COIN_REWARD_MULTIPLIER if amount > 0 else amount


def competition_coins(value: int, mode: str) -> int:
    reward_mode = str(mode or "").strip().upper()
    if reward_mode not in REWARD_MODES:
        raise ValueError("unknown competition reward mode: %s" % mode)
    amount = int(value)
    if amount <= 0:
        return amount
    multiplier = (ONLINE_COMPETITION_REWARD_MULTIPLIER
                  if reward_mode == REWARD_MODE_ONLINE
                  else OFFLINE_COMPETITION_REWARD_MULTIPLIER)
    return amount * multiplier
