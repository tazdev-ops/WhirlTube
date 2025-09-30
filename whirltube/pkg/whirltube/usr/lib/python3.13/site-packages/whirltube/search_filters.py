from __future__ import annotations

from typing import Any


def normalize_search_filters(settings: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """
    Convert persisted settings to provider-friendly values:
      - order: 'relevance' -> None else 'date'|'views'
      - duration: 'any' -> None else 'short'|'medium'|'long'
      - period: 'any' -> None else 'today'|'week'|'month'
    Returns (order, duration, period)
    """
    ordv = str(settings.get("search_order", "relevance") or "relevance").strip().lower()
    durv = str(settings.get("search_duration", "any") or "any").strip().lower()
    perv = str(settings.get("search_period", "any") or "any").strip().lower()

    order = None if ordv == "relevance" else ordv
    duration = None if durv == "any" else durv
    period = None if perv == "any" else perv
    return order, duration, period