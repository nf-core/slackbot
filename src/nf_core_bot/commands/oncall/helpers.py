"""Shared helpers for on-call commands."""

from __future__ import annotations

import datetime


def monday_of_week(d: datetime.date) -> datetime.date:
    """Return the Monday of the ISO week containing *d*."""
    return d - datetime.timedelta(days=d.weekday())


def current_week_start() -> str:
    """Return the Monday of the current week as ``YYYY-MM-DD``."""
    return monday_of_week(datetime.date.today()).isoformat()


def today_iso() -> str:
    """Return today's date as ``YYYY-MM-DD``."""
    return datetime.date.today().isoformat()


def format_date_range(start: str, end: str) -> str:
    """Format an ISO date range as ``Apr 6 – Apr 12``."""
    s = datetime.date.fromisoformat(start)
    e = datetime.date.fromisoformat(end)
    return f"{s.strftime('%b %-d')} – {e.strftime('%b %-d')}"


def format_week_range(week_start: str) -> str:
    """Format a week as ``Apr 6 – Apr 12``."""
    end = (datetime.date.fromisoformat(week_start) + datetime.timedelta(days=6)).isoformat()
    return format_date_range(week_start, end)


def parse_date_arg(text: str) -> datetime.date:
    """Parse a ``YYYY-MM-DD`` string, raising *ValueError* on bad input."""
    try:
        return datetime.date.fromisoformat(text)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"`{text}` is not a valid date. Please use `YYYY-MM-DD` format.") from exc
