"""Compatibility wrappers for CUETools Database metadata lookups."""
from __future__ import annotations

from .metadata import (
    lookup_cuetools_db_layout,
    sanitize_ctdb_layout,
)

# Expose the previously-private sanitizer under its old name so existing
# call sites (including tests) continue to work during the transition period.
_sanitize_ctdb_layout = sanitize_ctdb_layout


def lookup_ctdb_layout(ctdb_toc: str | None, *, fuzzy: bool = False):
    """Look up album metadata from a CUETools-style CTDB TOC layout."""
    return lookup_cuetools_db_layout(ctdb_toc, fuzzy=fuzzy)
