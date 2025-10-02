from __future__ import annotations

from src.whirltube.dialogs import DownloadOptions
from pathlib import Path

def test_download_options_default_to_ydl_opts():
    opts = DownloadOptions()
    ydl_opts = opts.to_ydl_opts()
    assert ydl_opts["format"] == "bv*+ba/b"
    assert ydl_opts["quiet"] is True
    assert "writesubtitles" not in ydl_opts

def test_download_options_custom_format_to_ydl_opts():
    opts = DownloadOptions(quality_mode="custom", custom_format="bestvideo[height<=1080]+bestaudio")
    ydl_opts = opts.to_ydl_opts()
    assert ydl_opts["format"] == "bestvideo[height<=1080]+bestaudio"

def test_download_options_subtitles_to_ydl_opts():
    opts = DownloadOptions(
        write_subs=True,
        subs_langs="en,fr",
        write_auto_subs=True,
        subs_format="srt"
    )
    ydl_opts = opts.to_ydl_opts()
    assert ydl_opts["writesubtitles"] is True
    assert ydl_opts["subtitleslangs"] == ["en", "fr"]
    assert ydl_opts["writeautomaticsub"] is True
    assert ydl_opts["subtitlesformat"] == "srt"

def test_download_options_default_raw_cli_list():
    opts = DownloadOptions()
    cli_list = opts.raw_cli_list()
    assert "-f" in cli_list
    assert "bv*+ba/b" in cli_list
    assert "--write-subs" not in cli_list
    assert "--sponsorblock-mark" not in cli_list

def test_download_options_full_raw_cli_list():
    opts = DownloadOptions(
        quality_mode="lowest",
        sort_string="res:1080",
        write_subs=True,
        subs_langs="en",
        subs_format="best",
        sb_mark="sponsor",
        sb_remove="selfpromo",
        embed_metadata=True,
        embed_thumbnail=True,
        write_thumbnail=True,
        use_cookies=True,
        cookies_browser="firefox",
        cookies_profile="default",
        cookies_container="personal",
        limit_rate="1M",
        concurrent_fragments=4,
        impersonate="chrome-110",
        extra_flags="--no-mtime -v",
        target_dir=Path("/tmp/downloads")
    )
    cli_list = opts.raw_cli_list()
    
    assert "-f" in cli_list and "worst" in cli_list
    assert "-S" in cli_list and "res:1080" in cli_list
    assert "--write-subs" in cli_list
    assert "--sub-langs" in cli_list and "en" in cli_list
    assert "--sub-format" in cli_list and "best" in cli_list
    assert "--sponsorblock-mark" in cli_list and "sponsor" in cli_list
    assert "--sponsorblock-remove" in cli_list and "selfpromo" in cli_list
    assert "--embed-metadata" in cli_list
    assert "--embed-thumbnail" in cli_list
    assert "--write-thumbnail" in cli_list
    assert "--cookies-from-browser" in cli_list
    assert "firefox:default::personal" in cli_list
    assert "--limit-rate" in cli_list and "1M" in cli_list
    assert "-N" in cli_list and "4" in cli_list
    assert "--impersonate" in cli_list and "chrome-110" in cli_list
    assert "--no-mtime" in cli_list
    assert "-v" in cli_list
    # target_dir is not part of raw_cli_list, it's handled by the caller
    assert Path("/tmp/downloads") not in cli_list

def test_download_options_cookies_keyring():
    opts = DownloadOptions(
        use_cookies=True,
        cookies_browser="chromium",
        cookies_keyring="kwallet",
    )
    cli_list = opts.raw_cli_list()
    assert "chromium+kwallet" in cli_list

def test_download_options_extra_flags_shlex_split():
    opts = DownloadOptions(extra_flags='--postprocessor-args "arg with space"')
    cli_list = opts.raw_cli_list()
    assert cli_list[-2] == "--postprocessor-args"
    assert cli_list[-1] == "arg with space"
