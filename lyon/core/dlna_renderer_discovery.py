"""Discover UPnP MediaRenderer devices on the local network via SSDP."""
from __future__ import annotations

import logging
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from defusedxml.ElementTree import fromstring
from PySide6.QtCore import QThread, Signal

LOG = logging.getLogger(__name__)

_SSDP_ADDR = ("239.255.255.250", 1900)
_RENDERER_ST = "urn:schemas-upnp-org:device:MediaRenderer:1"
_AV_TRANSPORT_TYPE = "urn:schemas-upnp-org:service:AVTransport:1"
_MSEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 3\r\n"
    f"ST: {_RENDERER_ST}\r\n"
    "\r\n"
)


@dataclass(frozen=True)
class RendererDevice:
    friendly_name: str
    location_url: str
    av_transport_url: str
    udn: str


class RendererDiscovery(QThread):
    """Scan the local network for UPnP MediaRenderer devices.

    Usage::

        discovery = RendererDiscovery(timeout=3.0)
        discovery.discovered.connect(my_slot)
        discovery.start()
    """

    discovered = Signal(list)  # list[RendererDevice]

    def __init__(self, timeout: float = 3.0, parent=None):
        super().__init__(parent)
        self._timeout = timeout

    def run(self) -> None:
        devices = _scan(self._timeout, should_stop=self.isInterruptionRequested)
        self.discovered.emit(devices)

    def stop(self) -> None:
        self.requestInterruption()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _scan(
    timeout: float,
    *,
    should_stop: Callable[[], bool] | None = None,
) -> list[RendererDevice]:
    should_stop = should_stop or (lambda: False)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.5)
        sock.bind(("", 0))
    except OSError as exc:
        LOG.warning("Renderer discovery: socket error: %s", exc)
        return []

    try:
        if should_stop():
            return []
        try:
            sock.sendto(_MSEARCH.encode("utf-8"), _SSDP_ADDR)
        except OSError as exc:
            LOG.warning("Renderer discovery: M-SEARCH failed: %s", exc)
            return []

        locations: set[str] = set()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not should_stop():
            try:
                data, _ = sock.recvfrom(4096)
            except TimeoutError:
                continue
            except OSError:
                break
            text = data.decode("utf-8", "ignore")
            location = _header_value(text, "LOCATION")
            if location:
                locations.add(location)
    finally:
        sock.close()

    devices: list[RendererDevice] = []
    for location in locations:
        if should_stop():
            break
        device = _fetch_device(location)
        if device is not None:
            devices.append(device)
    devices.sort(key=lambda d: d.friendly_name.lower())
    return devices


def _fetch_device(location: str) -> RendererDevice | None:
    try:
        resp = requests.get(location, timeout=3.0)
        resp.raise_for_status()
        root = fromstring(resp.content)
    except Exception as exc:
        LOG.debug("Renderer discovery: failed to fetch %s: %s", location, exc)
        return None

    ns = {"d": "urn:schemas-upnp-org:device-1-0"}
    device_el = root.find("d:device", ns)
    if device_el is None:
        return None

    friendly_name = _el_text(device_el.find("d:friendlyName", ns))
    udn = _el_text(device_el.find("d:UDN", ns))
    if not friendly_name or not udn:
        return None

    av_transport_url = ""
    for service in root.findall(".//d:service", ns):
        stype = _el_text(service.find("d:serviceType", ns))
        if stype == _AV_TRANSPORT_TYPE:
            control = _el_text(service.find("d:controlURL", ns))
            if control:
                av_transport_url = urljoin(location, control)
            break

    if not av_transport_url:
        LOG.debug("Renderer discovery: no AVTransport at %s", location)
        return None

    return RendererDevice(
        friendly_name=friendly_name,
        location_url=location,
        av_transport_url=av_transport_url,
        udn=udn,
    )


def _header_value(response: str, name: str) -> str:
    prefix = name.lower() + ":"
    for line in response.splitlines():
        if line.lower().startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _el_text(element) -> str:
    if element is None:
        return ""
    return (element.text or "").strip()
