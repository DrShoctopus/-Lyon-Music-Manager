from __future__ import annotations

from lyon.core.equalizer import normalize_equalizer_bands
from lyon.core.settings import Settings


def test_equalizer_bands_are_normalized_and_clamped():
    assert normalize_equalizer_bands([20, -20, "6", None, "bad", 3.8, 99]) == [
        12,
        -12,
        6,
        0,
        0,
        3,
    ]


def test_equalizer_bands_fall_back_to_flat_for_missing_or_invalid_values():
    assert normalize_equalizer_bands(None) == [0, 0, 0, 0, 0, 0]
    assert normalize_equalizer_bands(7) == [0, 0, 0, 0, 0, 0]
    assert normalize_equalizer_bands([4, -4]) == [4, -4, 0, 0, 0, 0]


def test_settings_normalize_malformed_equalizer_values_on_init():
    settings = Settings(equalizer_enabled=1, equalizer_bands=[24, "bad", -24])

    assert settings.equalizer_enabled is True
    assert settings.equalizer_bands == [12, 0, -12, 0, 0, 0]
