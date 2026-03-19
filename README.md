# Information Systems Paper Review Agent

Automated local pipeline that turns one or more local PDF papers into slides, narration audio, and subtitle-burned videos, with optional YouTube upload.

## Overview

`main.py` orchestrates:

1. Load input PDFs from `--pdf-path` or `--input-dir`.
2. Infer identifier from filename (or `--paper-id` in single mode).
3. Detect DOI-like identifiers and enrich metadata using Crossref.
4. Stage local PDFs into output workspace (`paper.pdf`).
5. Extract text and optional figures.
6. Generate structured slide content with LLM.
7. Render Slidev slides to PNG.
8. Generate per-slide TTS audio.
9. Build MP4 videos with hard subtitles.
10. Optionally upload to YouTube.

## Pipeline

```text
Local PDF(s)
  -> Identifier extraction
  -> DOI detection
  -> Crossref metadata (if DOI-like)
  -> Local PDF staging
  -> Text + figure extraction
  -> LLM summarization
  -> Slidev slides
  -> TTS audio
  -> Video build
  -> Optional upload
```

## Quick Start

```bash
./scripts/setup_venv.sh
cp .env.example .env
source scripts/env.sh
python main.py --pdf-path "/absolute/path/to/10.1145_1234567.1234568.pdf" --skip-upload
```

## Usage

### Single local PDF

```bash
python main.py \
  --pdf-path "/absolute/path/to/paper.pdf" \
  --paper-title "Optional custom title" \
  --origin "Optional affiliation" \
  --skip-upload
```

### Batch directory

```bash
python main.py \
  --input-dir "/absolute/path/to/papers" \
  --skip-upload
```

### Video-only shortcut

```bash
./scripts/run_video_only.sh --pdf-path "/absolute/path/to/paper.pdf"
./scripts/run_video_only.sh --input-dir "/absolute/path/to/papers"
```

## DOI Filename Convention

DOI strings include `/`, which is not valid in filenames. Supported filename stems:

- `10.1145%2F1234567.1234568.pdf` (URL-encoded slash)
- `10.1145_1234567.1234568.pdf` (first underscore treated as slash)

When DOI is detected, metadata enrichment attempts title, authors, venue, published date, and canonical URL. If lookup fails, pipeline continues with fallback metadata.

## CLI Reference

| Flag | Description |
| --- | --- |
| `--date YYYY-MM-DD` | Output grouping date. Defaults to today. |
| `--languages en,...` | Narration languages. |
| `--pdf-path PATH` | Process one local PDF file. |
| `--input-dir PATH` | Process all local `*.pdf` files in a directory. |
| `--paper-id ID` | Optional custom ID in `--pdf-path` mode. |
| `--paper-title TITLE` | Optional custom title in `--pdf-path` mode. |
| `--origin TEXT` | Optional affiliation/origin override. |
| `--strip-pdf-annotations` | Strip PDF annotations before text/figure extraction (default ON). |
| `--keep-pdf-annotations` | Keep original PDF annotations during text/figure extraction. |
| `--skip-render` | Skip Slidev PNG rendering. |
| `--skip-tts` | Skip TTS generation. |
| `--skip-video` | Skip video composition. |
| `--skip-upload` | Skip YouTube upload. |
| `--no-upload` | Disable YouTube upload. |
| `--upload` | Enable YouTube upload (default: enabled). |
| `--video-only` | Build local video and skip upload. |

