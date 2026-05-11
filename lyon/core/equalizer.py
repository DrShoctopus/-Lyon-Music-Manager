"""Shared six-band equalizer helpers."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

EQ_BAND_COUNT = 6
MIN_GAIN_DB = -12
MAX_GAIN_DB = 12
DEFAULT_EQUALIZER_BANDS = (0,) * EQ_BAND_COUNT


def normalize_equalizer_bands(values: Iterable[Any] | None) -> list[int]:
    """Return a valid six-band EQ curve from user/config input.

    Settings are loaded from JSON, so defensive normalization keeps corrupt or
    hand-edited config files from crashing the player or equalizer window.
    Invalid/missing bands are treated as flat (0 dB), and valid bands are
    clamped to the supported +/-12 dB range.
    """
    normalized: list[int] = []
    if values is None:
        values = ()

    try:
        iterator = iter(values)
    except TypeError:
        iterator = iter(())

    for value in iterator:
        if len(normalized) >= EQ_BAND_COUNT:
            break
        try:
            gain = int(value)
        except (TypeError, ValueError, OverflowError):
            gain = 0
        normalized.append(max(MIN_GAIN_DB, min(MAX_GAIN_DB, gain)))

    normalized.extend(DEFAULT_EQUALIZER_BANDS[: EQ_BAND_COUNT - len(normalized)])
    return normalized
