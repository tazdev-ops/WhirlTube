#!/usr/bin/env bash
set -euo pipefail
find src/whirltube -type f -name "*.py" -print0 | xargs -0 sha256sum | sort > .tripwire/after.txt
diff -u .tripwire/before.txt .tripwire/after.txt || true
