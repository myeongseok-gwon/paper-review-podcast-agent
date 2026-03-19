import re
from typing import Optional
from urllib.parse import unquote


DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)


def normalize_doi(raw: str) -> str:
    text = unquote((raw or "").strip())
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    return text.strip().rstrip(".").lower()


def doi_from_filename_stem(stem: str) -> Optional[str]:
    text = (stem or "").strip()
    if not text:
        return None

    normalized = normalize_doi(text)
    if DOI_PATTERN.match(normalized):
        return normalized

    # Common filesystem-friendly variant: first underscore/hyphen stands in for DOI slash.
    if re.match(r"^10\.\d{4,9}[_-].+$", text, flags=re.IGNORECASE):
        prefix, rest = re.split(r"[_-]", text, maxsplit=1)
        normalized = normalize_doi(f"{prefix}/{rest}")
        if DOI_PATTERN.match(normalized):
            return normalized

    return None


def looks_like_doi(raw: str) -> bool:
    return bool(doi_from_filename_stem(raw))


def doi_url(doi: str) -> Optional[str]:
    normalized = normalize_doi(doi)
    if not normalized:
        return None
    return f"https://doi.org/{normalized}"
