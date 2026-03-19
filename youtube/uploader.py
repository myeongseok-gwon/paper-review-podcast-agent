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
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _sanitize_youtube_title(raw_title: str) -> str:
    # YouTube title must be non-empty and <= 100 chars.
    collapsed = " ".join((raw_title or "").split()).strip().strip(' "“”')
    if not collapsed:
        return "Untitled"
    if len(collapsed) > 100:
        return collapsed[:100].rstrip()
    return collapsed


def _sanitize_youtube_description(raw_description: str, fallback_title: str) -> str:
    cleaned = (raw_description or "").strip()
    return cleaned if cleaned else f"{fallback_title}\n\nDescription not available."


def get_youtube_client(client_secrets: str, token_file: str) -> Optional[any]:
    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secrets, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as token:
            token.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: List[str],
    client_secrets: str,
    token_file: str,
    privacy_status: str = "unlisted",
) -> Optional[str]:
    if not os.path.exists(video_path):
        logging.error("Video file not found: %s", video_path)
        return None

    youtube = get_youtube_client(client_secrets, token_file)
    normalized_privacy = privacy_status.strip().lower()
    if normalized_privacy not in {"public", "private", "unlisted"}:
        logging.warning("Invalid YOUTUBE_PRIVACY_STATUS '%s'. Falling back to 'private'.", privacy_status)
        normalized_privacy = "private"
    safe_title = _sanitize_youtube_title(title)
    safe_description = _sanitize_youtube_description(description, safe_title)

    body = {
        "snippet": {"title": safe_title, "description": safe_description, "tags": tags, "categoryId": "28"},
        "status": {"privacyStatus": normalized_privacy},
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    logging.info("Uploading video to YouTube...")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    video_id = response.get("id")
    logging.info("YouTube upload complete: %s", video_id)
    return video_id
