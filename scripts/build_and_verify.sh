#!/usr/bin/env bash
set -euo pipefail
bash scripts/build_zipapp.sh
bash scripts/deep_verify.sh
echo "Build and verify complete."
