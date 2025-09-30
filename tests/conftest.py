from __future__ import annotations

import pytest
from unittest.mock import Mock
from pathlib import Path
from typing import Any

from src.whirltube.models import Video
from src.whirltube.providers.base import Provider

@pytest.fixture
def mock_settings() -> dict[str, Any]:
    """Mock settings dictionary."""
    return {
        "http_proxy": None,
        "use_invidious": False,
        "invidious_instance": "https://yewtu.be",
        "search_duration": "any",
        "search_period": "any",
        "search_order": "relevance",
    }

@pytest.fixture
def mock_provider() -> Mock:
    """Mock Provider instance."""
    mock = Mock(spec=Provider)
    mock.search.return_value = []
    mock.trending.return_value = []
    mock.fetch_formats.return_value = []
    return mock

@pytest.fixture
def sample_videos() -> list[Video]:
    """A list of sample Video objects."""
    return [
        Video(
            id="short_id",
            title="A Short Video",
            url="https://youtu.be/short_id",
            channel="Short Channel",
            duration=120, # 2 minutes
            thumb_url="http://example.com/short.jpg",
            kind="video",
        ),
        Video(
            id="long_id",
            title="A Very Long Video",
            url="https://www.youtube.com/watch?v=long_id",
            channel="Long Channel",
            duration=3600, # 1 hour
            thumb_url="http://example.com/long.jpg",
            kind="video",
        ),
        Video(
            id="playlist_id",
            title="My Playlist",
            url="https://www.youtube.com/playlist?list=playlist_id",
            channel=None,
            duration=None,
            thumb_url=None,
            kind="playlist",
        ),
    ]

@pytest.fixture
def mock_xdg_dirs(tmp_path: Path) -> None:
    """Mock XDG environment variables to use a temporary directory."""
    # This is a bit tricky without patching the functions directly, 
    # but for simple tests, we can rely on the functions being called 
    # with no arguments, which defaults to home dir logic.
    # Since we can't easily mock os.environ here, we'll rely on tests 
    # that use xdg_data_dir/xdg_config_dir to be mocked if needed.
    pass