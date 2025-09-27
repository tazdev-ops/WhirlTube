from whirltube.search_filters import normalize_search_filters


def test_normalize_defaults_to_none():
    s = {}
    order, duration, period = normalize_search_filters(s)
    assert order is None and duration is None and period is None


def test_normalize_any_and_relevance_become_none():
    s = {
        "search_order": "relevance",
        "search_duration": "any",
        "search_period": "any",
    }
    order, duration, period = normalize_search_filters(s)
    assert order is None and duration is None and period is None


def test_normalize_respects_values_case_insensitive():
    s = {
        "search_order": "DATE",
        "search_duration": "Short",
        "search_period": "Week",
    }
    order, duration, period = normalize_search_filters(s)
    assert order == "date" and duration == "short" and period == "week"


def test_normalize_passes_through_known_values():
    s = {
        "search_order": "views",
        "search_duration": "long",
        "search_period": "month",
    }
    assert normalize_search_filters(s) == ("views", "long", "month")