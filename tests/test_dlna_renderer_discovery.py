"""Tests for DLNA renderer discovery."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lyon.core.dlna_renderer_discovery import (
    RendererDevice,
    _el_text,
    _fetch_device,
    _header_value,
    _scan,
)


# ---------------------------------------------------------------------------
# _header_value
# ---------------------------------------------------------------------------

def test_header_value_found():
    response = "HTTP/1.1 200 OK\r\nLOCATION: http://192.168.1.5:49152/description.xml\r\nST: foo\r\n"
    assert _header_value(response, "LOCATION") == "http://192.168.1.5:49152/description.xml"


def test_header_value_case_insensitive():
    response = "location: http://example.com/\r\n"
    assert _header_value(response, "LOCATION") == "http://example.com/"


def test_header_value_missing():
    assert _header_value("HTTP/1.1 200 OK\r\n", "LOCATION") == ""


# ---------------------------------------------------------------------------
# _fetch_device — valid MediaRenderer description
# ---------------------------------------------------------------------------

_RENDERER_XML = b"""<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
    <friendlyName>Living Room TV</friendlyName>
    <UDN>uuid:test-renderer-1234</UDN>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
        <serviceId>urn:upnp-org:serviceId:AVTransport</serviceId>
        <controlURL>/AVTransport/control</controlURL>
        <SCPDURL>/AVTransport/scpd.xml</SCPDURL>
        <eventSubURL>/AVTransport/event</eventSubURL>
      </service>
    </serviceList>
  </device>
</root>
"""


def test_fetch_device_valid():
    location = "http://192.168.1.5:49152/description.xml"
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.content = _RENDERER_XML

    with patch("lyon.core.dlna_renderer_discovery.requests.get", return_value=mock_resp):
        device = _fetch_device(location)

    assert device is not None
    assert device.friendly_name == "Living Room TV"
    assert device.udn == "uuid:test-renderer-1234"
    assert device.location_url == location
    assert device.av_transport_url == "http://192.168.1.5:49152/AVTransport/control"


def test_fetch_device_absolute_control_url():
    xml = _RENDERER_XML.replace(
        b"<controlURL>/AVTransport/control</controlURL>",
        b"<controlURL>http://192.168.1.5:49152/AVTransport/control</controlURL>",
    )
    location = "http://192.168.1.5:49152/description.xml"
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.content = xml

    with patch("lyon.core.dlna_renderer_discovery.requests.get", return_value=mock_resp):
        device = _fetch_device(location)

    assert device is not None
    assert device.av_transport_url == "http://192.168.1.5:49152/AVTransport/control"


def test_fetch_device_no_av_transport():
    xml = b"""<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <friendlyName>Speaker</friendlyName>
    <UDN>uuid:speaker-5678</UDN>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>
        <controlURL>/RC/control</controlURL>
      </service>
    </serviceList>
  </device>
</root>
"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.content = xml

    with patch("lyon.core.dlna_renderer_discovery.requests.get", return_value=mock_resp):
        device = _fetch_device("http://192.168.1.10/desc.xml")

    assert device is None


def test_fetch_device_request_fails():
    with patch("lyon.core.dlna_renderer_discovery.requests.get", side_effect=Exception("timeout")):
        device = _fetch_device("http://192.168.1.99/description.xml")
    assert device is None


def test_fetch_device_missing_friendly_name():
    xml = b"""<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <UDN>uuid:no-name</UDN>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
        <controlURL>/AVTransport/control</controlURL>
      </service>
    </serviceList>
  </device>
</root>
"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.content = xml

    with patch("lyon.core.dlna_renderer_discovery.requests.get", return_value=mock_resp):
        device = _fetch_device("http://192.168.1.1/desc.xml")

    assert device is None


# ---------------------------------------------------------------------------
# _scan — socket-level
# ---------------------------------------------------------------------------

def test_scan_returns_empty_on_socket_error():
    with patch("lyon.core.dlna_renderer_discovery.socket.socket", side_effect=OSError("no socket")):
        devices = _scan(0.1)
    assert devices == []


def test_scan_returns_empty_when_no_responses():
    mock_sock = MagicMock()
    mock_sock.recvfrom.side_effect = TimeoutError
    with patch("lyon.core.dlna_renderer_discovery.socket.socket", return_value=mock_sock):
        devices = _scan(0.01)
    assert devices == []


def test_scan_discovers_renderer():
    ssdp_response = (
        "HTTP/1.1 200 OK\r\n"
        "LOCATION: http://192.168.1.5:49152/description.xml\r\n"
        f"ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n"
        "\r\n"
    ).encode("utf-8")

    call_count = 0

    def fake_recvfrom(_size):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ssdp_response, ("192.168.1.5", 1900)
        raise TimeoutError

    mock_sock = MagicMock()
    mock_sock.recvfrom.side_effect = fake_recvfrom

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.content = _RENDERER_XML

    with (
        patch("lyon.core.dlna_renderer_discovery.socket.socket", return_value=mock_sock),
        patch("lyon.core.dlna_renderer_discovery.requests.get", return_value=mock_resp),
    ):
        devices = _scan(0.01)

    assert len(devices) == 1
    assert devices[0].friendly_name == "Living Room TV"


def test_scan_deduplicates_same_location():
    ssdp_response = (
        "HTTP/1.1 200 OK\r\n"
        "LOCATION: http://192.168.1.5:49152/description.xml\r\n"
        "\r\n"
    ).encode("utf-8")

    call_count = 0

    def fake_recvfrom(_size):
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            return ssdp_response, ("192.168.1.5", 1900)
        raise TimeoutError

    mock_sock = MagicMock()
    mock_sock.recvfrom.side_effect = fake_recvfrom

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.content = _RENDERER_XML

    with (
        patch("lyon.core.dlna_renderer_discovery.socket.socket", return_value=mock_sock),
        patch("lyon.core.dlna_renderer_discovery.requests.get", return_value=mock_resp) as mock_get,
    ):
        devices = _scan(0.01)

    assert len(devices) == 1
    assert mock_get.call_count == 1


# ---------------------------------------------------------------------------
# _el_text
# ---------------------------------------------------------------------------

def test_el_text_none():
    assert _el_text(None) == ""


def test_el_text_empty():
    from defusedxml.ElementTree import fromstring
    el = fromstring("<tag></tag>")
    assert _el_text(el) == ""


def test_el_text_value():
    from defusedxml.ElementTree import fromstring
    el = fromstring("<tag>  hello  </tag>")
    assert _el_text(el) == "hello"
