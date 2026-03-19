#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
THEME_DIR="$ROOT/slidev-theme-umn"

if [ $# -lt 1 ]; then
  echo "Usage: $0 <slides.md path> [lang]"
  exit 1
fi

MD_PATH="$1"
LANG="${2:-en}"

if [ ! -f "$MD_PATH" ]; then
  echo "slides file not found: $MD_PATH"
  exit 1
fi

if [ ! -d "$THEME_DIR" ]; then
  echo "theme directory not found: $THEME_DIR"
  exit 1
fi

if [ -f "$ROOT/scripts/env.sh" ]; then
  # shellcheck source=/dev/null
  source "$ROOT/scripts/env.sh"
fi

MD_DIR="$(cd "$(dirname "$MD_PATH")" && pwd)"
PAPER_DIR="$(cd "$MD_DIR/.." && pwd)"
MD_BASENAME="$(basename "$MD_PATH")"
DATE="$(python - <<'PY' "$MD_BASENAME"
import re
import sys
name = sys.argv[1]
m = re.search(r"slides_(\d{4}-\d{2}-\d{2})\.md$", name)
print(m.group(1) if m else "unknown-date")
PY
)"

if [ "$DATE" = "unknown-date" ]; then
  echo "Could not infer date from filename: $MD_BASENAME"
  exit 1
fi

EXPORT_DIR="$MD_DIR/manual_export"
SCRIPTS_PATH="$PAPER_DIR/scripts_${DATE}_${LANG}.txt"
AUDIO_DIR="$PAPER_DIR/audio/$LANG"
OUT_VIDEO="$PAPER_DIR/is_papers_review_${DATE}_${LANG}_manual.mp4"

if [ ! -f "$SCRIPTS_PATH" ]; then
  echo "scripts file not found: $SCRIPTS_PATH"
  exit 1
fi
if [ ! -d "$AUDIO_DIR" ]; then
  echo "audio directory not found: $AUDIO_DIR"
  exit 1
fi

if [ ! -x "$THEME_DIR/node_modules/.bin/slidev" ]; then
  echo "Slidev runtime missing. Installing in $THEME_DIR ..."
  (cd "$THEME_DIR" && npm install --no-audit --no-fund)
fi

echo "Exporting slides to PNG..."
(cd "$THEME_DIR" && npm run export -- "$MD_PATH" --per-slide --format png --output "$EXPORT_DIR")

echo "Building video from exported slides + existing audio..."
python - <<'PY' "$EXPORT_DIR" "$SCRIPTS_PATH" "$AUDIO_DIR" "$OUT_VIDEO"
import re
import sys
from pathlib import Path

from video.builder import build_video

export_dir = Path(sys.argv[1])
scripts_path = Path(sys.argv[2])
audio_dir = Path(sys.argv[3])
out_video = Path(sys.argv[4])

images = sorted(str(p) for p in export_dir.glob("*.png"))
audios = sorted(str(p) for p in audio_dir.glob("audio_slide_*.mp3"))

text = scripts_path.read_text(encoding="utf-8")
matches = re.findall(r"\[Slide \d+\]\nScript:\n(.*?)(?=\n\n\[Slide \d+\]\nScript:|\Z)", text, flags=re.S)
scripts = [m.strip() for m in matches]

if not images:
    raise SystemExit(f"No PNG files found in {export_dir}")
if not audios:
    raise SystemExit(f"No audio files found in {audio_dir}")
if not (len(images) == len(audios) == len(scripts)):
    raise SystemExit(
        f"Count mismatch: images={len(images)}, audios={len(audios)}, scripts={len(scripts)}"
    )

build_video(images, audios, str(out_video), subtitle_scripts=scripts)
print(f"Saved video: {out_video}")
PY
