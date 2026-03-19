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

import logging
import os
import re
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from llm.summarizer import DailyEpisode, SlideSpec
from slides.figure_assets import FigureAsset, FigureLibrary, extract_reference_detail, rewrite_caption

DEFAULT_EMBED_IMAGE_WIDTH_WITH_TEXT = "90%"
DEFAULT_EMBED_IMAGE_WIDTH_VISUAL_ONLY = "92%"
DEFAULT_MAX_IMAGE_HEIGHT_WITH_TEXT = "54vh"
DEFAULT_MAX_IMAGE_HEIGHT_VISUAL_ONLY = "68vh"
DEFAULT_OCR_ROTATE_MIN_CONFIDENCE = 8.0

_OCR_BACKEND_UNAVAILABLE_LOGGED = False


def _sanitize_markdown_text(text: str) -> str:
    """Make text safe for Slidev/Vue markdown rendering.

    - Unwrap common LaTeX-style macros like \textsc{AI} -> AI.
    - Remove remaining curly braces to avoid Vue moustache parsing ({{ ... }}).
    """
    value = text or ""

    # Repeatedly unwrap simple latex commands.
    prev = None
    while prev != value:
        prev = value
        value = re.sub(r"\\[A-Za-z]+\{([^{}]*)\}", r"\1", value)

    # Remove any remaining braces to prevent Vue interpolation parse errors.
    value = value.replace("{", "").replace("}", "")
    return " ".join(value.split()).strip()


def _clean_origin(text: str) -> str:
    return text.strip().strip(' "“”') if text else ""


def _month_label(month_raw: str) -> str:
    text = (month_raw or "").strip().lower().strip("{}")
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
    return month_map.get(text, month_raw or "")


def _authors_for_slide(authors: List[str]) -> str:
    cleaned = [_normalize_author_text(a) for a in (authors or []) if a and a.strip()]
    return ", ".join(cleaned) if cleaned else "n/a"


def _format_slidev_date(date_text: str) -> str:
    try:
        return datetime.strptime((date_text or "").strip(), "%Y-%m-%d").strftime("%Y/%m/%d")
    except ValueError:
        return date_text


def _normalize_author_text(text: str) -> str:
    value = text or ""
    # Handle common LaTeX accent notations such as F{\"u}gener.
    value = re.sub(r'\{\\["\'`^~=.uvHcbdkrt]\s*([A-Za-z])\}', r"\1", value)
    value = re.sub(r'\\["\'`^~=.uvHcbdkrt]\s*([A-Za-z])', r"\1", value)
    value = value.replace("{", "").replace("}", "").replace("\\", "")
    value = " ".join(value.split()).strip()
    return value


def _strip_diacritics(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _first_author_display(authors: List[str]) -> str:
    cleaned = [a.strip() for a in (authors or []) if a and a.strip()]
    cleaned = [_normalize_author_text(a) for a in cleaned]
    if not cleaned:
        return "Unknown Author"

    first = cleaned[0]
    if len(cleaned) == 1:
        return _strip_diacritics(first)

    if "," in first:
        family = first.split(",", 1)[0].strip()
    else:
        parts = first.split()
        family = parts[-1] if parts else first
    return f"{_strip_diacritics(family)} et al."


def _theme_reference(out_path: str) -> str:
    out_dir = Path(out_path).resolve().parent
    theme_dir = Path(__file__).resolve().parents[1] / "slidev-theme-umn"
    rel = os.path.relpath(theme_dir.as_posix(), start=out_dir.as_posix())
    rel_posix = rel.replace("\\", "/")
    if rel_posix.startswith("."):
        return rel_posix
    return f"./{rel_posix}"


def _resolve_figure_asset(
    slide: SlideSpec,
    figure_library: Optional[FigureLibrary],
) -> Optional[FigureAsset]:
    if not figure_library:
        return None

    if slide.figure_hint:
        ref_type, number, page = extract_reference_detail(slide.figure_hint)
        if ref_type:
            asset = figure_library.find(ref_type, number, page=page)
            if asset:
                return asset

        asset = figure_library.search_caption(slide.figure_hint)
        if asset:
            return asset
    return None


def _auto_rotate_image_by_ocr(image_path: Path) -> None:
    """Rotate image to upright orientation using OCR orientation detection."""
    global _OCR_BACKEND_UNAVAILABLE_LOGGED

    try:
        import cv2  # type: ignore
        import pytesseract  # type: ignore
    except Exception:
        if not _OCR_BACKEND_UNAVAILABLE_LOGGED:
            logging.warning(
                "OCR auto-rotate requested but pytesseract/cv2 is unavailable. "
                "Install tesseract + pytesseract to enable this feature."
            )
            _OCR_BACKEND_UNAVAILABLE_LOGGED = True
        return

    try:
        img = cv2.imread(image_path.as_posix(), cv2.IMREAD_UNCHANGED)
        if img is None:
            return

        osd = pytesseract.image_to_osd(img)
        rotate_match = re.search(r"Rotate:\s*(\d+)", osd)
        conf_match = re.search(r"Orientation confidence:\s*([0-9.]+)", osd, flags=re.IGNORECASE)
        if not rotate_match:
            return

        rotate_deg = int(rotate_match.group(1)) % 360
        confidence = float(conf_match.group(1)) if conf_match else 0.0
        if confidence < DEFAULT_OCR_ROTATE_MIN_CONFIDENCE:
            return

        rotated = None
        if rotate_deg == 90:
            rotated = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        elif rotate_deg == 180:
            rotated = cv2.rotate(img, cv2.ROTATE_180)
        elif rotate_deg == 270:
            rotated = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)

        if rotated is None:
            return

        cv2.imwrite(image_path.as_posix(), rotated)
        logging.info(
            "OCR auto-rotated image %s by %d degrees (confidence=%.2f)",
            image_path,
            rotate_deg,
            confidence,
        )
    except Exception as exc:
        # Best effort only.
        logging.debug("OCR auto-rotate skipped for %s: %s", image_path, exc)


