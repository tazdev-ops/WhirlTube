#!/usr/bin/env bash
set -euo pipefail

OUT="important_code_snapshot.txt"

> "$OUT"

{
  echo "======================================================================="
  echo "WhirlTube Important Code Snapshot"
  echo "Generated: $(date)"
  if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Git branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '-')"
    echo "Git commit: $(git rev-parse HEAD 2>/dev/null || echo '-')"
    if [ -n "$(git status --porcelain 2>/dev/null || true)" ]; then
      echo "Git status: DIRTY"
    else
      echo "Git status: CLEAN"
    fi
  fi
  echo "======================================================================="
  echo
} >> "$OUT"

# List of important files to capture
important_files=(
  "./src/whirltube/app.py"
  "./src/whirltube/player.py"
  "./src/whirltube/downloader.py"
  "./src/whirltube/download_manager.py"
  "./src/whirltube/ytdlp_runner.py"
  "./src/whirltube/models.py"
  "./src/whirltube/window.py"
  "./src/whirltube/mpv_embed.py"
  "./src/whirltube/navigation_controller.py"
  "./src/whirltube/quickdownload.py"
  "./src/whirltube/search_filters.py"
  "./src/whirltube/subscriptions.py"
  "./src/whirltube/history.py"
  "./src/whirltube/download_history.py"
  "./src/whirltube/dialogs.py"
  "./src/whirltube/util.py"
  "./src/whirltube/invidious_auth.py"
  "./src/whirltube/logging_config.py"
  "./src/whirltube/metrics.py"
  "./src/whirltube/mpv_gl.py"
  "./src/whirltube/quick_quality.py"
  "./src/whirltube/subscription_feed.py"
  "./src/whirltube/thumbnail_cache.py"
  "./src/whirltube/watch_later.py"
  "./src/whirltube/providers/base.py"
  "./src/whirltube/providers/hybrid.py"
  "./src/whirltube/providers/innertube_web.py"
  "./src/whirltube/providers/invidious.py"
  "./src/whirltube/providers/ytdlp.py"
  "./src/whirltube/providers/__init__.py"
  "./src/whirltube/services/mpv_launcher.py"
  "./src/whirltube/services/native_resolver.py"
  "./src/whirltube/services/playback.py"
  "./src/whirltube/services/__init__.py"
  "./src/whirltube/ui/widgets/mpv_controls.py"
  "./src/whirltube/ui/widgets/result_row.py"
  "./src/whirltube/ui/widgets/__init__.py"
  "./src/whirltube/ui/controllers/browse.py"
  "./src/whirltube/ui/controllers/search.py"
  "./src/whirltube/ui/controllers/__init__.py"
  "./src/whirltube/ui/__init__.py"
  "./pyproject.toml"
  "./README.md"
  "./CHANGELOG.md"
  "./CONTRIBUTING.md"
  "./ruff.toml"
  "./mypy.ini"
  "./.pre-commit-config.yaml"
  "./.github/workflows/ci.yml"
  "./flatpak/org.whirltube.WhirlTube.yml"
  "./data/org.whirltube.WhirlTube.desktop"
  "./data/org.whirltube.WhirlTube.metainfo.xml"
  "./whirltube/PKGBUILD"
  "./tests/conftest.py"
  "./tests/test_dialogs.py"
  "./tests/test_models.py"
  "./tests/test_parse_line.py"
  "./tests/test_runner_state.py"
  "./tests/test_search_filters.py"
  "./tests/test_smoke.py"
  "./tests/test_util.py"
  "./tests/test_utils_proxy.py"
  "./tests/test_utils_youtube_url.py"
  "./tests/test_ytdlp_runner.py"
)

for file in "${important_files[@]}"; do
  if [ -f "$file" ]; then
    {
      echo
      echo "--- FILE: $file ---"
      cat "$file"
      echo
    } >> "$OUT"
    echo "Added $file to snapshot"
  else
    echo "File not found: $file"
  fi
done

echo "Important code snapshot written to: $OUT"