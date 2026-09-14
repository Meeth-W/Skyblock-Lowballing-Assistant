"""Timestamp helpers.

Everything stored in the ledger is an ISO-8601 UTC string with millisecond
precision and a trailing ``Z``.  That format sorts lexicographically, which is
what the event log relies on for ordering ties.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

ISO_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_iso(dt: datetime) -> str:
    """Render a datetime as ``2026-09-13T10:30:00.123Z``."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime(ISO_FMT)[:-3] + "Z"


def now_iso() -> str:
    return to_iso(utcnow())


def from_iso(text: str) -> datetime:
    """Parse anything the app or the mod might emit, including bare ``Z``."""
    cleaned = text.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    return datetime.fromisoformat(cleaned).astimezone(UTC)


def iso_days_ago(days: float) -> str:
    return to_iso(utcnow() - timedelta(days=days))


def age_seconds(iso_ts: str, *, now: datetime | None = None) -> float:
    return ((now or utcnow()) - from_iso(iso_ts)).total_seconds()


def age_days(iso_ts: str, *, now: datetime | None = None) -> float:
    return age_seconds(iso_ts, now=now) / 86_400.0


def format_duration(seconds: float) -> str:
    """``~4h 20m`` style, matching the sell-time readout in the valuation pane."""
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return f"{int(round(seconds))}s"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{int(round(minutes))}m"
    hours = int(minutes // 60)
    rem_min = int(round(minutes - hours * 60))
    if rem_min == 60:
        hours, rem_min = hours + 1, 0
    if hours < 24:
        return f"{hours}h {rem_min}m" if rem_min else f"{hours}h"
    days = hours // 24
    rem_h = hours % 24
    return f"{days}d {rem_h}h" if rem_h else f"{days}d"
