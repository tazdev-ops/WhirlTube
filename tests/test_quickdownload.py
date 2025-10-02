from unittest.mock import Mock, patch
import pytest
from src.whirltube.quickdownload import QuickDownloadWindow
from src.whirltube.util import _download_archive_path

# Mock GI objects and dependencies
@pytest.fixture
def mock_quick_download_window():
    # Mock the necessary GI objects and methods
    mock_window = Mock(spec=QuickDownloadWindow)
    mock_window.url_view = Mock()
    mock_window.entry_path_video = Mock()
    mock_window.entry_path_audio = Mock()
    mock_window.entry_ytdlp = Mock()
    mock_window.entry_cookies = Mock()
    mock_window.tabview = Mock()
    mock_window.dd_res = Mock()
    mock_window.dd_vidfmt = Mock()
    mock_window.dd_audfmt = Mock()
    mock_window.dd_audq = Mock()
    mock_window.chk_playlist = Mock()
    mock_window.dd_sb = Mock()
    
    # Mock settings
    mock_window.settings = {
        "download_template": "%(title)s_CUSTOM.%(ext)s",
        "quick_video_dir": "/tmp/video",
        "http_proxy": "http://test-proxy:8080",
        "sb_skip_categories": "sponsor,music_offtopic",
    }
    
    # Mock UI elements
    mock_window.url_view.get_buffer.return_value.get_text.return_value = """https://test.com/video1
https://test.com/video2"""
    mock_window.entry_path_video.get_text.return_value = "/tmp/video"
    mock_window.entry_path_audio.get_text.return_value = "/tmp/audio"
    mock_window.entry_ytdlp.get_text.return_value = "/usr/bin/yt-dlp"
    mock_window.entry_cookies.get_text.return_value = ""
    
    # Mock tab view state (Video tab selected)
    mock_page = Mock()
    mock_page.get_title.return_value = "Video"
    mock_window.tabview.get_selected_page.return_value = mock_page
    
    # Mock dropdowns for Video tab (1080p, mp4)
    mock_window.dd_res.get_selected.return_value = 2 # 1080
    mock_window.dd_vidfmt.get_selected.return_value = 0 # mp4
    
    # Mock checkboxes
    mock_window.chk_playlist.get_active.return_value = False
    mock_window.dd_sb.get_selected.return_value = 2 # Remove (default)
    
    # Mock runner and progress
    mock_window.runner = Mock()
    mock_window.progress = Mock()
    mock_window._set_msg = Mock()
    
    # Attach the actual _on_download method for testing
    # We need to patch Path.exists() for the directory check
    with patch('src.whirltube.quickdownload.Path') as MockPath:
        MockPath.return_value.exists.return_value = True
        # We need to patch save_settings to prevent side effects
        with patch('src.whirltube.quickdownload.save_settings'):
            # We need to patch GLib.idle_add and threading.Thread to prevent blocking/errors
            with patch('src.whirltube.quickdownload.GLib.idle_add'), \
                 patch('src.whirltube.quickdownload.threading.Thread'):
                # Call the actual method
                QuickDownloadWindow._on_download(mock_window)

    return mock_window

def test_quick_args_parity_and_template(mock_quick_download_window):
    """
    Validate that _on_download generates the correct args for:
    - Archive/resume/no-overwrites (Task 2)
    - Custom filename template (Task 3)
    - Proxy (Task 6 - implicitly tested by proxy being in settings)
    - SponsorBlock categories (Task 5)
    - Concurrency -N 4 (Task 2)
    """
    mock_window = mock_quick_download_window
    
    # The args list is the first argument to runner.start
    args = mock_window.runner.start.call_args[0][0]
    
    # 1. Check Parity Arguments (Task 2)
    archive_path = str(_download_archive_path())
    assert "--download-archive" in args
    assert args[args.index("--download-archive") + 1] == archive_path
    assert "--no-overwrites" in args
    assert "--continue" in args
    assert "--retries" in args and args[args.index("--retries") + 1] == "3"
    assert "--fragment-retries" in args and args[args.index("--fragment-retries") + 1] == "2"
    assert "-N" in args and args[args.index("-N") + 1] == "4"
    
    # 2. Check Filename Template (Task 3)
    assert "-o" in args
    # Should use the custom template from settings
    assert args[args.index("-o") + 1] == "%(title)s_CUSTOM.%(ext)s"
    
    # 3. Check Proxy (Implicit Task 6 check)
    assert "--proxy" in args
    assert args[args.index("--proxy") + 1] == "http://test-proxy:8080"
    
    # 4. Check SponsorBlock (Task 5)
    assert "--sponsorblock-remove" in args
    assert args[args.index("--sponsorblock-remove") + 1] == "sponsor,music_offtopic"
    assert "--sponsorblock-mark" not in args
    
    # 5. Check Video URLs
    assert args[-2:] == ["https://test.com/video1", "https://test.com/video2"]

def test_quick_args_playlist_mode():
    """Validate that playlist mode uses the playlist template and correct flags."""
    mock_window = Mock(spec=QuickDownloadWindow)
    mock_window.url_view = Mock()
    mock_window.entry_path_video = Mock()
    mock_window.entry_path_audio = Mock()
    mock_window.entry_ytdlp = Mock()
    mock_window.entry_cookies = Mock()
    mock_window.tabview = Mock()
    mock_window.dd_res = Mock()
    mock_window.dd_vidfmt = Mock()
    mock_window.dd_audfmt = Mock()
    mock_window.dd_audq = Mock()
    mock_window.chk_playlist = Mock()
    mock_window.dd_sb = Mock()
    
    mock_window.settings = {"download_template": "%(title)s_CUSTOM.%(ext)s"}
    mock_window.url_view.get_buffer.return_value.get_text.return_value = "https://test.com/playlist"
    mock_window.entry_path_video.get_text.return_value = "/tmp/video"
    mock_window.entry_path_audio.get_text.return_value = "/tmp/audio"
    mock_window.entry_ytdlp.get_text.return_value = "/usr/bin/yt-dlp"
    mock_window.entry_cookies.get_text.return_value = ""
    mock_page = Mock()
    mock_page.get_title.return_value = "Video"
    mock_window.tabview.get_selected_page.return_value = mock_page
    mock_window.dd_res.get_selected.return_value = 2
    mock_window.dd_vidfmt.get_selected.return_value = 0
    mock_window.chk_playlist.get_active.return_value = True # <--- Playlist mode ON
    mock_window.dd_sb.get_selected.return_value = 0
    mock_window.runner = Mock()
    mock_window.progress = Mock()
    mock_window._set_msg = Mock()
    
    with patch('src.whirltube.quickdownload.Path') as MockPath:
        MockPath.return_value.exists.return_value = True
        with patch('src.whirltube.quickdownload.save_settings'):
            with patch('src.whirltube.quickdownload.GLib.idle_add'), \
                 patch('src.whirltube.quickdownload.threading.Thread'):
                QuickDownloadWindow._on_download(mock_window)

    args = mock_window.runner.start.call_args[0][0]
    
    # Should use playlist template
    assert "-o" in args
    assert args[args.index("-o") + 1] == "%(playlist)s/%(title)s.%(ext)s"
    
    # Should have --yes-playlist
    assert "--yes-playlist" in args
    
    # Should NOT have --no-playlist or --match-filter !playlist
    assert "--no-playlist" not in args
    assert "--match-filter" not in args
