import importlib.util
import sys
import types


def _install_dependency_stubs() -> None:
    if importlib.util.find_spec("PySide6") is None:
        pyside = types.ModuleType("PySide6")
        qtcore = types.ModuleType("PySide6.QtCore")

        class _Signal:
            def __init__(self, *_, **__):
                pass

            def connect(self, *_):
                pass

            def emit(self, *_):
                pass

        class _QObject:
            def __init__(self, *_, **__):
                pass

            def moveToThread(self, *_):
                pass

        class _QThread:
            started = _Signal()

            def __init__(self, *_, **__):
                pass

            def isRunning(self):
                return False

            def start(self):
                pass

            def quit(self):
                pass

            def wait(self):
                pass

        qtcore.QObject = _QObject
        qtcore.QThread = _QThread
        qtcore.Signal = _Signal
        sys.modules["PySide6"] = pyside
        sys.modules["PySide6.QtCore"] = qtcore

    if importlib.util.find_spec("musicbrainzngs") is None:
        musicbrainzngs = types.ModuleType("musicbrainzngs")
        musicbrainzngs.ResponseError = Exception
        musicbrainzngs.NetworkError = Exception
        sys.modules["musicbrainzngs"] = musicbrainzngs

    if importlib.util.find_spec("requests") is None:
        requests = types.ModuleType("requests")
        requests.RequestException = Exception
        sys.modules["requests"] = requests


_install_dependency_stubs()

from lyon.core.ripper import (  # noqa: E402
    _build_libcdio_track_command,
    _track_sector_span,
)


def test_track_sector_span_normalises_musicbrainz_toc_offsets():
    offsets = (150, 15150, 30150)

    assert _track_sector_span(1, offsets, 45150) == (0, 15000)
    assert _track_sector_span(2, offsets, 45150) == (15000, 30000)
    assert _track_sector_span(3, offsets, 45150) == (30000, 45000)


def test_libcdio_command_extracts_one_audio_stream_with_toc_timing(tmp_path):
    out = tmp_path / "track.flac"

    cmd = _build_libcdio_track_command(
        "ffmpeg",
        "D:",
        out,
        8,
        (15000, 30000),
        input_seek=True,
    )

    assert cmd[cmd.index("-ss") + 1] == "200"
    assert cmd[cmd.index("-t") + 1] == "200"
    assert cmd[cmd.index("-map") + 1] == "0:a:0"
    assert "0:a:1" not in cmd
    assert cmd[-1] == str(out)
