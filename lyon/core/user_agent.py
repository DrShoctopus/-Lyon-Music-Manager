"""Shared outbound HTTP User-Agent helpers."""
from __future__ import annotations

from .. import __version__
from .settings import DEFAULT_MUSICBRAINZ_CONTACT, Settings


def _contact(settings: Settings) -> str:
    contact = (settings.musicbrainz_contact or "").strip()
    return contact or DEFAULT_MUSICBRAINZ_CONTACT


def component_user_agent(component: str, settings: Settings) -> str:
    """Return Sea Lyon's app UA for non-MusicBrainz integrations."""
    return f"Sea Lyon Media Manager/{__version__} (+{_contact(settings)}) {component}/1.0"


def musicbrainz_user_agent(settings: Settings) -> str:
    """Return the MusicBrainz-compatible app/version/contact UA."""
    app = (settings.musicbrainz_app or "Sea Lyon Media Manager").strip()
    version = (settings.musicbrainz_version or __version__).strip()
    return f"{app}/{version} ({_contact(settings)})"
