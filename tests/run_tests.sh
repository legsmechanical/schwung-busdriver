#!/usr/bin/env bash
# run_tests.sh — native build + offline harness. No device needed.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
mkdir -p build
CXX="${CXX:-c++}"
echo "==> building harness with $CXX"
$CXX -O2 -std=c++17 -Wall -Wextra -Wno-unused-parameter \
    tests/harness.cpp src/drumbus_module.cpp \
    -Isrc -Ishared -Idsp -Ivendor \
    -o build/harness -lm
echo "==> running"
exec ./build/harness
