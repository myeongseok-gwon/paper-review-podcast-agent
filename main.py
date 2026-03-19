# Copyright 2026 ThisIsHwang
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import datetime
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _ensure_packages_distributions() -> None:
    """Monkey-patch importlib.metadata.packages_distributions for Python <3.10."""
    import importlib.metadata as _im

    if hasattr(_im, "packages_distributions"):
        return
    try:
        import importlib_metadata as _backport

        _im.packages_distributions = _backport.packages_distributions  # type: ignore[attr-defined, assignment]
    except Exception as exc:  # pragma: no cover - best-effort fallback
        import warnings

        warnings.warn(
            f"packages_distributions missing and backport unavailable: {exc}. "
            "Upgrade to Python 3.10+ for full compatibility.",
            RuntimeWarning,
        )


_ensure_packages_distributions()

from config import Config, load_config
from daily_papers.doi_utils import doi_url, normalize_doi
from daily_papers.models import HFPaperEntry
from daily_papers.pdf_downloader import stage_local_pdf
from daily_papers.pdf_parser import extract_core_text
from daily_papers.pdf_preprocessor import strip_pdf_annotations
from daily_papers.zotero_bib import find_entry_by_doi
from llm.client import LLMClient
from llm.summarizer import DailyEpisode, PaperSummary, SlideSpec, summarize_paper
from llm.translator import language_display, translate_scripts
from slides.figure_assets import FigureAsset, FigureLibrary, load_figure_library, summarize_assets
from slides.figure_extractor import extract_pdf_figures
from slides.markdown_builder import build_daily_markdown
from slides.slidev_renderer import render_markdown_to_images
from storage import paths
from tts.client import TTSClient
from video.builder import build_video
from youtube.uploader import upload_video


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local PDF paper review video automation")
    parser.add_argument("--date", help="Target date (YYYY-MM-DD). Defaults to today.")
    parser.add_argument(
        "--languages",
        help="Comma-separated narration languages (e.g., en). Defaults to LANGUAGES env/config.",
    )
    parser.add_argument("--doi", help='Process by DOI from Better BibTeX (e.g., "10.1287/isre.2022.0152").')
    parser.add_argument("--zotero-bib", help="Path to Better BibTeX .bib file.")
    parser.add_argument("--pdf-path", help="Process a single local PDF file.")
    parser.add_argument("--input-dir", help="Process all PDF files in a local directory.")
    parser.add_argument("--paper-id", help="Optional custom identifier for --pdf-path mode.")
    parser.add_argument("--paper-title", help="Optional custom title for --pdf-path mode.")
    parser.add_argument("--origin", help="Optional origin/affiliation override.")
    parser.add_argument(
        "--strip-pdf-annotations",
        dest="strip_pdf_annotations",
        action="store_true",
        default=True,
        help="Strip PDF annotations before text/figure extraction (default: enabled).",
    )
    parser.add_argument(
        "--keep-pdf-annotations",
        dest="strip_pdf_annotations",
        action="store_false",
        help="Keep original PDF annotations during text/figure extraction.",
    )
    parser.add_argument("--skip-render", action="store_true", help="Skip Slidev slide rendering.")
    parser.add_argument("--skip-tts", action="store_true", help="Skip TTS generation.")
    parser.add_argument("--skip-video", action="store_true", help="Skip video rendering.")
    parser.add_argument("--skip-upload", action="store_true", help="Skip YouTube upload (legacy flag).")
    parser.add_argument("--upload", dest="upload", action="store_true", default=True, help="Enable YouTube upload (default: enabled).")
    parser.add_argument("--no-upload", dest="upload", action="store_false", help="Disable YouTube upload.")
    parser.add_argument("--video-only", action="store_true", help="Produce video locally and skip YouTube upload.")
    parser.add_argument(
        "--debug-figure-layout",
        action="store_true",
        help=(
            "Debug mode: skip LLM/TTS/video/upload, extract figure/table assets only, and build "
            "template slides (image-only + 3-bullet+image) for every extracted asset."
        ),
    )
    parser.add_argument(
        "--auto-rotate-by-ocr",
        action="store_true",
        help="Use OCR orientation detection to auto-rotate extracted table images before slide embedding.",
    )
    return parser.parse_args()


