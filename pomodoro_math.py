"""Pomodoro stage arithmetic (StudyLion's timer model).

The whole cycle derives from a single `last_started` anchor: stage and
boundaries are pure functions of wall-clock time, so a timer survives bot
restarts by construction. Unit-tested in tests/test_pomodoro_math.py.
"""
from datetime import datetime, timedelta


def current_stage(
    last_started: datetime, focus_seconds: int, break_seconds: int, now: datetime
) -> tuple[str, datetime, datetime]:
    """Return ("focus" | "break", stage_start, stage_end) for the given moment.

    The timer loops focus→break forever; at exactly the focus boundary the
    stage is "break".
    """
    interval = focus_seconds + break_seconds
    elapsed = int((now - last_started).total_seconds())
    cycles, offset = divmod(elapsed, interval)
    cycle_start = last_started + timedelta(seconds=cycles * interval)
    if offset < focus_seconds:
        return "focus", cycle_start, cycle_start + timedelta(seconds=focus_seconds)
    return (
        "break",
        cycle_start + timedelta(seconds=focus_seconds),
        cycle_start + timedelta(seconds=interval),
    )
