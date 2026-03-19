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

import os
from dataclasses import dataclass, field
from typing import List, Optional


def _load_env_file() -> None:
    """Load .env into process env if variables are unset.

    This keeps `python main.py` working without requiring `source scripts/env.sh`.
    """
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value:
                    os.environ.setdefault(key, value)
    except OSError:
        # Best-effort only; regular env vars can still be used.
        return


_load_env_file()


def _get_languages(env_var: str, default: str) -> List[str]:
    raw = os.getenv(env_var, default)
    langs = [part.strip().lower() for part in raw.split(",") if part.strip()]
    if langs:
        return langs
    fallback = [part.strip().lower() for part in default.split(",") if part.strip()]
    return fallback or ["en"]


def _get_float(env_var: str, default: float) -> float:
    value = os.getenv(env_var)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_youtube_privacy_status(env_var: str, default: str) -> str:
    value = os.getenv(env_var, default).strip().lower()
    if value in {"public", "private", "unlisted"}:
        return value
    return default


@dataclass
class Config:
    crossref_base_url: str = os.getenv("CROSSREF_BASE_URL", "https://api.crossref.org")
    zotero_bib_path: str = os.getenv("ZOTERO_BIB_PATH", os.path.expanduser("~/Documents/better_bib.bib"))
    openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
    openai_llm_model: str = os.getenv("OPENAI_LLM_MODEL", "gpt-5.4")
    openai_tts_model: str = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    openai_tts_voice: str = os.getenv("OPENAI_TTS_VOICE", "echo")
    tts_style_instruction: Optional[str] = os.getenv("TTS_STYLE_INSTRUCTION")
    tts_speed: float = _get_float("TTS_SPEED", 1.2)
    youtube_client_secrets: Optional[str] = os.getenv("YOUTUBE_CLIENT_SECRETS_FILE")
    youtube_token_file: Optional[str] = os.getenv("YOUTUBE_TOKEN_FILE")
    youtube_privacy_status: str = _get_youtube_privacy_status("YOUTUBE_PRIVACY_STATUS", "unlisted")
    output_base_dir: str = os.getenv("OUTPUT_BASE_DIR", "./outputs")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    languages: List[str] = field(default_factory=lambda: _get_languages("LANGUAGES", "en"))


def load_config() -> Config:
    return Config()
