"""Shared helpers for on-call commands."""

from __future__ import annotations

import datetime


def monday_of_week(d: datetime.date) -> datetime.date:
    """Return the Monday of the ISO week containing *d*."""
    return d - datetime.timedelta(days=d.weekday())


def current_week_start() -> str:
    """Return the Monday of the current week as ``YYYY-MM-DD``."""
    return monday_of_week(datetime.date.today()).isoformat()


def format_week_range(week_start: str) -> str:
    """Format a week as ``Apr 6 – Apr 12``."""
    start = datetime.date.fromisoformat(week_start)
    end = start + datetime.timedelta(days=6)
    return f"{start.strftime('%b %-d')} – {end.strftime('%b %-d')}"


def parse_date_arg(text: str) -> datetime.date:
    """Parse a ``YYYY-MM-DD`` string, raising *ValueError* on bad input."""
    try:
        return datetime.date.fromisoformat(text)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"`{text}` is not a valid date. Please use `YYYY-MM-DD` format.") from exc
