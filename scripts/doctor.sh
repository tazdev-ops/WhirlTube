#!/usr/bin/env bash
set -euo pipefail
echo "== WhirlTube Doctor =="

ok=1

have() { command -v "$1" >/dev/null 2>&1; }

echo "-- Python + gi check --"
if python3 - <<'PY'
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Adw, Gdk  # noqa
print("gi: ok")
PY
then
  :
else
  echo "gi: MISSING"; ok=0
fi

echo "-- Binaries --"
for c in mpv ffmpeg; do
  if have "$c"; then echo "$c: ok"; else echo "$c: MISSING"; ok=0; fi
done

echo "-- Optional Python deps (ok if vendored) --"
python3 -c "import httpx; print('httpx: ok')" || echo "httpx: missing (ok if vendored)"
python3 -c "import yt_dlp; print('yt-dlp: ok')" || echo "yt-dlp: missing (ok if vendored)"

if [[ $ok -eq 1 ]]; then
  echo "Doctor: PASS"
  exit 0
else
  echo "Doctor: FAIL"
  exit 1
fi