def build_description(papers: List[Any]) -> str:
    lines = ["Information Systems Paper Review", "", "Source: Local PDF inputs", ""]
    for idx, paper in enumerate(papers, 1):
        title = getattr(paper, "title", "Untitled")
        authors = ", ".join(getattr(paper, "authors", []))
        link = getattr(paper, "source_url", "") or doi_url(getattr(paper, "doi", "")) or "n/a"
        venue = getattr(paper, "venue", "") or "n/a"
        published_date = getattr(paper, "published_date", "") or getattr(paper, "published_at", "") or "n/a"
        lines.append(f"{idx}. {title}")
        lines.append(f"   - Authors: {authors}")
        lines.append(f"   - Venue: {venue}")
        lines.append(f"   - Published: {published_date}")
        lines.append(f"   - Link: {link}")
        lines.append("")
    return "\n".join(lines)


def _year_month_label(paper: Any) -> str:
    published_date = _clean_text(getattr(paper, "published_date", ""))
    if published_date:
        m = re.match(r"^(\d{4})(?:-(\d{1,2}))?", published_date)
        if m:
            year = m.group(1)
            month_num = m.group(2)
            if month_num:
                month_idx = max(1, min(12, int(month_num)))
                return f"{year} {datetime.date(1900, month_idx, 1).strftime('%b')}"
            return year

    year = _clean_text(getattr(paper, "published_at", ""))
    month = _month_label(getattr(paper, "published_month", ""))
    return " ".join(part for part in [year, month] if part).strip()


def _single_paper_upload_title(paper: Any) -> str:
    title = _clean_text(getattr(paper, "title", "")) or "Untitled"
    venue = _clean_text(getattr(paper, "venue", ""))
    year_month = _year_month_label(paper)
    detail = ", ".join(part for part in [venue, year_month] if part)
    return f"{title} ({detail})" if detail else title


def _single_paper_upload_description(paper: Any, abstract: str) -> str:
    abstract_clean = _clean_text(abstract)
    if abstract_clean:
        return abstract_clean

    fallback = _clean_text(getattr(paper, "summary", ""))
    if fallback:
        return fallback

    title = _clean_text(getattr(paper, "title", ""))
    return f"Abstract not available for {title}." if title else "Abstract not available."


