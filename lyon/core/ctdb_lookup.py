"""CUETools Database lookups using native CTDB layout strings."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

from .metadata import (
    AlbumInfo,
    CTDB_LOOKUP_URL,
    CTDB_TIMEOUT_SECONDS,
    _ctdb_album_score,
    _ctdb_meta_to_album,
    _user_agent,
)


def lookup_ctdb_layout(ctdb_toc: str | None, *, fuzzy: bool = False) -> AlbumInfo | None:
    """Look up album metadata from a CUETools-style CTDB TOC layout."""
    layout = _sanitize_ctdb_layout(ctdb_toc)
    if not layout:
        return None

    try:
        response = requests.get(
            CTDB_LOOKUP_URL,
            params={
                "version": "3",
                "ctdb": "0",
                "metadata": "extensive",
                "fuzzy": "1" if fuzzy else "0",
                "toc": layout,
            },
            headers={"User-Agent": _user_agent()},
            timeout=CTDB_TIMEOUT_SECONDS,
        )
        if response.status_code != 200 or not response.content:
            return None
    except requests.RequestException:
        return None

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError:
        return None

    candidates = [_ctdb_meta_to_album(meta) for meta in root.findall(".//metadata")]
    candidates = [info for info in candidates if info is not None]
    if not candidates:
        return None

    candidates.sort(key=_ctdb_album_score, reverse=True)
    return candidates[0]


def _sanitize_ctdb_layout(ctdb_toc: str | None) -> str:
    if not ctdb_toc:
        return ""

    tokens = [token.strip() for token in ctdb_toc.strip().split(":")]
    if len(tokens) < 2 or any(not token for token in tokens):
        return ""

    cleaned = []
    for index, token in enumerate(tokens):
        is_data_track = token.startswith("-")
        if is_data_track and index == len(tokens) - 1:
            return ""

        offset_text = token[1:] if is_data_track else token
        if not offset_text.isdigit():
            return ""

        offset = int(offset_text, 10)
        cleaned.append(f"-{offset}" if is_data_track else str(offset))
    return ":".join(cleaned)
