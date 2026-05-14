"""CUETools DB audio verification via AccurateRip v1 CRC.

After ripping, each FLAC is decoded back to raw PCM and its AccurateRip v1 CRC
is computed. That CRC is then compared against the per-track CRCs held in the
CUETools DB for the same disc TOC. A match means the rip is provably bit-perfect
against at least one other rip of the same disc.

AccurateRip v1 CRC algorithm:
  - Treat each stereo sample pair as a 32-bit little-endian unsigned integer.
  - Accumulate: crc += sample * (1-based position in track), mod 2**32.
  - Skip the first 2940 samples (5 CD frames) for the first track.
  - Skip the last 2940 samples for the last track.
"""
from __future__ import annotations

import array
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # type: ignore[no-redef]

import requests

CTDB_LOOKUP_URL = "https://db.cuetools.net/lookup2.php"
CTDB_TIMEOUT_SECONDS = 20
_SKIP_SAMPLES = 2940  # 5 CD frames * 588 samples/frame

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


@dataclass
class TrackVerifyResult:
    track_no: int
    verified: bool
    confidence: int = 0
    computed_crc: Optional[int] = None
    # Human-readable outcome for the rip log.
    message: str = ""


def compute_accuraterip_v1_crc(
    flac_path: object,
    ffmpeg: str,
    *,
    is_first_track: bool,
    is_last_track: bool,
) -> Optional[int]:
    """Decode *flac_path* and return its AccurateRip v1 CRC, or None on error."""
    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel", "error",
                "-i", str(flac_path),
                "-f", "s16le",
                "-ar", "44100",
                "-ac", "2",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    data = proc.stdout
    if not data or len(data) % 4 != 0:
        return None

    num_samples = len(data) // 4
    # array.array stores raw C uint32 values (~4 bytes each vs ~28 bytes per int
    # in a Python tuple), cutting peak memory use by ~85% on a 42 MB PCM buffer.
    samples = array.array('I', data)
    if sys.byteorder == 'big':
        samples.byteswap()

    skip_start = _SKIP_SAMPLES if is_first_track else 0
    skip_end = num_samples - _SKIP_SAMPLES if is_last_track and num_samples > _SKIP_SAMPLES else num_samples

    # Accumulate without per-iteration masking to keep the inner loop fast;
    # mask only once at the end.
    crc = sum(samples[i] * (i + 1) for i in range(skip_start, skip_end))
    return crc & 0xFFFFFFFF


def fetch_ctdb_crcs(
    ctdb_toc: str,
    *,
    session: Optional[requests.Session] = None,
    user_agent: str = "LyonMusicManager/1.0",
) -> Optional[dict[int, list[tuple[int, int]]]]:
    """Query CTDB for per-track CRCs for the given disc TOC.

    Returns ``{track_no: [(crc, confidence), ...]}`` where each entry is a
    (CRC, confidence) pair from one submitted rip, or ``None`` on network/parse
    error.  Track numbers are 1-based.
    """
    if not ctdb_toc:
        return None

    http = session or requests.Session()
    try:
        resp = http.get(
            CTDB_LOOKUP_URL,
            params={
                "version": "3",
                "ctdb": "1",
                "metadata": "none",
                "toc": ctdb_toc,
            },
            headers={"User-Agent": user_agent},
            timeout=CTDB_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200 or not resp.content:
            return None
    except requests.RequestException:
        return None

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return None

    result: dict[int, list[tuple[int, int]]] = {}
    for entry in _iter_tag(root, "entry"):
        try:
            confidence = int(entry.get("confidence", "0"))
        except ValueError:
            confidence = 0
        for track_el in _iter_tag(entry, "track"):
            track_id = track_el.get("id") or ""
            crc_str = track_el.get("CRC") or track_el.get("crc") or ""
            if not track_id or not crc_str:
                continue
            try:
                track_no = int(track_id)
                crc_val = int(crc_str, 16)
            except ValueError:
                continue
            result.setdefault(track_no, []).append((crc_val, confidence))

    return result if result else None


def verify_rips(
    ripped_files: dict[int, object],
    ctdb_toc: str,
    ffmpeg: str,
    total_tracks: int,
    *,
    session: Optional[requests.Session] = None,
) -> list[TrackVerifyResult]:
    """Verify ripped FLACs against CTDB CRCs. Returns one result per track.

    *ripped_files* maps 1-based track number to FLAC path.
    """
    if not ripped_files or not ctdb_toc:
        return []

    ctdb_crcs = fetch_ctdb_crcs(ctdb_toc, session=session)
    if ctdb_crcs is None:
        return [
            TrackVerifyResult(
                track_no=n,
                verified=False,
                message="CUETools DB is unreachable; rip accuracy could not be confirmed.",
            )
            for n in sorted(ripped_files)
        ]

    results: list[TrackVerifyResult] = []
    sorted_tracks = sorted(ripped_files)
    for track_no in sorted_tracks:
        flac_path = ripped_files[track_no]
        is_first = track_no == sorted_tracks[0]
        is_last = track_no == sorted_tracks[-1]

        crc = compute_accuraterip_v1_crc(
            flac_path,
            ffmpeg,
            is_first_track=is_first,
            is_last_track=is_last,
        )
        if crc is None:
            results.append(TrackVerifyResult(
                track_no=track_no,
                verified=False,
                message=f"Track {track_no}: could not compute CRC (ffmpeg decode failed).",
            ))
            continue

        track_crcs = ctdb_crcs.get(track_no, [])
        if not track_crcs:
            results.append(TrackVerifyResult(
                track_no=track_no,
                verified=False,
                computed_crc=crc,
                message=f"Track {track_no}: not in CUETools DB (no reference CRC available).",
            ))
            continue

        # Find the best (highest confidence) matching entry.
        match_confidence = next(
            (conf for stored_crc, conf in sorted(track_crcs, key=lambda x: -x[1]) if stored_crc == crc),
            None,
        )
        if match_confidence is not None:
            results.append(TrackVerifyResult(
                track_no=track_no,
                verified=True,
                confidence=match_confidence,
                computed_crc=crc,
                message=f"Track {track_no}: verified OK (confidence {match_confidence}).",
            ))
        else:
            results.append(TrackVerifyResult(
                track_no=track_no,
                verified=False,
                computed_crc=crc,
                message=f"Track {track_no}: CRC mismatch — rip may contain errors.",
            ))

    return results


def _iter_tag(element: ET.Element, tag: str):
    """Yield child elements matching *tag*, ignoring XML namespaces."""
    for child in element:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == tag:
            yield child
