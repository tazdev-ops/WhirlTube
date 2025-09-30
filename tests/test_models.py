from __future__ import annotations

import pytest
from src.whirltube.models import Video

@pytest.mark.parametrize(
    "duration, expected",
    [
        (0, ""),
        (59, "0:59"),
        (60, "1:00"),
        (3599, "59:59"),
        (3600, "1:00:00"),
        (3661, "1:01:01"),
        (86399, "23:59:59"),
        (None, ""),
    ],
)
def test_video_duration_str(duration, expected):
    video = Video(
        id="test",
        title="test",
        url="test",
        channel=None,
        duration=duration,
        thumb_url=None,
    )
    assert video.duration_str == expected

@pytest.mark.parametrize(
    "kind, expected",
    [
        ("video", True),
        ("playlist", False),
        ("channel", False),
        ("comment", False),
        ("unknown", False),
    ],
)
def test_video_is_playable(kind, expected):
    video = Video(
        id="test",
        title="test",
        url="test",
        channel=None,
        duration=100,
        thumb_url=None,
        kind=kind,
    )
    assert video.is_playable == expected