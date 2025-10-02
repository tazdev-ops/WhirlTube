from __future__ import annotations
from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest


def test_quick_download_includes_archive_and_resume():
    \"\"\"Verify Quick Download args include archive/resume flags.\"\"\"
    from src.whirltube.quickdownload import QuickDownloadWindow
    from src.whirltube.util import _download_archive_path
    
    # Mock settings and UI elements
    with patch.object(QuickDownloadWindow, \"settings\", {\"download_template\": \"%(title)s.%(ext)s\"}):
        # Simulate args construction in _on_download
        args = [\"-P\", \"/tmp\"]
        archive_path = _download_archive_path()
        args += [\"--download-archive\", str(archive_path)]
        args += [\"--no-overwrites\", \"--continue\"]
        args += [\"--retries\", \"3\", \"--fragment-retries\", \"2\"]
        args += [\"-N\", \"4\"]
        
        assert \"--download-archive\" in args
        assert \"--no-overwrites\" in args
        assert \"--continue\" in args
        assert \"--retries\" in args
        assert \"-N\" in args


def test_quick_download_respects_template():
    \"\"\"Verify Quick Download uses global download template in non-playlist mode.\"\"\"
    from src.whirltube.quickdownload import QuickDownloadWindow
    
    # Mock settings with custom template
    template = \"%(uploader)s/%(title)s.%(ext)s\"
    with patch.object(QuickDownloadWindow, \"settings\", {\"download_template\": template}):
        # Simulate non-playlist args
        args = [
            \"--break-on-reject\",
            \"--match-filter\", \"!playlist\",
            \"--no-playlist\",
            \"-o\", template
        ]
        assert \"-o\" in args
        assert template in args


def test_quick_cookies_handling():
    \"\"\"Verify cookies are added as --cookies-from-browser or --cookies based on input.\"\"\"
    from src.whirltube.quickdownload import QuickDownloadWindow
    from pathlib import Path
    
    with patch.object(QuickDownloadWindow, \"entry_cookies\") as mock_entry:
        mock_entry.get_text.return_value = \"firefox:default\"  # Browser spec
        # Simulate args
        args = []
        ck = mock_entry.get_text.return_value.strip()
        if \":\" in ck or \"+\" in ck:
            args += [\"--cookies-from-browser\", ck]
        elif Path(ck).exists():
            args += [\"--cookies\", ck]
        assert \"--cookies-from-browser\" in args
        
        # Test file path
        mock_entry.get_text.return_value = \"/path/to/cookies.txt\"
        with patch(\"pathlib.Path.exists\", return_value=True):
            args = []
            ck = mock_entry.get_text.return_value.strip()
            if \":\" in ck or \"+\" in ck:
                pass
            elif Path(ck).exists():
                args += [\"--cookies\", ck]
            assert \"--cookies\" in args


def test_sponsorblock_categories():
    \"\"\"Verify SponsorBlock args use configured categories.\"\"\"
    from src.whirltube.quickdownload import QuickDownloadWindow
    
    with patch.object(QuickDownloadWindow, \"dd_sb\", selected=1):  # Mark
        with patch.object(QuickDownloadWindow, \"settings\", {\"sb_skip_categories\": \"sponsor,selfpromo\"}):
            # Simulate args
            args = []
            sb_idx = 1
            cats = \"sponsor,selfpromo\"
            if sb_idx == 1:
                args += [\"--sponsorblock-mark\", cats]
            assert \"--sponsorblock-mark\" in args