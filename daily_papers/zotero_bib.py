import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from .doi_utils import doi_url, normalize_doi


@dataclass
class ZoteroBibEntry:
    doi: Optional[str]
    title: str
    authors: List[str]
    venue: Optional[str]
    published_at: Optional[str]
    published_month: Optional[str]
    file_path: Optional[str]
    source_url: Optional[str]


def _iter_entry_blocks(text: str) -> List[str]:
    blocks: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        at = text.find("@", i)
        if at < 0:
            break
        brace = text.find("{", at)
        if brace < 0:
            break
        depth = 0
        j = brace
        while j < n:
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(text[at : j + 1])
                    i = j + 1
                    break
            j += 1
        else:
            break
    return blocks


def _parse_fields(block: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    start = block.find("{")
    if start < 0:
        return fields

    comma = block.find(",", start)
    if comma < 0:
        return fields
    body = block[comma + 1 :].rstrip().rstrip("}")

    i = 0
    n = len(body)
    while i < n:
        while i < n and body[i] in " \t\r\n,":
            i += 1
        if i >= n:
            break

        key_start = i
        while i < n and (body[i].isalnum() or body[i] in "_-"):
            i += 1
        key = body[key_start:i].strip().lower()
        if not key:
            i += 1
            continue

        while i < n and body[i].isspace():
            i += 1
        if i >= n or body[i] != "=":
            continue
        i += 1
        while i < n and body[i].isspace():
            i += 1
        if i >= n:
            break

        value = ""
        if body[i] == "{":
            depth = 0
            i += 1
            start_val = i
            while i < n:
                ch = body[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    if depth == 0:
                        value = body[start_val:i]
                        i += 1
                        break
                    depth -= 1
                i += 1
        elif body[i] == '"':
            i += 1
            start_val = i
            while i < n:
                if body[i] == '"' and body[i - 1] != "\\":
                    value = body[start_val:i]
                    i += 1
                    break
                i += 1
        else:
            start_val = i
            while i < n and body[i] not in ",\n\r":
                i += 1
            value = body[start_val:i].strip()

        fields[key] = value.strip()
        while i < n and body[i] not in ",\n\r":
            i += 1
        if i < n and body[i] == ",":
            i += 1

    return fields


def _parse_authors(raw: str) -> List[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(" and ") if part.strip()]


def _parse_file_path(raw: str) -> Optional[str]:
    if not raw:
        return None
    # Better BibTeX can contain multiple attachments separated by ';'
    first = raw.split(";")[0].strip()
    if not first:
        return None
    # Some exports include "path:label" style; prefer path token.
    if ":" in first and not first.startswith("/"):
        first = first.split(":", 1)[0].strip()
    return os.path.abspath(os.path.expanduser(first)) if first else None


def _to_entry(fields: Dict[str, str]) -> ZoteroBibEntry:
    raw_doi = fields.get("doi", "").strip()
    doi = normalize_doi(raw_doi) if raw_doi else None
    url = fields.get("url") or fields.get("howpublished") or None
    return ZoteroBibEntry(
        doi=doi,
        title=fields.get("title", "").strip(),
        authors=_parse_authors(fields.get("author", "")),
        venue=(
            fields.get("journal")
            or fields.get("booktitle")
            or fields.get("publisher")
            or None
        ),
        published_at=fields.get("year") or None,
        published_month=fields.get("month") or None,
        file_path=_parse_file_path(fields.get("file", "")),
        source_url=url or (doi_url(doi) if doi else None),
    )


def find_entry_by_doi(bib_path: str, doi: str) -> Optional[ZoteroBibEntry]:
    bib_path = os.path.abspath(os.path.expanduser(bib_path))
    if not os.path.isfile(bib_path):
        return None

    target = normalize_doi(doi)
    if not target:
        return None

    with open(bib_path, "r", encoding="utf-8") as f:
        text = f.read()

    for block in _iter_entry_blocks(text):
        fields = _parse_fields(block)
        raw_doi = fields.get("doi", "")
        if not raw_doi:
            continue
        if normalize_doi(raw_doi) == target:
            return _to_entry(fields)
    return None
