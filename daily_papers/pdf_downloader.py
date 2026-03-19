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
import shutil
from typing import Optional

from .models import HFPaperEntry
from storage import paths


def stage_local_pdf(paper: HFPaperEntry, date: str, base_dir: str) -> Optional[str]:
    if not paper.pdf_path:
        logging.error("Paper %s missing local pdf_path", paper.paper_id)
        return None
    if not os.path.isfile(paper.pdf_path):
        logging.error("Local PDF not found for %s: %s", paper.paper_id, paper.pdf_path)
        return None

    target_dir = paths.paper_dir(base_dir, date, paper.paper_id)
    paths.ensure_dir(target_dir)
    pdf_path = os.path.join(target_dir, "paper.pdf")

    src_path = os.path.abspath(paper.pdf_path)
    if os.path.exists(pdf_path) and os.path.abspath(pdf_path) == src_path:
        logging.info("Using staged PDF in-place: %s", pdf_path)
        return pdf_path

    if os.path.exists(pdf_path):
        logging.info("PDF already staged: %s", pdf_path)
        return pdf_path

    logging.info("Staging local PDF for %s from %s", paper.paper_id, src_path)
    try:
        shutil.copy2(src_path, pdf_path)
        return pdf_path
    except Exception as exc:
        logging.error("Failed to stage local PDF for %s: %s", paper.paper_id, exc)
        return None
