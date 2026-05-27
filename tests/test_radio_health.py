"""Tests for check_station_health."""
from __future__ import annotations

import socket
import urllib.error
from unittest.mock import MagicMock, call, patch

from lyon.core.radio import check_station_health


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status: int) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://radio.example.test/live", code, "Error", {}, None)


# ---------------------------------------------------------------------------
# check_station_health
# ---------------------------------------------------------------------------

def test_healthy_head_returns_true_and_status():
    with patch("urllib.request.urlopen", return_value=_mock_response(200)) as mock_open:
        ok, code = check_station_health("https://radio.example.test/live")

    assert ok is True
    assert code == 200
    # HEAD should be tried first.
    assert mock_open.call_count == 1
    req = mock_open.call_args[0][0]
    assert req.get_method() == "HEAD"


def test_head_405_falls_back_to_get():
    """Servers that reject HEAD should be retried with GET."""
    call_count = 0

    def fake_urlopen(req, timeout=None):
        nonlocal call_count
        call_count += 1
        if req.get_method() == "HEAD":
            raise _http_error(405)
        return _mock_response(200)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        ok, code = check_station_health("https://radio.example.test/live")

    assert ok is True
    assert code == 200
    assert call_count == 2  # HEAD then GET


def test_http_404_returns_false_and_code():
    with patch("urllib.request.urlopen", side_effect=_http_error(404)):
        ok, code = check_station_health("https://radio.example.test/live")

    assert ok is False
    assert code == 404


def test_http_200_is_healthy():
    with patch("urllib.request.urlopen", return_value=_mock_response(200)):
        ok, code = check_station_health("https://radio.example.test/live")
    assert ok is True


def test_http_301_redirect_treated_as_healthy():
    """urlopen follows redirects by default; reaching any 2xx/3xx via urlopen means ok."""
    with patch("urllib.request.urlopen", return_value=_mock_response(200)):
        ok, _ = check_station_health("https://radio.example.test/redirect")
    assert ok is True


def test_connection_error_returns_false_zero():
    with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
        ok, code = check_station_health("https://radio.example.test/live")

    assert ok is False
    assert code == 0


def test_oserror_returns_false_zero():
    with patch("urllib.request.urlopen", side_effect=OSError("network unreachable")):
        ok, code = check_station_health("https://radio.example.test/live")

    assert ok is False
    assert code == 0


def test_non_405_head_error_falls_back_to_get():
    """Stream servers often reject HEAD with codes other than 405."""
    call_count = 0

    def fake_urlopen(req, timeout=None):
        nonlocal call_count
        call_count += 1
        if req.get_method() == "HEAD":
            raise _http_error(403)
        return _mock_response(200)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        ok, code = check_station_health("https://radio.example.test/live")

    assert ok is True
    assert code == 200
    assert call_count == 2


def test_get_failure_after_head_error_returns_false_zero():
    def fake_urlopen(req, timeout=None):
        if req.get_method() == "HEAD":
            raise _http_error(503)
        raise socket.timeout("timed out")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        ok, code = check_station_health("https://radio.example.test/live")

    assert ok is False
    assert code == 0


def test_timeout_parameter_is_forwarded():
    captured: list[float | None] = []

    def fake_urlopen(req, timeout=None):
        captured.append(timeout)
        return _mock_response(200)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        check_station_health("https://radio.example.test/live", timeout=3.0)

    assert captured == [3.0]
