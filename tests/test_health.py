from lyon.core.health import run_health_checks


def test_health_checks_include_music_folder(tmp_path):
    checks = run_health_checks(str(tmp_path / "Music"))

    assert checks[0].name == "Music folder"
    assert checks[0].ok
