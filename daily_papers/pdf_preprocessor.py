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

from __future__ import annotations

import logging
from pathlib import Path

try:  # pragma: no cover - import guard
    import pymupdf as fitz  # type: ignore
except Exception:  # pragma: no cover - fallback
    import fitz  # type: ignore


def strip_pdf_annotations(src_pdf_path: str, out_pdf_path: str) -> str:
    """
    Save a copy of the PDF with page annotations removed.
    Returns the output path; if stripping fails, returns the original source path.
    """
    src = Path(src_pdf_path)
    out = Path(out_pdf_path)

    if not src.exists():
        logging.warning("PDF not found for annotation stripping: %s", src)
        return src_pdf_path

    try:
        doc = fitz.open(src.as_posix())
        removed_count = 0
        for page in doc:
            annot = page.first_annot
            while annot is not None:
                next_annot = annot.next
                page.delete_annot(annot)
                removed_count += 1
                annot = next_annot

        out.parent.mkdir(parents=True, exist_ok=True)
        doc.save(out.as_posix(), garbage=4, deflate=True)
        doc.close()
        logging.info("Saved annotation-free PDF to %s (removed %d annotations)", out, removed_count)
        return out.as_posix()
    except Exception as exc:  # pragma: no cover - IO/runtime guard
        logging.warning("Failed to strip annotations from %s: %s", src, exc)
        return src_pdf_path