def _attach_figure_to_slide(
    slide: SlideSpec,
    asset: Optional[FigureAsset],
    out_dir: Path,
    paper_idx: int,
    slide_idx: int,
    auto_rotate_by_ocr: bool = False,
) -> None:
    if not asset:
        return

    figures_dir = out_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    suffix = asset.path.suffix or ".png"
    name_parts = [f"paper{paper_idx}", f"slide{slide_idx}"]
    if asset.number:
        name_parts.append(f"no{asset.number}")
    dest = figures_dir / ("_".join(name_parts) + suffix)

    try:
        shutil.copyfile(asset.path, dest)
    except Exception as exc:
        logging.warning("Failed to copy figure asset %s -> %s: %s", asset.path, dest, exc)
        return

    if auto_rotate_by_ocr and str(asset.asset_type).lower().startswith("table"):
        _auto_rotate_image_by_ocr(dest)

    slide.figure_image = dest.resolve().as_posix()
    slide.figure_caption = rewrite_caption(asset, slide.figure_hint, max_len=90)


def _image_style_for_slide(slide: SlideSpec) -> str:
    return (
        "max-height:100% !important; "
        "max-width:100% !important; "
        "height:auto !important; "
        "width:auto !important; "
        "display:block; "
        "object-fit:contain;"
    )


def _image_container_style_for_slide(slide: SlideSpec) -> str:
    has_text = bool(slide.bullets)
    max_h = DEFAULT_MAX_IMAGE_HEIGHT_WITH_TEXT if has_text else DEFAULT_MAX_IMAGE_HEIGHT_VISUAL_ONLY
    max_w = DEFAULT_EMBED_IMAGE_WIDTH_WITH_TEXT if has_text else DEFAULT_EMBED_IMAGE_WIDTH_VISUAL_ONLY
    return (
        f"height:{max_h}; "
        f"max-width:{max_w}; "
        "width:100%; "
        "margin:6px auto 8px auto; "
        "display:flex; "
        "align-items:center; "
        "justify-content:center; "
        "overflow:hidden;"
    )


def _llm_slide_body(_idx: int, _slide_idx: int, slide: SlideSpec, _single_pdf_mode: bool) -> str:
    safe_title = _sanitize_markdown_text(slide.title)
    lines: List[str] = [f"# {safe_title}"]

    if slide.bullets:
        lines.append("")
        for bullet in slide.bullets:
            lines.append(f"- {_sanitize_markdown_text(bullet)}")

    if slide.figure_image:
        caption = _sanitize_markdown_text((slide.figure_caption or slide.figure_hint or "Figure").strip())
        img_style = _image_style_for_slide(slide)
        container_style = _image_container_style_for_slide(slide)
        lines.append("")
        lines.append(f'<div style="{container_style}">')
        lines.append(f'<img src="{slide.figure_image}" alt="{caption}" style="{img_style}"/>')
        lines.append("</div>")

    return "\n".join(lines)


def _asset_label(asset: FigureAsset) -> str:
    base = f"{asset.asset_type} {asset.number}" if asset.number else str(asset.asset_type)
    if asset.page is not None:
        return f"{base} (p{asset.page})"
    return base


def _append_unused_assets_as_slides(
    *,
    paper_idx: int,
    paper_slide_count: int,
    paper_library: Optional[FigureLibrary],
    used_asset_paths: set[str],
    out_dir: Path,
    single_pdf_mode: bool,
    auto_rotate_by_ocr: bool,
    slide_blocks: List[str],
    scripts: List[str],
) -> int:
    if not paper_library:
        return 0

    appended = 0
    next_slide_idx = paper_slide_count + 1
    for asset in paper_library.assets:
        key = asset.path.resolve().as_posix()
        if key in used_asset_paths:
            continue

        title = f"Appendix: {_asset_label(asset)}"
        slide = SlideSpec(
            title=title,
            bullets=[],
            script=f"Let's quickly review {_asset_label(asset)}.",
            figure_hint=title,
        )
        _attach_figure_to_slide(
            slide,
            asset,
            out_dir,
            paper_idx,
            next_slide_idx,
            auto_rotate_by_ocr=auto_rotate_by_ocr,
        )
        if not slide.figure_image:
            continue

        slide_blocks.append(_llm_slide_body(paper_idx, next_slide_idx, slide, single_pdf_mode).strip())
        scripts.append(slide.script.strip())
        used_asset_paths.add(key)
        appended += 1
        next_slide_idx += 1
    return appended


