"""Equalizer band definitions, gain limits, and preset curves."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

EQ_BANDS: tuple[tuple[str, str], ...] = (
    ("60 Hz", "Sub bass weight and kick-drum thump"),
    ("170 Hz", "Bass body and warmth"),
    ("310 Hz", "Low-mid fullness"),
    ("600 Hz", "Boxiness and lower vocal body"),
    ("1 kHz", "Midrange focus"),
    ("3 kHz", "Presence and vocal clarity"),
    ("6 kHz", "Attack, detail, and edge"),
    ("12 kHz", "Air and sparkle"),
    ("14 kHz", "Upper shimmer"),
    ("16 kHz", "Extreme top-end air"),
)

EQ_BAND_COUNT = len(EQ_BANDS)
MIN_EQ_GAIN_DB = -12
MAX_EQ_GAIN_DB = 12
DEFAULT_EQ_CURVE_NAME = "Flat"
UNSAVED_EQ_CURVE_NAME = "Custom (unsaved)"

# Five common listening curves. Flat is still available as the reset/default
# curve, but these are the musical presets shown first in the picker.
BUILTIN_EQ_CURVES: dict[str, list[int]] = {
    "Bass Boost": [5, 4, 3, 1, 0, 0, 0, 1, 1, 1],
    "Treble Boost": [-1, -1, 0, 0, 0, 2, 4, 5, 5, 5],
    "Vocal Clarity": [-2, -1, 0, 1, 2, 4, 3, 1, 0, 0],
    "Rock": [4, 3, 1, -1, 0, 2, 4, 3, 2, 2],
    "Classical": [2, 1, 0, 0, 0, 1, 2, 3, 3, 2],
}
RESERVED_EQ_CURVE_NAMES = frozenset(
    (DEFAULT_EQ_CURVE_NAME, UNSAVED_EQ_CURVE_NAME, *BUILTIN_EQ_CURVES)
)


def normalize_equalizer_bands(bands: Iterable[Any] | None) -> list[int]:
    """Return exactly ten integer EQ gains clamped to Lyon's UI range.

    Settings files are user-editable JSON, so malformed values are treated as
    flat bands instead of preventing the app from loading.
    """
    try:
        values = list(bands or [])[:EQ_BAND_COUNT]
    except TypeError:
        values = []
    values.extend([0] * (EQ_BAND_COUNT - len(values)))
    return [_clamp_gain(value) for value in values]


def flat_equalizer_bands() -> list[int]:
    """Return a new flat ten-band EQ curve."""
    return [0] * EQ_BAND_COUNT


def _clamp_gain(value: Any) -> int:
    try:
        gain = int(value)
    except (TypeError, ValueError):
        gain = 0
    return max(MIN_EQ_GAIN_DB, min(MAX_EQ_GAIN_DB, gain))
