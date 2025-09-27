# Contributing to WhirlTube

Thanks for your interest! This project aims to be a lean, native YouTube client for GNOME/Wayland using MPV + yt-dlp. Small, focused PRs are very welcome.

## Dev Setup
- Arch deps:
  sudo pacman -S --needed gtk4 libadwaita python-gobject mpv ffmpeg
- Python:
  python -m venv .venv && source .venv/bin/activate
  pip install -e .[dev]
- Build:
  bash scripts/build_and_verify.sh
- Run:
  WHIRLTUBE_DEBUG=1 ./dist/whirltube

## Coding Style
- Ruff (PEP8 + curated rules), mypy (py312), small functions, minimal diffs.
- One feature/bug per PR (~300 lines max ideal).
- Conventional commits (feat:, fix:, docs:, chore:, refactor:, test:, build:).

## Tests
- Run: pytest -q
- Please add tests for parsers (ytdlp_runner), options mapping (dialogs), and provider helpers.

## PR Checklist
- [ ] ruff, mypy, pytest pass
- [ ] scripts/build_and_verify.sh passes locally
- [ ] No stray *.bak files
- [ ] Clear description; link issues if any

## Reporting Issues
- Use the bug report template; include OS/distro, logs (WHIRLTUBE_DEBUG=1), and steps to reproduce.

Thanks!
