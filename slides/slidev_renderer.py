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

import glob
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_local_slidev_cli(theme_dir: Path) -> Path:
    """
    Ensure slidev CLI exists in local theme workspace.
    """
    cli = theme_dir / "node_modules" / ".bin" / "slidev"
    if cli.exists():
        return cli

    package_json = theme_dir / "package.json"
    if not package_json.exists():
        return cli

    install_cmd = ["npm", "install", "--no-audit", "--no-fund"]
    logging.info("Installing local Slidev runtime in %s: %s", theme_dir, shlex.join(install_cmd))
    try:
        subprocess.run(install_cmd, check=True, cwd=theme_dir.as_posix())
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        logging.warning("Failed to install local Slidev runtime: %s", exc)
    return cli


def render_markdown_to_images(md_path: str, output_prefix: str) -> List[str]:
    """
    Render markdown to PNG slides via Slidev.
    output_prefix should be a path prefix (e.g., /.../slides_2024-12-31_).
    """
    md_path_abs = os.path.abspath(md_path)
    out_parent = os.path.abspath(os.path.dirname(output_prefix) or ".")
    out_dir = tempfile.mkdtemp(prefix="slidev_export_", dir=out_parent)

    theme_dir = _repo_root() / "slidev-theme-umn"
    local_slidev = _ensure_local_slidev_cli(theme_dir)

    commands: List[List[str]] = []
    if local_slidev.exists():
        commands.append(
            [
                local_slidev.as_posix(),
                "export",
                md_path_abs,
                "--per-slide",
                "--format",
                "png",
                "--output",
                out_dir,
            ]
        )
    commands.append(["slidev", "export", md_path_abs, "--per-slide", "--format", "png", "--output", out_dir])

    exported = False
    for cmd in commands:
        logging.info("Rendering slides via Slidev: %s", shlex.join(cmd))
        try:
            # Always run from the theme workspace to avoid per-paper npm installs in outputs/*/slides.
            subprocess.run(cmd, check=True, cwd=theme_dir.as_posix())
            exported = True
            break
        except FileNotFoundError:
            continue
        except subprocess.CalledProcessError as exc:
            logging.warning("Slidev command failed: %s", exc)

    if not exported:
        logging.error(
            "Slidev CLI not found or export failed. "
            "Install @slidev/cli globally, or run npm install in slidev-theme-umn."
        )
        shutil.rmtree(out_dir, ignore_errors=True)
        return []

    rendered = sorted(glob.glob(os.path.join(out_dir, "*.png")))
    if not rendered:
        # Some Slidev versions resolve output into nested subfolders.
        rendered = sorted(glob.glob(os.path.join(out_dir, "**", "*.png"), recursive=True))
    if not rendered:
        logging.error("Slidev export succeeded but no PNG files were created.")
        shutil.rmtree(out_dir, ignore_errors=True)
        return []

    images: List[str] = []
    for idx, source in enumerate(rendered, 1):
        dest = f"{output_prefix}{idx:03d}.png"
        try:
            os.replace(source, dest)
            images.append(dest)
        except OSError as exc:
            logging.warning("Failed to move slide image %s -> %s: %s", source, dest, exc)

    shutil.rmtree(out_dir, ignore_errors=True)
    logging.info("Rendered %d slide images", len(images))
    return images