def build_daily_markdown(
    daily: DailyEpisode,
    out_path: str,
    figure_libraries: Optional[Dict[str, FigureLibrary]] = None,
    single_pdf_mode: bool = False,
    auto_rotate_by_ocr: bool = False,
) -> List[str]:
    """
    Build Slidev markdown in a simple, theme-friendly format.
    """
    out_dir = Path(out_path).parent
    formatted_date = _format_slidev_date(daily.date)
    cover_authors = daily.papers[0].authors if daily.papers else []
    center_author = _first_author_display(cover_authors)
    theme_ref = _theme_reference(out_path)
    lines: List[str] = [
        "---",
        f'theme: "{theme_ref}"',
        "colorSchema: auto",
        'author: "Myeongseok (Edgar) Gwon"',
        f'title: "{center_author}"',
        f'date: "{formatted_date}"',
        "transition: slide-left",
        "---",
        "",
    ]

    slide_blocks: List[str] = []
    scripts: List[str] = []

    if single_pdf_mode and daily.papers:
        paper = daily.papers[0]
        venue = _clean_origin(getattr(paper, "venue", ""))
        year = _clean_origin(getattr(paper, "published_at", ""))
        month = _month_label(_clean_origin(getattr(paper, "published_month", "")))
        pub_date = " ".join(part for part in [month, year] if part).strip() or "n/a"
        intro_body = "\n".join(
            [
                f"# {_sanitize_markdown_text(paper.title)}",
                "",
                f"## {_authors_for_slide(getattr(paper, 'authors', []))}",
                "",
                f"## {venue or 'n/a'}, {pub_date}",
            ]
        )
        intro_script = (
            f"안녕하세요. IS Edgar입니다. "
            f"오늘의 꼬리의 꼬리를 무는 페이퍼 딥다이브, 꼬꼬페에서 다룰 내용은 {paper.title}입니다."
        )
    else:
        intro_body = "\n".join(
            [
                "# Information Systems Paper Review",
                "",
                "## Myeongseok (Edgar) Gwon",
                "",
                f"### Weekly ISSS, {formatted_date}",
                "",
                f"## {len(daily.papers)} paper(s) from local PDF collection",
            ]
        )
        intro_script = (
            f"Hi Everyone. This is IS Edgar. "
            f"Information Systems paper review for {daily.date}. "
            f"This episode covers {len(daily.papers)} papers from local PDF inputs."
        )

    slide_blocks.append(intro_body.strip())
    scripts.append(intro_script.strip())

    for idx, paper in enumerate(daily.papers, 1):
        paper_library = figure_libraries.get(paper.paper_id) if figure_libraries else None
        used_asset_paths: set[str] = set()

        for slide_idx, slide in enumerate(paper.slides, 1):
            asset = _resolve_figure_asset(slide, paper_library)
            _attach_figure_to_slide(
                slide,
                asset,
                out_dir,
                idx,
                slide_idx,
                auto_rotate_by_ocr=auto_rotate_by_ocr,
            )
            if asset:
                used_asset_paths.add(asset.path.resolve().as_posix())
            slide_blocks.append(_llm_slide_body(idx, slide_idx, slide, single_pdf_mode).strip())
            scripts.append((slide.script or " ".join(slide.bullets)).strip())

        appended = _append_unused_assets_as_slides(
            paper_idx=idx,
            paper_slide_count=len(paper.slides),
            paper_library=paper_library,
            used_asset_paths=used_asset_paths,
            out_dir=out_dir,
            single_pdf_mode=single_pdf_mode,
            auto_rotate_by_ocr=auto_rotate_by_ocr,
            slide_blocks=slide_blocks,
            scripts=scripts,
        )
        if appended:
            logging.info("Appended %d unused figure/table slides for %s", appended, paper.paper_id)

    slide_blocks.append(
        "\n".join(
            [
                "section: Final words",
                "layout: center",
                'class: "text-center"',
                "---",
                "",
                "# Thank you!",
            ]
        ).strip()
    )
    scripts.append("Thank you for watching. See you in the next paper review.")

    normalized_blocks = [block for block in slide_blocks if block]
    if normalized_blocks:
        merged = normalized_blocks[0]
        for block in normalized_blocks[1:]:
            if block.startswith("section:"):
                merged += "\n\n---\n" + block
            else:
                merged += "\n\n---\n\n" + block
        lines.append(merged)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return scripts
