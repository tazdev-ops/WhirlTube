#!/usr/bin/env bash
set -euo pipefail
rm -rf build/zipapp dist
mkdir -p build/zipapp dist
PY=${PY:-/usr/bin/python3}
# Vendor whirltube and its pure-Python deps into a local dir; no system break
PIP_DISABLE_PIP_VERSION_CHECK=1 "$PY" -m pip install --no-input --no-compile --target build/zipapp .
cat > build/zipapp/__main__.py <<PY
from whirltube.app import main
if __name__ == "__main__":
    raise SystemExit(main())
PY
"$PY" - <<'PY'
import zipapp, os, stat, pathlib
stage = pathlib.Path("build/zipapp")
out = pathlib.Path("dist/whirltube")
zipapp.create_archive(stage, out, interpreter="/usr/bin/python3", compressed=True)
os.chmod(out, os.stat(out).st_mode | stat.S_IEXEC)
print("Built:", out, "Size:", out.stat().st_size, "bytes")
PY
echo "Zipapp ready at dist/whirltube"