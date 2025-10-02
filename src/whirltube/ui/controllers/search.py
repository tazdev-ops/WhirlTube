from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from gi.repository import Gtk, GLib

from ...history import add_search_term
from ...search_filters import normalize_search_filters
from ...util import save_settings

if TYPE_CHECKING:
    from ...providers.base import Provider

log = logging.getLogger(__name__)


def on_search_activate(
    entry: Gtk.SearchEntry,
    run_search_func: callable,
) -> None:
    """Handle search entry activation (Enter key)"""
    query = entry.get_text().strip()
    if not query:
        return
    add_search_term(query)
    run_search_func(query)


def run_search(
    query: str,
    provider: Provider,
    settings: dict,
    search_generation: int,
    show_loading_func: callable,
    show_error_func: callable,
    populate_results_func: callable,
    set_search_generation_func: callable,
    limit: int,
    last_filters: dict[str, str] | None,
    timed_func: callable,
    search_lock: threading.Lock | None = None,  # NEW PARAMETER
) -> None:
    """Execute the search query in a worker thread."""
    log.info("Searching: %s", query)
    show_loading_func(f"Searching: {query}", cancellable=True)

    with (search_lock if search_lock else threading.Lock()):
        gen = set_search_generation_func(search_generation + 1)
        current_gen = gen

    def worker() -> None:
        with timed_func(f"Search: {query}"):
            try:
                if last_filters:
                    order = last_filters.get('order')
                    duration = last_filters.get('duration')
                    period = last_filters.get('period')
                else:
                    # Normalize filters from settings to provider-friendly form
                    order, duration, period = normalize_search_filters(settings)
                
                results = provider.search(query, limit=limit, order=order, duration=duration, period=period)
            except Exception as e:
                log.exception("Search failed")
                GLib.idle_add(show_error_func, f"Search failed: {e}")
                return
        
        # Check if still the current search with lock
        if search_lock:
            with search_lock:
                if current_gen != settings.get("_search_generation", 0):
                    log.debug(f"Search '{query}' cancelled (generation mismatch: {current_gen} != {settings.get('_search_generation')})")
                    return
        else:
            if current_gen != settings.get("_search_generation", 0):
                log.debug(f"Search '{query}' cancelled (generation mismatch: {current_gen} != {settings.get('_search_generation')})")
                return
        
        GLib.idle_add(populate_results_func, results)

    threading.Thread(target=worker, daemon=True).start()


def filters_load_from_settings(
    settings: dict,
    dd_dur: Gtk.DropDown,
    dd_period: Gtk.DropDown,
    dd_order: Gtk.DropDown,
) -> None:
    """Load filter settings from config into the UI dropdowns."""
    dur = (settings.get("search_duration") or "any").lower()
    per = (settings.get("search_period") or "any").lower()
    ordv = (settings.get("search_order") or "relevance").lower()
    # Map to indices
    dur_idx = {"any":0, "short":1, "medium":2, "long":3}.get(dur, 0)
    per_idx = {"any":0, "today":1, "week":2, "month":3}.get(per, 0)
    ord_idx = {"relevance":0, "date":1, "views":2}.get(ordv, 0)
    try:
        dd_dur.set_selected(dur_idx)
        dd_period.set_selected(per_idx)
        dd_order.set_selected(ord_idx)
    except Exception as e:
        log.warning("Failed to load search filters from settings: %s", e)


def filters_apply(
    settings: dict,
    dd_dur: Gtk.DropDown,
    dd_period: Gtk.DropDown,
    dd_order: Gtk.DropDown,
    filters_pop: Gtk.Popover,
    search_entry: Gtk.SearchEntry,
    run_search_func: callable,
    set_last_filters_func: callable,
) -> None:
    """Apply filter selections, save to settings, and re-run search if active."""
    # Save UI selections into settings and persist
    dur_map = {0:"any", 1:"short", 2:"medium", 3:"long"}
    per_map = {0:"any", 1:"today", 2:"week", 3:"month"}
    ord_map = {0:"relevance", 1:"date", 2:"views"}
    
    duration = dur_map.get(dd_dur.get_selected(), "any")
    period = per_map.get(dd_period.get_selected(), "any")
    order = ord_map.get(dd_order.get_selected(), "relevance")
    
    settings["search_duration"] = duration
    settings["search_period"] = period
    settings["search_order"] = order
    save_settings(settings)
    filters_pop.popdown()
    
    # Persist to window instance for re-running search on view switch
    set_last_filters_func({
        'duration': duration,
        'period': period,
        'order': order,
    })
    
    # If there is a current query, re-run search with new filters
    try:
        q = (search_entry.get_text() or "").strip()
        if q:
            run_search_func(q)
    except Exception as e:
        log.error("Error applying filters and re-running search: %s", e)


def filters_clear(
    settings: dict,
    load_filters_func: callable,
    search_entry: Gtk.SearchEntry,
    run_search_func: callable,
) -> None:
    """Clear all search filters, save to settings, and re-run search if active."""
    settings["search_duration"] = "any"
    settings["search_period"] = "any"
    settings["search_order"] = "relevance"
    save_settings(settings)
    load_filters_func()
    # Optionally re-run current search after clearing
    try:
        q = (search_entry.get_text() or "").strip()
        if q:
            run_search_func(q)
    except Exception as e:
        log.error("Error clearing filters and re-running search: %s", e)