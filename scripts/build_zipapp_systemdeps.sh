#!/usr/bin/env bash
set -euo pipefail
rm -rf build/zipapp dist
mkdir -p build/zipapp dist
cp -a src/whirltube build/zipapp/whirltube
cat > build/zipapp/__main__.py <<PY
from whirltube.app import main
if __name__ == "__main__":
    raise SystemExit(main())
PY
/usr/bin/python3 - <<'PY'
import zipapp, os, stat, pathlib
stage = pathlib.Path("build/zipapp")
out = pathlib.Path("dist/whirltube")
zipapp.create_archive(stage, out, interpreter="/usr/bin/python3", compressed=True)
os.chmod(out, os.stat(out).st_mode | stat.S_IEXEC)
print("Built (system-deps):", out, "Size:", out.stat().st_size, "bytes")
PY
echo "Zipapp (system-deps) at dist/whirltube"
