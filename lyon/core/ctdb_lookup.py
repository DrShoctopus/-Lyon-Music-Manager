"""Compatibility wrappers for CUETools Database metadata lookups."""
from __future__ import annotations

from .metadata import (
    _sanitize_ctdb_layout,
    lookup_cuetools_db_layout,
)


def lookup_ctdb_layout(ctdb_toc: str | None, *, fuzzy: bool = False):
    """Look up album metadata from a CUETools-style CTDB TOC layout."""
    return lookup_cuetools_db_layout(ctdb_toc, fuzzy=fuzzy)
