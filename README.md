# WhirlTube

Wayland-first, GTK 4 + Libadwaita frontend for YouTube that:
- Plays videos with MPV (external window by default; optional in-window embed on X11).
- Searches and downloads with yt-dlp (no API keys).
- Minimal dependencies; robust, async UI.

Status: v0.4.5

## Highlights
- Search YouTube via yt-dlp (no API), browse Open URL (video/playlist/channel), view Related and Comments.
- External MPV playback with quality presets (Auto/2160/1440/1080/720/480) and extra args; optional X11 embedding via python-mpv.
- Unified downloads with robust JSON progress (main Download dialog + Quick Download).
- Quick Download: batch URLs, Video/Audio tabs, SponsorBlock, cookies, custom yt-dlp path; per-tab output directories.
- History: persistent search and watch history.
- Smooth UX: loading spinners, cached settings, thumbnail placeholders on failures.

## Requirements
System packages:
- GTK4, Libadwaita, PyGObject (gi)
- MPV
- FFmpeg
- Python 3.12+ (3.13 OK)

Arch:
  sudo pacman -S --needed gtk4 libadwaita python-gobject mpv ffmpeg

Optional (for tiny build):
  sudo pacman -S --needed python-httpx python-yt-dlp

If your venv cannot see system PyGObject:
  pip install PyGObject pycairo

## Install (from source)
- Dev deps:
  pip install -e .[dev]

- Run:
  whirltube
  # or
  python -m whirltube

- Logs:
  WHIRLTUBE_DEBUG=1 whirltube

## Build (zipapp)
Vendored deps:
  bash scripts/build_and_verify.sh

Tiny system deps:
  bash scripts/build_zipapp_systemdeps.sh && bash scripts/deep_verify.sh

Run:
  ./dist/whirltube

## Features
- Search via yt-dlp (ytsearchN); thumbnails via httpx (thread pool, fallback placeholders).
- Browse: Open URL (video/playlist/channel), Related videos, Comments.
- Watch and search history with persistent storage.
- External MPV playback (default) with custom MPV args in Preferences.
- Optional in-window playback via python-mpv (X11 only); falls back on Wayland.
- Preferred playback quality: Auto/2160/1440/1080/720/480 (sets MPV --ytdl-format height cap).
- Downloads via yt-dlp:
  - Per-item Download dialog (presets/custom format; subtitles, SponsorBlock, cookies, advanced flags).
  - Quick Download (batch URLs; Video/Audio tabs, SponsorBlock, cookies, custom yt-dlp path).

## Navigation
- Back: Escape, Backspace, Alt+Left, Ctrl+Backspace.
- Open URL: Works for single videos, playlists, and channels (/videos tab).

## Packaging
AUR:
- whirltube-git: tracks main branch tip
- whirltube: stable releases (tags)
See packaging/arch/ for PKGBUILD examples.

Flatpak: planned for v1.0.0.

## Screenshots
(TBD)

## Icons
- App icon is at src/whirltube/assets/icons/hicolor/scalable/apps/whirltube.svg
- Runtime registers icon so About/Window icons work from source and wheel.

## License
GPL-3.0-or-later. See LICENSE.