You must provide exactly one of `--pdf-path` or `--input-dir`.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `CROSSREF_BASE_URL` | `https://api.crossref.org` | Crossref API base URL for DOI metadata. |
| `OPENAI_API_KEY` | - | Required for LLM/TTS. |
| `OPENAI_LLM_MODEL` | `gpt-5.4` | Summarization and translation model. |
| `OPENAI_TTS_MODEL` | `gpt-4o-mini-tts` | TTS model. |
| `OPENAI_TTS_VOICE` | `echo` | TTS voice. |
| `TTS_STYLE_INSTRUCTION` | empty | Optional style hint. |
| `TTS_SPEED` | `1.2` | TTS speed multiplier. |
| `LANGUAGES` | `en` | Narration languages. |
| `YOUTUBE_CLIENT_SECRETS_FILE` | empty | YouTube OAuth client file. |
| `YOUTUBE_TOKEN_FILE` | empty | YouTube token file. |
| `YOUTUBE_PRIVACY_STATUS` | `unlisted` | YouTube upload privacy (`public`, `private`, or `unlisted`). |
| `OUTPUT_BASE_DIR` | `./outputs` | Base output directory. |
| `LOG_LEVEL` | `INFO` | Log level. |
| `FIGURE_RENDER_DPI` | `350` | PDF render DPI used before layout detection (higher improves small figure coverage). |
| `PUBLAYNET_SCORE_THRESH` | `0.6` | Detection confidence threshold for PubLayNet model. |
| `FIGURE_CROP_PAD_RATIO` | `0.08` | Symmetric crop padding ratio for detected figure/table boxes. |
| `FIGURE_CROP_PAD_BOTTOM_RATIO` | `0.18` | Extra bottom padding ratio to reduce caption/axis clipping. |
| `TABLE_CROP_PAD_RATIO` | `0.16` | Left/right padding ratio for table crops. |
| `TABLE_CROP_PAD_TOP_RATIO` | `0.18` | Extra top padding ratio for table title/header area. |
| `TABLE_CROP_PAD_BOTTOM_RATIO` | `0.28` | Extra bottom padding ratio for table notes/footers. |
| `TABLE_FULL_WIDTH_TRIGGER_RATIO` | `0.78` | If table box width/page width exceeds this, expand to near full width. |
| `TABLE_FULL_WIDTH_MARGIN_RATIO` | `0.04` | Margin ratio kept on both sides for full-width-expanded tables. |
| `FIGURE_MIN_AREA_RATIO` | `0.0015` | Minimum box area ratio vs page image to filter tiny false positives. |
| `FIGURE_MIN_SIDE_PX` | `40` | Minimum width/height in pixels for extracted figure crops. |

## Output Layout

Batch mode:

```text
outputs/{date}/
  is_papers_review_{date}.mp4
  is_papers_review_{date}_{lang}.mp4
  slides/
    slides_{date}.md
    slides_{date}_*.png
    scripts_{date}_{lang}.txt
  {paper_id}/
    paper.pdf
    captions.json
    figures/*.png
  audio/{lang}/audio_slide_*.mp3
```

Single mode:

```text
outputs/{date}/{paper_id}/
  paper.pdf
  captions.json
  figures/*.png
  slides/
    slides_{date}.md
    slides_{date}_*.png
    figures/*.png
  scripts_{date}_{lang}.txt
  audio/{lang}/audio_slide_*.mp3
  is_papers_review_{date}.mp4
  is_papers_review_{date}_{lang}.mp4
```

## Troubleshooting

- `slidev` missing: `npm i -g @slidev/cli slidev-theme-umn`
- `ffmpeg` missing: install and verify `ffmpeg -version`
- Crossref metadata missing: check DOI filename format, record availability, or temporary API/network errors
# Information Systems Paper Review Agent

Automated local pipeline that turns one or more **local PDF papers** into:

- slide deck images,
- narrated audio tracks,
- subtitle-burned MP4 videos,
- optional YouTube uploads.

This repository is optimized for **Information Systems paper review workflows** with DOI-aware metadata enrichment.

## Overview

`main.py` orchestrates an end-to-end pipeline:

1. Load local PDF input (`--pdf-path` or `--input-dir`).
2. Infer an identifier from filename (or `--paper-id` for single-file mode).
3. If identifier looks like a DOI, fetch metadata from Crossref.
4. Stage each local PDF into output workspace.
5. Extract core paper text (`abstract`, `introduction`, `conclusion`, plus full text).
6. Ask an LLM for structured slide content in JSON.
7. Build Slidev markdown with optional figure embedding.
8. Render slides to PNG.
9. Generate TTS audio per slide and per language.
10. Compose video with subtitles using MoviePy.
11. Upload to YouTube (optional).

## Pipeline

```text
Local PDF(s) (--pdf-path / --input-dir)
  -> Identifier from filename
  -> DOI detection
  -> Crossref metadata fetch (if DOI-like)
  -> Local PDF staging (paper.pdf)
  -> PDF text + figure extraction
  -> LLM summarization -> slide specs
  -> Slidev markdown generation
  -> Slidev PNG rendering
  -> OpenAI TTS (per slide, per language)
  -> MoviePy composition + hard subtitles
  -> MP4 output
  -> Optional YouTube upload
```

