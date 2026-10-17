from __future__ import annotations

import re

_PART = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)
_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
MAX_DURATION_SECONDS = 365 * 86400


def parse_duration(value: str) -> int:
    """Parse values such as '10 minutes', '2h 30m', or '1 day'."""
    raw = value.strip().lower()
    words = {
        "seconds": "s", "second": "s", "secs": "s", "sec": "s",
        "minutes": "m", "minute": "m", "mins": "m", "min": "m",
        "hours": "h", "hour": "h", "hrs": "h", "hr": "h",
        "days": "d", "day": "d", "weeks": "w", "week": "w",
    }
    for word, short in sorted(words.items(), key=lambda item: -len(item[0])):
        raw = re.sub(rf"(?<![a-z]){word}(?![a-z])", short, raw)
    raw = re.sub(r"\s+", "", raw)
    matches = list(_PART.finditer(raw))
    if not matches or "".join(m.group(0) for m in matches).lower() != raw:
        raise ValueError("Use a duration like 10m, 2h 30m, or 1 day.")
    seconds = sum(int(m.group(1)) * _SECONDS[m.group(2).lower()] for m in matches)
    if seconds < 10:
        raise ValueError("Duration must be at least 10 seconds.")
    if seconds > MAX_DURATION_SECONDS:
        raise ValueError("Duration cannot be longer than one year.")
    return seconds

