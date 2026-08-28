#!/usr/bin/env bash
# build.sh — cross-compile busdriver.so for the Move (aarch64) and package
# dist/busdriver/ + dist/busdriver-module.tar.gz.
#
# Auto-Dockerizes (PushNPull pattern): if CROSS_PREFIX is unset and we're not
# already in a container, build the toolchain image and re-run inside it.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

MODULE_ID=busdriver

if [ -z "${CROSS_PREFIX:-}" ] && [ ! -f /.dockerenv ]; then
    echo "==> building in Docker (move-anything-builder)"
    docker build -q -t move-anything-builder -f scripts/Dockerfile scripts >/dev/null
    docker run --rm -v "$HERE":/work -w /work \
        -e CROSS_PREFIX=aarch64-linux-gnu- \
        move-anything-builder bash scripts/build.sh
    exit 0
fi

CROSS_PREFIX="${CROSS_PREFIX:-aarch64-linux-gnu-}"
CXX="${CROSS_PREFIX}g++"

echo "==> compiling with $CXX"
mkdir -p build
$CXX -Ofast -shared -fPIC -march=armv8-a -mtune=cortex-a72 \
    -fomit-frame-pointer -fno-stack-protector -DNDEBUG -std=c++17 \
    src/busdriver_module.cpp \
    -Isrc -Ishared -Idsp -Ivendor \
    -o "build/${MODULE_ID}.so" -lm

echo "==> packaging dist/"
rm -rf "dist/${MODULE_ID}"
mkdir -p "dist/${MODULE_ID}"
cp "build/${MODULE_ID}.so" "dist/${MODULE_ID}/"
cp src/module.json "dist/${MODULE_ID}/"
[ -f src/help.json ] && cp src/help.json "dist/${MODULE_ID}/"
[ -f src/canvas.js ] && cp src/canvas.js "dist/${MODULE_ID}/"

tar -czf "dist/${MODULE_ID}-module.tar.gz" -C dist "${MODULE_ID}"
echo "==> done: dist/${MODULE_ID}-module.tar.gz"