## Repository Structure

```text
main.py                  # Entry point
config.py                # Env-driven configuration

daily_papers/            # Input models, DOI/Crossref metadata, PDF handling, text extraction
llm/                     # LLM client, prompts, summarizer, translator
slides/                  # Figure handling, markdown builder, Slidev renderer
tts/                     # OpenAI TTS client
video/                   # MoviePy video builder + subtitles
youtube/                 # YouTube OAuth/upload
storage/                 # Output path helpers
scripts/                 # Setup and convenience scripts
models/publaynet/        # PubLayNet config + weights (for figure extraction)
```

## Requirements

### Runtime

- Python `3.10+` recommended
- `ffmpeg` on `PATH`
- `slidev` CLI on `PATH`
- OpenAI API key

### Install Python dependencies

```bash
pip install -r requirements.txt
```

### Install system dependencies

```bash
# macOS example
brew install ffmpeg node
npm i -g @slidev/cli slidev-theme-umn
```

## Quick Start

### 1) Create virtual environment

```bash
./scripts/setup_venv.sh
```

### 2) Configure environment

```bash
cp .env.example .env
```

Set at least:

- `OPENAI_API_KEY`

If uploading to YouTube, also set:

- `YOUTUBE_CLIENT_SECRETS_FILE`
- `YOUTUBE_TOKEN_FILE`
- `YOUTUBE_PRIVACY_STATUS` (`public` | `private` | `unlisted`, default: `private`)

### 3) Activate environment

```bash
source scripts/env.sh
```

### 4) Run pipeline (local video build, no upload)

```bash
python main.py --pdf-path "/absolute/path/to/10.1145_1234567.1234568.pdf" --skip-upload
```

## Usage

### Single local PDF mode

```bash
python main.py \
  --pdf-path "/absolute/path/to/10.1145_1234567.1234568.pdf" \
  --paper-title "Optional Custom Title" \
  --origin "Your Lab/Company" \
  --skip-upload
```

### Batch local directory mode

```bash
python main.py \
  --input-dir "/absolute/path/to/papers" \
  --skip-upload
```

All `*.pdf` files in the directory are processed.

### Video-only shortcut (always skips upload)

```bash
# single file
./scripts/run_video_only.sh --pdf-path "/absolute/path/to/paper.pdf"

# batch directory
./scripts/run_video_only.sh --input-dir "/absolute/path/to/papers"
```

### Partial runs (debug/dev)

```bash
python main.py --pdf-path "/absolute/path/to/paper.pdf" --skip-render
python main.py --pdf-path "/absolute/path/to/paper.pdf" --skip-tts
python main.py --pdf-path "/absolute/path/to/paper.pdf" --skip-video
```

## DOI Filename Convention

DOI contains `/`, which cannot appear in file names on most systems. Supported patterns:

- URL-encoded DOI stem: `10.1145%2F1234567.1234568.pdf`
- Filesystem-friendly DOI stem: `10.1145_1234567.1234568.pdf` (first `_` treated as DOI slash)
- Full DOI URL stem: `https___doi.org_10.1145_1234567.1234568.pdf` is not guaranteed; prefer the two formats above.

If DOI is detected, metadata enrichment attempts:

- title
- authors
- venue (journal/proceedings container title)
- published date
- canonical URL

If metadata lookup fails, pipeline continues using filename-derived fallback metadata.

## CLI Reference

| Flag | Description |
| --- | --- |
| `--date YYYY-MM-DD` | Output grouping date. Defaults to today. |
| `--languages en,...` | Narration languages. First language is primary output video. |
| `--pdf-path PATH` | Process one local PDF file. |
| `--input-dir PATH` | Process all local `*.pdf` files in a directory. |
| `--paper-id ID` | Optional custom ID in `--pdf-path` mode. |
| `--paper-title TITLE` | Optional custom title in `--pdf-path` mode. |
| `--origin TEXT` | Optional affiliation/origin override. |
| `--strip-pdf-annotations` | Strip PDF annotations before text/figure extraction (default ON). |
| `--keep-pdf-annotations` | Keep original PDF annotations during text/figure extraction. |
| `--skip-render` | Skip Slidev PNG rendering. |
| `--skip-tts` | Skip TTS generation. |
| `--skip-video` | Skip video composition. |
| `--skip-upload` | Disable YouTube upload. |
| `--no-upload` | Disable YouTube upload. |
| `--upload` | Enable YouTube upload (default: enabled). |
| `--video-only` | Build local video and skip upload (same effect as `--skip-upload` for upload phase). |

