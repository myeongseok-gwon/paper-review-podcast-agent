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

"""Extract figures/tables and captions from a PDF into captions.json.

Intended to mirror the ad-hoc test script logic and drop assets next to each
downloaded paper so the slide pipeline can auto-embed figures.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# Optional heavy deps are imported lazily inside functions.


_LABEL_MAP = {0: "Text", 1: "Title", 2: "List", 3: "Table", 4: "Figure"}
_CAPTION_PREFER = {
    "Figure": re.compile(r"^(fig(?:ure)?\.?\s*\d+(?:\.\d+)*)", re.IGNORECASE),
    "Table": re.compile(r"^(table\s*\d+(?:\.\d+)*)", re.IGNORECASE),
}
_NUMBER_PATTERNS = [
    r"\bFigure\.?\s*(\d+(?:\.\d+)*)",
    r"\bFig\.?\s*(\d+(?:\.\d+)*)",
    r"\bTable\.?\s*(\d+(?:\.\d+)*)",
]


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class _ExtractedItem:
    page: int
    block_type: str
    detected_idx: int
    number: Optional[str]
    caption: str
    file: str


def _overlap_ratio(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    overlap = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    min_width = max(1e-6, min(a_end - a_start, b_end - b_start))
    return overlap / min_width


def _extract_caption(block_type: str, bbox: Tuple[float, float, float, float], text_blocks, search_margin=350, min_overlap=0.2) -> str:
    x1, y1, x2, y2 = bbox
    below_candidates = []
    above_candidates = []
    prefer_pattern = _CAPTION_PREFER.get(block_type)

    def register_candidate(distance, overlap, text, target):
        target.append((distance, -overlap, text))

    for tb in text_blocks:
        tx1, ty1, tx2, ty2, text, *rest = tb
        text = (text or "").strip()
        if not text:
            continue
        if len(rest) >= 2 and rest[1] != 0:
            continue

        overlap = _overlap_ratio(x1, x2, tx1, tx2)
        if overlap < min_overlap:
            continue

        below_dist = ty1 - y2
        above_dist = y1 - ty2
        has_prefix = bool(prefer_pattern.search(text)) if prefer_pattern else False

        if 0 <= below_dist <= search_margin:
            register_candidate((0 if has_prefix else 1, below_dist), overlap, text, below_candidates)
        if 0 <= above_dist <= search_margin:
            register_candidate((0 if has_prefix else 1, above_dist), overlap, text, above_candidates)

    primary, fallback = (below_candidates, above_candidates) if block_type == "Figure" else (above_candidates, below_candidates)

    def pick(cands):
        prefix = [c for c in cands if c[0][0] == 0]
        chosen_pool = prefix
        if not chosen_pool:
            return None
        chosen_pool.sort()
        return chosen_pool[0][2]

    for candidates in (primary, fallback):
        caption = pick(candidates)
        if caption:
            return caption

    return ""


def _extract_number(block_type: str, caption_text: str) -> Optional[str]:
    for pat in _NUMBER_PATTERNS:
        m = re.search(pat, caption_text, flags=re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _expand_bbox(
    bbox: Tuple[float, float, float, float],
    img_width: int,
    img_height: int,
    pad_left_ratio: float,
    pad_top_ratio: float,
    pad_right_ratio: float,
    pad_bottom_ratio: float,
) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    width = max(1.0, x2 - x1)
    height = max(1.0, y2 - y1)

    pad_left = width * pad_left_ratio
    pad_top = height * pad_top_ratio
    pad_right = width * pad_right_ratio
    pad_bottom = height * pad_bottom_ratio

    nx1 = max(0, int(round(x1 - pad_left)))
    ny1 = max(0, int(round(y1 - pad_top)))
    nx2 = min(img_width, int(round(x2 + pad_right)))
    ny2 = min(img_height, int(round(y2 + pad_bottom)))
    return nx1, ny1, nx2, ny2


def _ensure_model(config_path: Path, weights_path: Path):
    try:
        import layoutparser as lp
    except Exception as exc:  # pragma: no cover - optional dependency guard
        logging.warning("layoutparser missing; figure extraction skipped: %s", exc)
        return None

    detectron_model_cls = getattr(lp, "Detectron2LayoutModel", None)
    if detectron_model_cls is None:
        # Some layoutparser builds do not expose this on top-level namespace.
        try:
            from layoutparser.models import Detectron2LayoutModel as detectron_model_cls  # type: ignore
        except Exception as exc:  # pragma: no cover
            logging.warning("Detectron2LayoutModel unavailable in layoutparser: %s", exc)
            return None

    score_thresh = _float_env("PUBLAYNET_SCORE_THRESH", 0.6)
    extra_config = ["MODEL.WEIGHTS", str(weights_path), "MODEL.ROI_HEADS.SCORE_THRESH_TEST", score_thresh]
    try:
        return detectron_model_cls(str(config_path), label_map=_LABEL_MAP, extra_config=extra_config)
    except Exception as exc:  # pragma: no cover - model load guard
        logging.warning("Failed to load PubLayNet model: %s", exc)
        return None


def _default_model_paths() -> Tuple[Path, Path]:
    root = Path(__file__).resolve().parents[1]
    base = root / "models" / "publaynet"
    return base / "config.yaml", base / "model_final.pth"


def _load_pdf(path: Path):
    try:  # pragma: no cover - import guard
        import pymupdf as fitz
    except Exception:  # pragma: no cover
        import fitz

    try:
        return fitz.open(path)
    except Exception as exc:  # pragma: no cover - open guard
        logging.warning("Failed to open PDF %s: %s", path, exc)
        return None


def _to_image(page, dpi: int):
    import numpy as np
    import cv2

    pix = page.get_pixmap(dpi=dpi)
    if pix.n == 4:
        mode = cv2.COLOR_BGRA2RGB
    elif pix.n == 3:
        mode = cv2.COLOR_BGR2RGB
    else:
        import pymupdf as fitz  # type: ignore

        pix = fitz.Pixmap(fitz.csRGB, pix)
        mode = cv2.COLOR_BGR2RGB

    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return cv2.cvtColor(img, mode)


def _extract_items(doc, model, assets_dir: Path, dpi: int) -> List[_ExtractedItem]:
    import cv2

    scale = dpi / 72
    fig_pad_ratio = _float_env("FIGURE_CROP_PAD_RATIO", 0.08)
    fig_pad_bottom_ratio = _float_env("FIGURE_CROP_PAD_BOTTOM_RATIO", 0.18)
    table_pad_ratio = _float_env("TABLE_CROP_PAD_RATIO", 0.16)
    table_pad_bottom_ratio = _float_env("TABLE_CROP_PAD_BOTTOM_RATIO", 0.28)
    table_pad_top_ratio = _float_env("TABLE_CROP_PAD_TOP_RATIO", 0.18)
    table_full_width_ratio = _float_env("TABLE_FULL_WIDTH_TRIGGER_RATIO", 0.78)
    table_margin_ratio = _float_env("TABLE_FULL_WIDTH_MARGIN_RATIO", 0.04)
    min_area_ratio = _float_env("FIGURE_MIN_AREA_RATIO", 0.0015)
    min_side_px = _int_env("FIGURE_MIN_SIDE_PX", 40)
    items: List[_ExtractedItem] = []
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        img = _to_image(page, dpi)
        img_h, img_w = img.shape[:2]
        layout = model.detect(img)

        text_blocks = []
        for tb in page.get_textpage().extractBLOCKS():
            x0, y0, x1, y1, text, block_no, block_type = tb
            text_blocks.append((x0 * scale, y0 * scale, x1 * scale, y1 * scale, text, block_no, block_type))

        for i, block in enumerate(layout):
            if block.type not in ["Figure", "Table"]:
                continue

            x1, y1, x2, y2 = block.coordinates
            raw_w = max(1.0, x2 - x1)
            if block.type == "Table":
                bx1, by1, bx2, by2 = _expand_bbox(
                    (x1, y1, x2, y2),
                    img_width=img_w,
                    img_height=img_h,
                    pad_left_ratio=table_pad_ratio,
                    pad_top_ratio=table_pad_top_ratio,
                    pad_right_ratio=table_pad_ratio,
                    pad_bottom_ratio=table_pad_bottom_ratio,
                )
                # Wide tables are often detected too tightly on the x-axis.
                if (raw_w / img_w) >= table_full_width_ratio:
                    margin = int(round(img_w * table_margin_ratio))
                    bx1 = max(0, margin)
                    bx2 = min(img_w, img_w - margin)
            else:
                bx1, by1, bx2, by2 = _expand_bbox(
                    (x1, y1, x2, y2),
                    img_width=img_w,
                    img_height=img_h,
                    pad_left_ratio=fig_pad_ratio,
                    pad_top_ratio=fig_pad_ratio,
                    pad_right_ratio=fig_pad_ratio,
                    pad_bottom_ratio=fig_pad_bottom_ratio,
                )
            box_w = bx2 - bx1
            box_h = by2 - by1
            if box_w < min_side_px or box_h < min_side_px:
                continue
            if (box_w * box_h) < (img_w * img_h * min_area_ratio):
                continue

            crop = img[by1:by2, bx1:bx2]
            filename = f"page{page_idx + 1}_{block.type}_{i + 1}.png"
            assets_dir.mkdir(parents=True, exist_ok=True)
            dest = assets_dir / filename
            cv2.imwrite(str(dest), crop)

            caption = _extract_caption(block.type, (bx1, by1, bx2, by2), text_blocks)
            number = _extract_number(block.type, caption)
            items.append(
                _ExtractedItem(
                    page=page_idx + 1,
                    block_type=block.type,
                    detected_idx=i + 1,
                    number=number,
                    caption=caption,
                    file=str(Path(assets_dir.name) / filename),
                )
            )

    return items


def extract_pdf_figures(pdf_path: str, out_dir: Optional[str] = None) -> Optional[str]:
    """Run layout detection and write captions.json next to the PDF.

    Returns the path to captions.json if extraction succeeded, else None.
    Skips work if captions.json already exists.
    """

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        logging.warning("PDF not found for figure extraction: %s", pdf_path)
        return None

    out_dir_path = Path(out_dir) if out_dir else pdf_path.parent
    out_dir_path.mkdir(parents=True, exist_ok=True)
    captions_path = out_dir_path / "captions.json"
    assets_dir = out_dir_path / "figures"
    if captions_path.exists():
        logging.info("captions.json already exists, skipping extraction: %s", captions_path)
        return str(captions_path)

    default_cfg, default_weights = _default_model_paths()
    config_path = Path(os.getenv("PUBLayNET_CONFIG", default_cfg))
    weights_path = Path(os.getenv("PUBLayNET_WEIGHTS", default_weights))

    if not config_path.exists() or not weights_path.exists():
        logging.warning("PubLayNet model files missing (config: %s, weights: %s); skipping figure extraction", config_path, weights_path)
        return None

    model = _ensure_model(config_path, weights_path)
    if not model:
        return None

    doc = _load_pdf(pdf_path)
    if not doc:
        return None

    dpi = _int_env("FIGURE_RENDER_DPI", 350)
    try:
        items = _extract_items(doc, model, assets_dir, dpi=dpi)
    except Exception as exc:  # pragma: no cover - runtime guard
        logging.warning("Figure extraction failed for %s: %s", pdf_path, exc)
        return None

    results = []
    for item in items:
        data = item.__dict__.copy()
        # Save a normalized `type` field so downstream consumers don't have to
        # special-case the internal block_type name.
        data.setdefault("type", item.block_type)
        results.append(data)
    try:
        captions_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        logging.info("Figure captions written to %s (%d items)", captions_path, len(results))
        return str(captions_path)
    except Exception as exc:  # pragma: no cover - IO guard
        logging.warning("Failed to write captions.json for %s: %s", pdf_path, exc)
        return None
