"""Small time parsing helpers used by extraction and query planning."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

UTC = timezone.utc


def utc_now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def parse_time_ms(value: object, default_ms: int | None = None) -> int:
    if value is None:
        if default_ms is None:
            return utc_now_ms()
        return default_ms
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return int(datetime.fromisoformat(text).timestamp() * 1000)
        except ValueError:
            return default_ms if default_ms is not None else utc_now_ms()
    return default_ms if default_ms is not None else utc_now_ms()


def infer_time_window_ms(text: str, hints: dict[str, object], now_ms: int | None = None) -> tuple[int, int]:
    now = now_ms if now_ms is not None else utc_now_ms()
    if "start_ms" in hints or "end_ms" in hints:
        return parse_time_ms(hints.get("start_ms"), now - days_ms(90)), parse_time_ms(hints.get("end_ms"), now)

    lowered = text.lower()
    if "today" in lowered:
        current = datetime.fromtimestamp(now / 1000, tz=UTC)
        start = datetime(current.year, current.month, current.day, tzinfo=UTC)
        return int(start.timestamp() * 1000), now
    if "this week" in lowered:
        return now - days_ms(7), now
    if "last month" in lowered or "past month" in lowered:
        return now - days_ms(31), now
    if "last quarter" in lowered or "past quarter" in lowered:
        return now - days_ms(92), now

    match = re.search(r"(?:last|past)\s+(\d{1,3})\s+days?", lowered)
    if match:
        return now - days_ms(int(match.group(1))), now

    return now - days_ms(180), now


def days_ms(days: int) -> int:
    return int(timedelta(days=days).total_seconds() * 1000)
