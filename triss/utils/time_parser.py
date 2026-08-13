"""
triss.utils.time_parser
========================
Parses compact duration strings such as "10s", "5m", "2h" (also accepts
plain integers, treated as seconds) into an integer number of seconds.
Used by Auto Delete configuration.
"""

from __future__ import annotations

import re

_DURATION_RE = re.compile(r"^\s*(\d+)\s*(s|sec|secs|second|seconds|"
                           r"m|min|mins|minute|minutes|"
                           r"h|hr|hrs|hour|hours)?\s*$", re.IGNORECASE)

_UNIT_SECONDS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
}

MIN_SECONDS = 5
MAX_SECONDS = 7 * 24 * 3600  # 7 days ceiling — sane upper bound, not an arbitrary feature cap


def parse_duration_to_seconds(text: str) -> int | None:
    match = _DURATION_RE.match(text or "")
    if not match:
        return None
    value, unit = match.groups()
    unit = (unit or "s").lower()
    seconds = int(value) * _UNIT_SECONDS.get(unit, 1)
    if seconds < MIN_SECONDS or seconds > MAX_SECONDS:
        return None
    return seconds


def format_seconds(seconds: int) -> str:
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"
