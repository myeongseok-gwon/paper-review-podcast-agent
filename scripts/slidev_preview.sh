#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
THEME_DIR="$ROOT/slidev-theme-umn"

if [ $# -lt 1 ]; then
  echo "Usage: $0 <slides.md path> [port]"
  exit 1
fi

MD_PATH="$1"
PORT="${2:-3030}"

if [ ! -f "$MD_PATH" ]; then
  echo "slides file not found: $MD_PATH"
  exit 1
fi

if [ ! -d "$THEME_DIR" ]; then
  echo "theme directory not found: $THEME_DIR"
  exit 1
fi

if [ ! -x "$THEME_DIR/node_modules/.bin/slidev" ]; then
  echo "Slidev runtime missing. Installing in $THEME_DIR ..."
  (cd "$THEME_DIR" && npm install --no-audit --no-fund)
fi

cd "$THEME_DIR"
CHOKIDAR_USEPOLLING=1 CHOKIDAR_INTERVAL=300 npm run dev -- "$MD_PATH" --port "$PORT"
