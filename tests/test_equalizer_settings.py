from __future__ import annotations

from lyon.core.equalizer import BUILTIN_EQ_CURVES, EQ_BAND_COUNT, normalize_equalizer_bands
from lyon.core.settings import Settings, normalize_library_paths


def test_equalizer_defaults_to_ten_flat_bands_and_ten_presets():
    settings = Settings()

    assert len(settings.equalizer_bands) == EQ_BAND_COUNT == 10
    assert settings.equalizer_bands == [0] * 10
    assert len(BUILTIN_EQ_CURVES) == 10
    assert all(len(curve) == 10 for curve in BUILTIN_EQ_CURVES.values())


def test_settings_migrates_old_six_band_curves_and_custom_curves():
    settings = Settings(
        equalizer_bands=[1, 2, 3, 4, 5, 6],
        equalizer_custom_curves={"My Curve": [20, -20, 3]},
    )

    assert settings.equalizer_bands == [1, 2, 3, 4, 5, 6, 0, 0, 0, 0]
    assert settings.equalizer_custom_curves["My Curve"] == [12, -12, 3, 0, 0, 0, 0, 0, 0, 0]


def test_normalize_equalizer_bands_clamps_to_ten_bands():
    assert normalize_equalizer_bands([99] * 12) == [12] * 10
    assert normalize_equalizer_bands(7) == [0] * 10


def test_settings_ignores_reserved_custom_names_and_malformed_curves():
    settings = Settings(
        equalizer_bands=None,
        equalizer_curve_name="Custom (unsaved)",
        equalizer_custom_curves={
            "Rock": [1, 2, 3],
            "Valid": ["5", object(), None],
        },
    )

    assert settings.equalizer_bands == [0] * 10
    assert settings.equalizer_curve_name == "Flat"
    assert settings.equalizer_custom_curves == {"Valid": [5, 0, 0, 0, 0, 0, 0, 0, 0, 0]}


def test_settings_resets_stale_selected_custom_curve_name():
    settings = Settings(equalizer_curve_name="Missing", equalizer_custom_curves={"Saved": [1]})

    assert settings.equalizer_curve_name == "Flat"


def test_equalizer_preamp_defaults_and_clamps():
    assert Settings().equalizer_preamp == 0
    assert Settings(equalizer_preamp=20).equalizer_preamp == 20
    assert Settings(equalizer_preamp=-20).equalizer_preamp == -20
    assert Settings(equalizer_preamp=99).equalizer_preamp == 20
    assert Settings(equalizer_preamp=-99).equalizer_preamp == -20
    assert Settings(equalizer_preamp="bad").equalizer_preamp == 0
    assert Settings(equalizer_preamp=None).equalizer_preamp == 0


def test_library_paths_are_normalized_without_duplicates():
    assert normalize_library_paths(["", "  /music/a  ", "/music/a", "/music/b"]) == [
        "/music/a",
        "/music/b",
    ]
    assert normalize_library_paths("/music/a") == []

    settings = Settings(library_paths=["/music/a", "/music/a", " /music/b "])

    assert settings.library_paths == ["/music/a", "/music/b"]


def test_watch_library_folders_setting_normalizes_string_values():
    assert Settings(watch_library_folders="false").watch_library_folders is False
    assert Settings(watch_library_folders="yes").watch_library_folders is True


def test_settings_clamps_user_editable_numeric_and_format_fields():
    settings = Settings(
        rip_format="invalid",
        flac_compression="loud",
        rip_audio_bitrate="huge",
        last_volume="very",
        queue_current_index=-4,
        crossfade_seconds="soon",
        yt_audio_format="wav",
        yt_video_format="avi",
    )

    assert settings.rip_format == "flac"
    assert settings.flac_compression == 4
    assert settings.rip_audio_bitrate == 320
    assert settings.last_volume == 80
    assert settings.queue_current_index == 0
    assert settings.crossfade_seconds == 0
    assert settings.yt_audio_format == "flac"
    assert settings.yt_video_format == "mp4"


def test_settings_clamps_volume_and_encoder_ranges():
    settings = Settings(
        flac_compression=99,
        rip_audio_bitrate=9999,
        last_volume=150,
    )

    assert settings.flac_compression == 8
    assert settings.rip_audio_bitrate == 1411
    assert settings.last_volume == 100
