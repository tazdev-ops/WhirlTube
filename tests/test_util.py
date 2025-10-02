from __future__ import annotations

import pytest
from unittest.mock import patch
from pathlib import Path
from src.whirltube.util import safe_httpx_proxy, is_valid_youtube_url, xdg_config_dir, xdg_data_dir, xdg_cache_dir

@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.youtube.com/watch?v=ID", True),
        ("http://youtu.be/ID", True),
        ("https://www.youtube.com/shorts/ID", True),
        ("https://www.youtube.com/embed/ID", True),
        ("https://invidious.example.com/watch?v=ID", False), # Allowed by default
        ("https://example.com/video", False),
        ("ftp://youtube.com/watch?v=ID", False),
        ("", False),
        (None, False),
    ],
)
def test_is_valid_youtube_url_core(url, expected):
    # Test core YouTube hosts
    assert is_valid_youtube_url(url) == expected

@pytest.mark.parametrize(
    "url, allowed_hosts, expected",
    [
        ("https://myinvidious.net/watch?v=ID", ["myinvidious.net"], True),
        ("https://www.myinvidious.net/watch?v=ID", ["myinvidious.net"], True),
        ("https://sub.myinvidious.net/watch?v=ID", ["myinvidious.net"], True),
        ("https://other.net/watch?v=ID", ["myinvidious.net"], False),
        ("https://www.youtube.com/watch?v=ID", ["myinvidious.net"], True), # Core hosts always allowed
    ],
)
def test_is_valid_youtube_url_allowed_hosts(url, allowed_hosts, expected):
    # Test with explicit allowed hosts (e.g., Invidious instances)
    assert is_valid_youtube_url(url, allowed_hosts) == expected

@pytest.mark.parametrize(
    "proxy_str, expected",
    [
        ("http://127.0.0.1:8080", "http://127.0.0.1:8080"),
        ("socks5://user:pass@host:1080", "socks5://user:pass@host:1080"),
        ("https://proxy.com", "https://proxy.com"),
        ("socks5h://host:1080", "socks5h://host:1080"),
        ("ftp://bad.com", None),
        ("127.0.0.1:8080", None), # Missing scheme
        ("http://", None), # Missing netloc
        ("", None),
        (None, None),
    ],
)
def test_safe_httpx_proxy(proxy_str, expected):
    assert safe_httpx_proxy(proxy_str) == expected

@patch("src.whirltube.util.Path.home", return_value=Path("/home/testuser"))
@patch("src.whirltube.util.os.environ", {"XDG_CONFIG_HOME": "/tmp/config"})
def test_xdg_config_dir_with_env(mock_env, mock_home, tmp_path):
    # Mock Path.mkdir to avoid actual FS changes in tests
    with patch("src.whirltube.util.Path.mkdir") as mock_mkdir:
        result = xdg_config_dir()
        assert result == Path("/tmp/config/whirltube")
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

@patch("src.whirltube.util.Path.home", return_value=Path("/home/testuser"))
@patch("src.whirltube.util.os.environ", {})
def test_xdg_data_dir_default(mock_home, mock_env, tmp_path):
    with patch("src.whirltube.util.Path.mkdir"):
        result = xdg_data_dir()
        assert result == Path("/home/testuser/.local/share/whirltube")

@patch("src.whirltube.util.Path.home", return_value=Path("/home/testuser"))
@patch("src.whirltube.util.os.environ", {"XDG_CACHE_HOME": "/tmp/cache"})
def test_xdg_cache_dir_with_env(mock_env, mock_home, tmp_path):
    with patch("src.whirltube.util.Path.mkdir"):
        result = xdg_cache_dir()
        assert result == Path("/tmp/cache/whirltube")