def _normalize_languages(raw_list: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for lang in raw_list:
        code = lang.strip().lower()
        if code and code not in seen:
            result.append(code)
            seen.add(code)
    return result


def _parse_languages(cli_value: Optional[str], config_langs: List[str]) -> List[str]:
    if cli_value:
        langs = _normalize_languages(cli_value.split(","))
        if langs:
            return langs
    langs = _normalize_languages(config_langs)
    return langs or ["en"]


def _strip_leading_enumeration(text: str) -> str:
    return re.sub(r"^\s*\d+\s*[.\)-:]?\s*", "", text.strip())


def _strip_delivery_cues(text: str) -> str:
    cleaned = re.sub(r"\[[^\[\]]+?\]", "", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def _normalize_texts(items: List[str]) -> List[str]:
    return [_strip_delivery_cues(_strip_leading_enumeration(s)) for s in items]


def _clean_text(text: str) -> str:
    return text.strip().strip(' "“”') if text else ""


def _month_label(month_raw: Optional[str]) -> str:
    if not month_raw:
        return ""
    text = month_raw.strip().lower().strip("{}")
    month_map = {
        "jan": "Jan",
        "feb": "Feb",
        "mar": "Mar",
        "apr": "Apr",
        "may": "May",
        "jun": "Jun",
        "jul": "Jul",
        "aug": "Aug",
        "sep": "Sep",
        "sept": "Sep",
        "oct": "Oct",
        "nov": "Nov",
        "dec": "Dec",
    }
    return month_map.get(text, month_raw)


def _authors_for_script(authors: List[str]) -> str:
    cleaned = [_clean_text(a) for a in authors if _clean_text(a)]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{cleaned[0]} et al."


def _sanitize_paper_id(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", (raw or "")).strip("_")
    return cleaned or "custom_pdf"


def _paper_id_from_pdf_path(pdf_path: str) -> str:
    stem = Path(pdf_path).stem or "custom_pdf"
    cleaned = _sanitize_paper_id(stem)
    return cleaned


def _resolve_local_pdf_inputs(args: argparse.Namespace) -> Tuple[List[str], bool]:
    if args.doi:
        raise ValueError("--doi mode does not accept local PDF input flags.")

    if bool(args.pdf_path) == bool(args.input_dir):
        raise ValueError("Provide exactly one of --pdf-path or --input-dir (or use --doi).")

    if args.pdf_path:
        pdf_path = os.path.abspath(args.pdf_path)
        if not os.path.isfile(pdf_path):
            raise ValueError(f"PDF file not found: {pdf_path}")
        if not pdf_path.lower().endswith(".pdf"):
            raise ValueError(f"Input file is not a PDF: {pdf_path}")
        return [pdf_path], True

    input_dir = os.path.abspath(args.input_dir)
    if not os.path.isdir(input_dir):
        raise ValueError(f"Input directory not found: {input_dir}")

    pdf_paths = [
        os.path.abspath(os.path.join(input_dir, name))
        for name in sorted(os.listdir(input_dir))
        if name.lower().endswith(".pdf")
    ]
    if not pdf_paths:
        raise ValueError(f"No PDF files found in input directory: {input_dir}")
    return pdf_paths, False


def _build_local_entry(
    pdf_path: str,
    target_date: str,
    custom_paper_id: Optional[str] = None,
    custom_title: Optional[str] = None,
    origin_override: Optional[str] = None,
) -> HFPaperEntry:
    paper_id = _sanitize_paper_id(custom_paper_id) if custom_paper_id else _paper_id_from_pdf_path(pdf_path)
    raw_identifier = Path(pdf_path).stem
    title = custom_title or raw_identifier.replace("_", " ")

    entry = HFPaperEntry(
        paper_id=paper_id,
        title=title,
        summary=f"Local PDF input from {pdf_path}",
        authors=[],
        upvotes=0,
        published_at=target_date,
        pdf_path=pdf_path,
        origin=origin_override,
    )

    # In local file mode, do not perform metadata lookup.
    entry.id_type = "filename"

    return entry


def _build_entry_from_doi(
    doi: str,
    bib_path: str,
    target_date: str,
    origin_override: Optional[str] = None,
) -> HFPaperEntry:
    normalized_doi = normalize_doi(doi)
    if not normalized_doi:
        raise ValueError(f"Invalid DOI: {doi}")

    bib_entry = find_entry_by_doi(bib_path, normalized_doi)
    if not bib_entry:
        raise ValueError(f"DOI not found in Better BibTeX file: {normalized_doi}")
    if not bib_entry.file_path:
        raise ValueError(f"DOI found but attached file path is missing in Better BibTeX: {normalized_doi}")
    if not os.path.isfile(bib_entry.file_path):
        raise ValueError(f"DOI found but PDF file does not exist: {bib_entry.file_path}")

    title = bib_entry.title or normalized_doi
    paper_id = _sanitize_paper_id(normalized_doi)
    published_at = bib_entry.published_at or target_date

    return HFPaperEntry(
        paper_id=paper_id,
        title=title,
        summary=f"Loaded from Better BibTeX by DOI ({normalized_doi})",
        authors=bib_entry.authors,
        upvotes=0,
        published_at=published_at,
        pdf_path=bib_entry.file_path,
        doi=normalized_doi,
        venue=bib_entry.venue,
        published_date=bib_entry.published_at,
        published_month=bib_entry.published_month,
        source_url=bib_entry.source_url or doi_url(normalized_doi),
        id_type="doi",
        origin=origin_override,
    )


def _write_scripts_file(scripts: List[str], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for idx, script in enumerate(scripts, 1):
            clean_script = _strip_delivery_cues(_strip_leading_enumeration(script))
            f.write(f"[Slide {idx}]\n")
            f.write("Script:\n")
            f.write(clean_script.strip())
            f.write("\n\n")


def _setup_logging(config: Config) -> None:
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def _load_input_papers(
    args: argparse.Namespace,
    target_date: str,
    zotero_bib_path: str,
    origin_override: Optional[str],
) -> Tuple[List[HFPaperEntry], bool]:
    if args.doi:
        if args.pdf_path or args.input_dir:
            raise ValueError("Use either --doi or local PDF input (--pdf-path/--input-dir), not both.")
        paper = _build_entry_from_doi(
            doi=args.doi,
            bib_path=zotero_bib_path,
            target_date=target_date,
            origin_override=origin_override,
        )
        return [paper], True

    pdf_paths, single_pdf_mode = _resolve_local_pdf_inputs(args)
    papers: List[HFPaperEntry] = []

    for idx, pdf_path in enumerate(pdf_paths):
        paper = _build_local_entry(
            pdf_path=pdf_path,
            target_date=target_date,
            custom_paper_id=args.paper_id if idx == 0 and single_pdf_mode else None,
            custom_title=args.paper_title if idx == 0 and single_pdf_mode else None,
            origin_override=origin_override,
        )
        papers.append(paper)

    return papers, single_pdf_mode


def _summarize_papers(
    papers: List[HFPaperEntry],
    target_date: str,
    config: Config,
    llm_client: LLMClient,
    single_pdf_mode: bool,
    origin_override: Optional[str],
    strip_pdf_annotations_flag: bool = False,
) -> Tuple[List[PaperSummary], Dict[str, FigureLibrary], Dict[str, str]]:
    figure_libraries: Dict[str, FigureLibrary] = {}
    figure_summaries: Dict[str, List[str]] = {}
    paper_abstracts: Dict[str, str] = {}
    summaries: List[PaperSummary] = []

    for paper in papers:
        try:
            staged_paper = paper
            pdf_path = stage_local_pdf(staged_paper, target_date, config.output_base_dir)
            if not pdf_path:
                continue

            parse_pdf_path = pdf_path
            figure_out_dir: Optional[str] = None
            if strip_pdf_annotations_flag:
                parse_pdf_path = strip_pdf_annotations(
                    pdf_path,
                    os.path.join(os.path.dirname(pdf_path), "paper.no_annotations.pdf"),
                )
                # Keep a dedicated cache dir to avoid mixing with captions extracted from annotated PDFs.
                figure_out_dir = os.path.join(os.path.dirname(pdf_path), "no_annotations_assets")

            captions_path = extract_pdf_figures(parse_pdf_path, out_dir=figure_out_dir)
            figure_lib = load_figure_library(captions_path) if captions_path else None
            if figure_lib:
                figure_libraries[staged_paper.paper_id] = figure_lib
                figure_summaries[staged_paper.paper_id] = summarize_assets(figure_lib, limit=20)

            extracted = extract_core_text(parse_pdf_path)
            paper_abstracts[staged_paper.paper_id] = _clean_text(getattr(extracted, "abstract", ""))
            summary = summarize_paper(
                staged_paper,
                extracted,
                llm_client,
                figure_summaries=figure_summaries.get(staged_paper.paper_id),
            )
            if single_pdf_mode and origin_override:
                summary.origin = origin_override
            summaries.append(summary)

        except Exception as exc:
            logging.exception("Failed to process paper %s: %s", paper.paper_id, exc)

    return summaries, figure_libraries, paper_abstracts


def _asset_hint(asset: FigureAsset) -> str:
    kind = str(asset.asset_type or "Figure").title()
    if asset.number and asset.page is not None:
        return f"Page {asset.page}, {kind} {asset.number}"
    if asset.number:
        return f"{kind} {asset.number}"
    if asset.page is not None:
        return f"Page {asset.page}, {kind}"
    return kind


def _summarize_papers_debug_layout(
    papers: List[HFPaperEntry],
    target_date: str,
    config: Config,
    single_pdf_mode: bool,
    origin_override: Optional[str],
    strip_pdf_annotations_flag: bool = False,
) -> Tuple[List[PaperSummary], Dict[str, FigureLibrary], Dict[str, str]]:
    figure_libraries: Dict[str, FigureLibrary] = {}
    paper_abstracts: Dict[str, str] = {}
    summaries: List[PaperSummary] = []

    for paper in papers:
        try:
            staged_paper = paper
            pdf_path = stage_local_pdf(staged_paper, target_date, config.output_base_dir)
            if not pdf_path:
                continue

            parse_pdf_path = pdf_path
            figure_out_dir: Optional[str] = None
            if strip_pdf_annotations_flag:
                parse_pdf_path = strip_pdf_annotations(
                    pdf_path,
                    os.path.join(os.path.dirname(pdf_path), "paper.no_annotations.pdf"),
                )
                figure_out_dir = os.path.join(os.path.dirname(pdf_path), "no_annotations_assets")

            captions_path = extract_pdf_figures(parse_pdf_path, out_dir=figure_out_dir)
            figure_lib = load_figure_library(captions_path) if captions_path else None
            if not figure_lib:
                logging.warning("No figure/table assets found for %s", staged_paper.paper_id)
                continue

            figure_libraries[staged_paper.paper_id] = figure_lib

            sorted_assets = sorted(
                figure_lib.assets,
                key=lambda a: (a.page or 0, str(a.asset_type).lower(), str(a.number or "")),
            )
            debug_slides = []
            for asset in sorted_assets:
                hint = _asset_hint(asset)
                label = hint

                debug_slides.append(
                    {
                        "title": f"Debug Image Only - {label}",
                        "bullets": [],
                        "script": "",
                        "figure_hint": hint,
                    }
                )
                debug_slides.append(
                    {
                        "title": f"Debug 3 Bullets + Image - {label}",
                        "bullets": [
                            "Debug bullet 1 for layout testing.",
                            "Debug bullet 2 for layout testing.",
                            "Debug bullet 3 for layout testing.",
                        ],
                        "script": "",
                        "figure_hint": hint,
                    }
                )

            summaries.append(
                PaperSummary(
                    paper_id=staged_paper.paper_id,
                    title=staged_paper.title,
                    category="Debug",
                    one_line="Figure/table layout debug deck",
                    origin=origin_override or staged_paper.origin or "",
                    authors=staged_paper.authors,
                    venue=staged_paper.venue,
                    published_at=staged_paper.published_date or staged_paper.published_at,
                    published_month=staged_paper.published_month,
                    key_ideas=[],
                    insights=[],
                    slides=[
                        SlideSpec(
                            title=raw_slide["title"],
                            bullets=raw_slide["bullets"],
                            script=raw_slide["script"],
                            figure_hint=raw_slide["figure_hint"],
                        )
                        for raw_slide in debug_slides
                    ],
                )
            )

            logging.info(
                "Debug layout mode prepared %d slides for %s (%d assets).",
                len(debug_slides),
                staged_paper.paper_id,
                len(sorted_assets),
            )

            if single_pdf_mode and origin_override and summaries:
                summaries[-1].origin = origin_override
        except Exception as exc:
            logging.exception("Failed to process paper in debug mode %s: %s", paper.paper_id, exc)

    return summaries, figure_libraries, paper_abstracts


def _build_scripts_by_language(
    scripts: List[str],
    target_languages: List[str],
    llm_client: LLMClient,
    single_pdf_mode: bool,
    daily: DailyEpisode,
) -> Dict[str, List[str]]:
    scripts_by_lang: Dict[str, List[str]] = {"en": scripts}

    for lang in target_languages:
        if lang == "en":
            continue
        try:
            translated_scripts = translate_scripts(scripts, llm_client, lang)
            scripts_by_lang[lang] = _normalize_texts(translated_scripts)
            logging.info("Translated scripts to %s", language_display(lang))
        except Exception as exc:
            logging.exception("Failed to translate scripts to %s: %s", lang, exc)

    if single_pdf_mode and daily.papers:
        paper = daily.papers[0]
        venue = _clean_text(getattr(paper, "venue", ""))
        published_at = _clean_text(getattr(paper, "published_at", ""))
        published_month = _month_label(getattr(paper, "published_month", ""))
        author_phrase = _authors_for_script(getattr(paper, "authors", []))
        date_phrase = " ".join(part for part in [published_month, published_at] if part).strip()

        for lang in target_languages:
            if lang == "ko":
                details: List[str] = []
                if venue:
                    details.append(f"{venue} 저널")
                if date_phrase:
                    details.append(f"{date_phrase} 발행")
                if author_phrase:
                    details.append(f"저자는 {author_phrase}입니다")
                detail_sentence = " ".join(details)
                intro_script = f"안녕하세요. IS Edgar입니다. 오늘 다룰 논문은 {paper.title}입니다."
                if detail_sentence:
                    intro_script = f"{intro_script} {detail_sentence}."
            else:
                details: List[str] = []
                if venue:
                    details.append(f"published in {venue}")
                if date_phrase:
                    details.append(f"in {date_phrase}")
                if author_phrase:
                    details.append(f"by {author_phrase}")
                detail_sentence = " ".join(details)
                intro_script = f"Hi everyone. This is IS Edgar. Today's deep dive is about the paper {paper.title}."
                if detail_sentence:
                    intro_script = f"{intro_script} It was {detail_sentence}."
            if scripts_by_lang.get(lang):
                scripts_by_lang[lang][0] = intro_script

    return scripts_by_lang


def _write_scripts_by_language(
    scripts_by_lang: Dict[str, List[str]],
    target_date: str,
    output_base_dir: str,
    single_paper_id: Optional[str],
) -> None:
    for lang, lang_scripts in scripts_by_lang.items():
        scripts_path = paths.scripts_path(output_base_dir, target_date, lang, paper_id=single_paper_id)
        _write_scripts_file(lang_scripts, scripts_path)
        logging.info("Saved %s scripts to %s", language_display(lang), scripts_path)


def _render_images(
    args: argparse.Namespace,
    md_path: str,
    output_base_dir: str,
    target_date: str,
    single_paper_id: Optional[str],
) -> List[str]:
    if args.skip_render:
        logging.info("Skipping Slidev rendering step.")
        return []

    image_paths = render_markdown_to_images(
        md_path,
        paths.slide_prefix(output_base_dir, target_date, paper_id=single_paper_id),
    )
    if not image_paths:
        logging.error("No slide images generated.")
    return image_paths


def _generate_audio(
    args: argparse.Namespace,
    scripts_by_lang: Dict[str, List[str]],
    target_languages: List[str],
    config: Config,
    target_date: str,
    single_paper_id: Optional[str],
) -> Dict[str, List[str]]:
    if args.skip_tts:
        logging.info("Skipping TTS generation.")
        return {}

    tts_client = TTSClient(
        api_key=config.openai_api_key,
        model=config.openai_tts_model,
        voice=config.openai_tts_voice,
        style_instruction=config.tts_style_instruction,
        speed=config.tts_speed,
    )

    audio_by_lang: Dict[str, List[str]] = {}
    for lang in target_languages:
        scripts_for_lang = scripts_by_lang.get(lang)
        if not scripts_for_lang:
            logging.warning("No scripts available for language %s; skipping TTS.", lang)
            continue

        audio_dir = paths.audio_lang_dir(config.output_base_dir, target_date, lang, paper_id=single_paper_id)
        audio_files = tts_client.synthesize_scripts(scripts_for_lang, audio_dir)
        if audio_files:
            audio_by_lang[lang] = audio_files
        else:
            logging.error("No audio files generated for language %s.", lang)

    return audio_by_lang


def _build_videos(
    args: argparse.Namespace,
    target_languages: List[str],
    primary_language: str,
    image_paths: List[str],
    audio_by_lang: Dict[str, List[str]],
    scripts_by_lang: Dict[str, List[str]],
    output_base_dir: str,
    target_date: str,
    single_paper_id: Optional[str],
) -> Dict[str, str]:
    if args.skip_video:
        logging.info("Skipping video rendering.")
        return {}

    video_paths: Dict[str, str] = {}
    for lang in target_languages:
        audio_files = audio_by_lang.get(lang)
        if image_paths and audio_files and len(image_paths) == len(audio_files):
            lang_suffix = None if lang == primary_language else lang
            video_path = paths.video_lang_path(output_base_dir, target_date, lang_suffix, paper_id=single_paper_id)

            subtitle_scripts = scripts_by_lang.get(lang)
            if subtitle_scripts is not None and len(subtitle_scripts) != len(audio_files):
                logging.warning(
                    "Skipping subtitles for %s due to script/audio mismatch (scripts=%d, audio=%d).",
                    language_display(lang),
                    len(subtitle_scripts),
                    len(audio_files),
                )
                subtitle_scripts = None

            build_video(image_paths, audio_files, video_path, subtitle_scripts=subtitle_scripts)
            video_paths[lang] = video_path
            continue

        logging.error(
            "Cannot build video for %s: missing images or audio, or count mismatch.",
            language_display(lang),
        )

    return video_paths


def _upload_videos(
    video_paths: Dict[str, str],
    skip_upload: bool,
    config: Config,
    papers: List[HFPaperEntry],
    paper_abstracts: Dict[str, str],
    target_date: str,
    summaries_count: int,
    primary_language: str,
    single_pdf_mode: bool,
) -> None:
    if skip_upload:
        logging.info("Upload skipped by flag.")
        return

    if not video_paths:
        logging.error("No videos built to upload.")
        return

    if not (config.youtube_client_secrets and config.youtube_token_file):
        logging.warning("YouTube credentials missing. Skipping upload.")
        return

    description = build_description(papers)
    multi_language = len(video_paths) > 1

    for lang, video_path in video_paths.items():
        title_suffix = "" if (lang == primary_language and not multi_language) else f" [{language_display(lang)}]"
        if single_pdf_mode and papers:
            primary_paper = papers[0]
            base_title = _single_paper_upload_title(primary_paper)
            title = f"{base_title}{title_suffix}"
            base_desc = _single_paper_upload_description(
                primary_paper,
                paper_abstracts.get(primary_paper.paper_id, ""),
            )
            per_lang_desc = base_desc if not multi_language else f"Language: {language_display(lang)}\n\n{base_desc}"
        else:
            title = f"Information Systems Paper Review - {target_date} | {summaries_count} Paper(s){title_suffix}"
            per_lang_desc = description if not multi_language else f"Language: {language_display(lang)}\n\n{description}"
        tags = [target_date, "Information Systems", "Research", "Paper Review", language_display(lang)]
        upload_video(
            video_path,
            title,
            per_lang_desc,
            tags,
            config.youtube_client_secrets,
            config.youtube_token_file,
            config.youtube_privacy_status,
        )


def main() -> int:
    args = parse_args()
    config = load_config()
    _setup_logging(config)

    target_date = args.date or datetime.date.today().isoformat()
    target_languages = _parse_languages(args.languages, config.languages)
    primary_language = target_languages[0] if target_languages else "en"
    origin_override = _clean_text(args.origin) if args.origin else None

    logging.info("Starting local PDF pipeline for %s", target_date)
    logging.info("Narration languages: %s", ", ".join(target_languages))
    if not args.upload:
        logging.info("YouTube upload disabled by flag.")
    if not config.openai_api_key:
        logging.warning("OPENAI_API_KEY not set. LLM/TTS calls may fail.")

    try:
        zotero_bib_path = args.zotero_bib or config.zotero_bib_path
        papers, single_pdf_mode = _load_input_papers(args, target_date, zotero_bib_path, origin_override)
    except ValueError as exc:
        logging.error("%s", exc)
        return 1
    if not papers:
        logging.error("No papers retrieved. Exiting.")
        return 1

    if args.debug_figure_layout:
        logging.info("Running in debug figure layout mode (LLM/TTS/video/upload disabled).")
        summaries, figure_libraries, paper_abstracts = _summarize_papers_debug_layout(
            papers,
            target_date,
            config,
            single_pdf_mode,
            origin_override,
            strip_pdf_annotations_flag=args.strip_pdf_annotations,
        )
    else:
        llm_client = LLMClient(api_key=config.openai_api_key, model=config.openai_llm_model)
        summaries, figure_libraries, paper_abstracts = _summarize_papers(
            papers,
            target_date,
            config,
            llm_client,
            single_pdf_mode,
            origin_override,
            strip_pdf_annotations_flag=args.strip_pdf_annotations,
        )
    if not summaries:
        logging.error("No summaries created. Exiting.")
        return 1

    daily = DailyEpisode(date=target_date, papers=summaries)
    single_paper_id = daily.papers[0].paper_id if single_pdf_mode and daily.papers else None

    md_path = paths.markdown_path(config.output_base_dir, target_date, paper_id=single_paper_id)
    scripts = build_daily_markdown(
        daily,
        md_path,
        figure_libraries,
        single_pdf_mode=single_pdf_mode,
        auto_rotate_by_ocr=args.auto_rotate_by_ocr,
    )
    scripts = _normalize_texts(scripts)
    logging.info("Markdown created at %s", md_path)

    if args.debug_figure_layout:
        image_paths = _render_images(args, md_path, config.output_base_dir, target_date, single_paper_id)
        if (not args.skip_render) and (not image_paths):
            logging.error("Debug slide rendering failed.")
            return 1
        logging.info("Debug figure layout mode complete.")
        return 0

    scripts_by_lang = _build_scripts_by_language(
        scripts,
        target_languages,
        llm_client,
        single_pdf_mode,
        daily,
    )
    _write_scripts_by_language(scripts_by_lang, target_date, config.output_base_dir, single_paper_id)

    image_paths = _render_images(args, md_path, config.output_base_dir, target_date, single_paper_id)
    if (not args.skip_render) and (not image_paths):
        logging.error("Slide rendering failed; stopping before TTS/video to avoid unnecessary API calls.")
        return 1

    audio_by_lang = _generate_audio(args, scripts_by_lang, target_languages, config, target_date, single_paper_id)
    video_paths = _build_videos(
        args,
        target_languages,
        primary_language,
        image_paths,
        audio_by_lang,
        scripts_by_lang,
        config.output_base_dir,
        target_date,
        single_paper_id,
    )

    _upload_videos(
        video_paths,
        skip_upload=(not args.upload) or args.skip_upload or args.video_only,
        config=config,
        papers=papers,
        paper_abstracts=paper_abstracts,
        target_date=target_date,
        summaries_count=len(summaries),
        primary_language=primary_language,
        single_pdf_mode=single_pdf_mode,
    )

    logging.info("Pipeline complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
