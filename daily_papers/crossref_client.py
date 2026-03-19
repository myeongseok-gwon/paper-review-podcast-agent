import logging
from typing import Dict, List, Optional

import requests

from .doi_utils import normalize_doi


def _extract_authors(author_rows: List[dict]) -> List[str]:
    authors: List[str] = []
    for item in author_rows or []:
        given = (item.get("given") or "").strip()
        family = (item.get("family") or "").strip()
        name = f"{given} {family}".strip()
        if name:
            authors.append(name)
            continue
        fallback = (item.get("name") or "").strip()
        if fallback:
            authors.append(fallback)
    return authors


def _extract_date_parts(message: Dict[str, object], key: str) -> Optional[str]:
    obj = message.get(key)
    if not isinstance(obj, dict):
        return None
    parts = obj.get("date-parts")
    if not isinstance(parts, list) or not parts:
        return None
    first = parts[0]
    if not isinstance(first, list) or not first:
        return None
    nums = [str(x) for x in first[:3]]
    if len(nums) == 1:
        return nums[0]
    if len(nums) == 2:
        return f"{nums[0]}-{nums[1].zfill(2)}"
    return f"{nums[0]}-{nums[1].zfill(2)}-{nums[2].zfill(2)}"


def fetch_crossref_metadata(doi: str, base_url: str = "https://api.crossref.org") -> Optional[Dict[str, object]]:
    normalized_doi = normalize_doi(doi)
    if not normalized_doi:
        return None

    url = f"{base_url.rstrip('/')}/works/{normalized_doi}"
    try:
        response = requests.get(
            url,
            timeout=20,
            headers={
                "Accept": "application/json",
                "User-Agent": "paper-review-podcast-agent/1.0 (mailto:unknown@example.com)",
            },
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logging.warning("Crossref lookup failed for DOI %s: %s", normalized_doi, exc)
        return None

    message = payload.get("message") or {}
    if not isinstance(message, dict):
        return None

    titles = message.get("title") or []
    title = titles[0].strip() if isinstance(titles, list) and titles else ""

    container = message.get("container-title") or []
    venue = container[0].strip() if isinstance(container, list) and container else ""

    published_date = (
        _extract_date_parts(message, "published-print")
        or _extract_date_parts(message, "published-online")
        or _extract_date_parts(message, "issued")
    )

    return {
        "doi": normalized_doi,
        "title": title,
        "authors": _extract_authors(message.get("author") or []),
        "venue": venue,
        "published_date": published_date,
        "source_url": message.get("URL"),
    }
