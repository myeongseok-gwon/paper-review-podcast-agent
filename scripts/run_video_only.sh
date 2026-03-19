#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXTRA_ARGS=("$@")

if [ -f "$ROOT/scripts/env.sh" ]; then
  # shellcheck source=/dev/null
  source "$ROOT/scripts/env.sh"
else
  echo "env.sh not found; ensure venv is activated and env vars are set."
fi

python "$ROOT/main.py" --video-only "${EXTRA_ARGS[@]}"
