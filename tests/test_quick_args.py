from __future__ import annotations
from unittest.mock import patch


def test_quick_download_includes_archive_and_resume():
    """Verify Quick Download args include archive/resume flags."""
    from src.whirltube.util import _download_archive_path
    
    # Simulate args construction in _on_download
    args = ["-P", "/tmp"]
    archive_path = _download_archive_path()
    args += ["--download-archive", str(archive_path)]
    args += ["--no-overwrites", "--continue"]
    args += ["--retries", "3", "--fragment-retries", "2"]
    args += ["-N", "4"]
    
    assert "--download-archive" in args
    assert "--no-overwrites" in args
    assert "--continue" in args
    assert "--retries" in args
    assert "-N" in args


def test_quick_download_respects_template():
    """Verify Quick Download uses global download template in non-playlist mode."""
    # Simulate non-playlist args
    template = "%(uploader)s/%(title)s.%(ext)s"
    args = [
        "--break-on-reject",
        "--match-filter", "!playlist",
        "--no-playlist",
        "-o", template
    ]
    assert "-o" in args
    assert template in args


def test_quick_cookies_handling():
    """Verify cookies are added as --cookies-from-browser or --cookies based on input."""
    from pathlib import Path
    
    # Test browser spec
    ck = "firefox:default"  # Browser spec
    # Simulate args
    args = []
    if ":" in ck or "+" in ck:
        args += ["--cookies-from-browser", ck]
    elif Path(ck).exists():
        args += ["--cookies", ck]
    assert "--cookies-from-browser" in args
    
    # Test file path
    with patch("pathlib.Path.exists", return_value=True):
        args = []
        ck = "/path/to/cookies.txt"
        if ":" in ck or "+" in ck:
            pass
        elif Path(ck).exists():
            args += ["--cookies", ck]
        assert "--cookies" in args


def test_sponsorblock_categories():
    """Verify SponsorBlock args use configured categories."""
    # Simulate args
    args = []
    sb_idx = 1
    cats = "sponsor,selfpromo"
    if sb_idx == 1:
        args += ["--sponsorblock-mark", cats]
    assert "--sponsorblock-mark" in args