import datetime
import hashlib
import math
import random

from monty.database import Rollout


def update_counts_to_time(rollout: Rollout, current_time: datetime.datetime) -> tuple[int, int]:
    """Calculate the new rollout hash levels for the current time, in relation the scheduled time."""
    if rollout.rollout_by is None:
        raise RuntimeError("rollout must have rollout_by set.")

    # if the current time is after rollout_by, return the current values
    if rollout.rollout_by < current_time:
        return rollout.rollout_hash_low, rollout.rollout_hash_high

    # if we're within a 5 minute range complete the rollout
    if abs(rollout.rollout_by - current_time) < datetime.timedelta(minutes=5):
        return find_new_hash_levels(rollout, goal_percent=rollout.rollout_to_percent)

    old_level = compute_current_percent(rollout) * 100
    goal = rollout.rollout_to_percent
    seconds_elapsed = (current_time - rollout.hashes_last_updated).total_seconds()
    total_seconds = (rollout.rollout_by - rollout.hashes_last_updated).total_seconds()

    new_diff = round(seconds_elapsed / (total_seconds) * (goal - old_level), 2)
    return find_new_hash_levels(rollout, new_diff + old_level)


def compute_current_percent(rollout: Rollout) -> float:
    """Computes the current rollout percentage."""
    return (rollout.rollout_hash_high - rollout.rollout_hash_low) / 10_000


def find_new_hash_levels(rollout: Rollout, goal_percent: float) -> tuple[int, int]:
    """Calcuate the new hash levels from the provided goal percentage."""
    # the goal_percent comes as 0 to 100, instead of 0 to 1.
    goal_percent = round(goal_percent / 100, 5)
    high: float = rollout.rollout_hash_high
    low: float = rollout.rollout_hash_low

    # this is the goal result of hash_high minus hash_low
    needed_difference = math.floor(goal_percent * 10_000)
    current_difference = high - low

    if current_difference > needed_difference:
        raise RuntimeError("the current percent is above the new goal percent.")

    if current_difference == needed_difference:
        # shortcut and return the existing values
        return low, high

    # difference is the total amount that needs to be added to the range right now
    difference = needed_difference - current_difference

    if low == 0:
        # can't change the low hash at all, so we just change the high hash
        high += difference
        return low, high

    if high == 10_000:
        # can't change the high hash at all, so we just change the low hash
        low -= difference
        return low, high

    # do some math to compute adding a random amount to each
    add_to_low = min(random.choice(range(0, difference, 50)), low)

    difference -= add_to_low
    low -= add_to_low
    high += difference

    return low, high


def is_rolled_out_to(id: int, *, rollout: Rollout, include_rollout_id: bool = True) -> bool:
    """
    Check if the provided rollout is rolled out to the provided Discord ID.

    This method hashes the rollout name with the ID and checks if the result
    is within hash_low and hash_high.
    """
    to_hash = rollout.name + ":" + str(id)
    if include_rollout_id:
        to_hash = str(rollout.id) + ":" + to_hash

    hash = hashlib.sha256(to_hash.encode()).hexdigest()
    hash_int = int(hash, 16)
    is_enabled = (hash_int % 10_000) in range(rollout.rollout_hash_low, rollout.rollout_hash_high)

    return is_enabled
