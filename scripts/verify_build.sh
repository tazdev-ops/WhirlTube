#!/usr/bin/env bash
set -euo pipefail

echo "== Build Reproducibility Check =="

# Build twice
echo "Building first time..."
bash scripts/build_and_verify.sh > /dev/null
cp dist/whirltube dist/whirltube.first
sha256sum dist/whirltube.first > build1.sha

echo "Building second time..."
rm -rf build/ dist/
bash scripts/build_and_verify.sh > /dev/null  
sha256sum dist/whirltube > build2.sha

if diff -q build1.sha build2.sha > /dev/null; then
    echo "✓ Build is reproducible"
    rm build1.sha build2.sha dist/whirltube.first
    exit 0
else
    echo "✗ Build is NOT reproducible"
    echo "This suggests non-deterministic file ordering or timestamps"
    diff build1.sha build2.sha
    exit 1
fi