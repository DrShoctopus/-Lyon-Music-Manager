from lyon.core.settings import Settings


def test_settings_migrates_fractional_last_volume():
    assert Settings(last_volume=0.8).last_volume == 80
    assert Settings(last_volume="0.35").last_volume == 35


def test_settings_clamps_percent_last_volume():
    assert Settings(last_volume=250).last_volume == 100
    assert Settings(last_volume=-5).last_volume == 0


def test_settings_preserves_muted_volume():
    assert Settings(last_volume=0).last_volume == 0