Input constraints:

- Provide exactly one of `--pdf-path` or `--input-dir`.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `CROSSREF_BASE_URL` | `https://api.crossref.org` | Crossref API base URL for DOI lookup. |
| `OPENAI_API_KEY` | - | Required for LLM/TTS steps. |
| `OPENAI_LLM_MODEL` | `gpt-5.4` | Model used for summarization and translation. |
| `OPENAI_TTS_MODEL` | `gpt-4o-mini-tts` | TTS model. |
| `OPENAI_TTS_VOICE` | `echo` | Voice preset. |
| `TTS_STYLE_INSTRUCTION` | empty | Style hint string (stored, currently not injected into spoken text). |
| `TTS_SPEED` | `1.2` | TTS speed multiplier, clamped to `[0.5, 4.0]`. |
| `LANGUAGES` | `en` | Comma-separated target narration languages. |
| `YOUTUBE_CLIENT_SECRETS_FILE` | empty | OAuth client JSON path. |
| `YOUTUBE_TOKEN_FILE` | empty | OAuth token cache path. |
| `YOUTUBE_PRIVACY_STATUS` | `private` | Upload privacy (`public`, `private`, or `unlisted`). |
| `OUTPUT_BASE_DIR` | `./outputs` | Base output directory. |
| `LOG_LEVEL` | `INFO` | Python logging level. |

## Outputs

### Batch mode (`--input-dir`)

```text
outputs/{date}/
  is_papers_review_{date}.mp4
  is_papers_review_{date}_{lang}.mp4
  slides/
    slides_{date}.md
    slides_{date}_*.png
    scripts_{date}_{lang}.txt
  {paper_id}/
    paper.pdf
    captions.json
    figures/*.png
  audio/{lang}/
    audio_slide_001.mp3
    ...
```

### Single mode (`--pdf-path`)

```text
outputs/{date}/{paper_id}/
  paper.pdf
  captions.json
  figures/*.png
  slides/
    slides_{date}.md
    slides_{date}_*.png
    figures/*.png
  scripts_{date}_{lang}.txt
  audio/{lang}/audio_slide_*.mp3
  is_papers_review_{date}.mp4
  is_papers_review_{date}_{lang}.mp4
```

## YouTube Upload Behavior

- Upload runs by default, and occurs only when both conditions are met:
  - you did not pass `--skip-upload` / `--no-upload` / `--video-only`
  - both `YOUTUBE_CLIENT_SECRETS_FILE` and `YOUTUBE_TOKEN_FILE` are configured
- First OAuth run opens a local browser for consent.
- Videos are uploaded as:
  - `privacyStatus: YOUTUBE_PRIVACY_STATUS` (default `private`)
  - `categoryId: 28` (Science & Technology)
- Upload metadata defaults:
  - Single-paper mode (`--doi` or `--pdf-path`): title is `Paper Title (Venue, Year Mon)` and description is extracted abstract text.
  - Batch mode (`--input-dir`): title/description use the daily digest format.

## Figure Extraction (Optional but Built-in)

Figure extraction runs per staged local PDF before summarization.

Behavior:

- If `captions.json` already exists, extraction is skipped (cache behavior).
- If model files or optional deps are missing, extraction is skipped gracefully.
- Extracted figure/table metadata is fed into the LLM prompt to improve slide quality.

## Troubleshooting

### `slidev CLI not found`

```bash
npm i -g @slidev/cli slidev-theme-umn
slidev --version
```

### FFmpeg / video encoding errors

```bash
ffmpeg -version
```

### OpenAI request failures

Check:

- `OPENAI_API_KEY` is set correctly
- model names are valid for your account
- quota/rate limits are not exhausted

### No video built

Common causes:

- slide image count and audio file count mismatch
- `--skip-render` or `--skip-tts` used in ways that leave missing artifacts
- upstream LLM/TTS failures in logs

### Crossref metadata missing

Possible causes:

- filename does not match supported DOI conventions
- DOI exists but Crossref record is incomplete
- transient API/network failure

Pipeline continues with fallback metadata even when this happens.
