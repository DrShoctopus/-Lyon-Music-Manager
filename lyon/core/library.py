"""SQLite-backed music library."""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Literal

from mutagen import File as MutagenFile
from mutagen.easymp4 import EasyMP4Tags

from .settings import app_data_dir

LOG = logging.getLogger(__name__)

try:
    EasyMP4Tags.RegisterFreeformKey("musicbrainz_discid", "MusicBrainz Disc Id")
except ValueError:
    pass  # already registered

SUPPORTED_AUDIO_EXTS = {
    ".flac",
    ".mp3",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".wav",
    ".aiff",
    ".aif",
    ".wma",
}
SUPPORTED_VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov"}
SUPPORTED_EXTS = SUPPORTED_AUDIO_EXTS | SUPPORTED_VIDEO_EXTS
SUPPORTED_CUE_EXT = ".cue"

DISPLAY_ARTIST_SQL = "COALESCE(NULLIF(album_artist,''), NULLIF(artist,''), 'Unknown Artist')"
DISPLAY_ALBUM_SQL = (
    "CASE WHEN album IS NOT NULL AND album != '' THEN album"
    " WHEN media_type = 'video' THEN 'YouTube Downloads'"
    " ELSE 'Unknown Album' END"
)

# Original table shape at first release (version 0).
# Never add migrated columns here — keep them in _MIGRATIONS so that
# CREATE INDEX cannot outrun ALTER TABLE on existing databases.
_SCHEMA_V0 = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    title TEXT,
    artist TEXT,
    album_artist TEXT,
    album TEXT,
    track_no INTEGER,
    disc_no INTEGER,
    year INTEGER,
    genre TEXT,
    duration REAL,
    bitrate INTEGER,
    samplerate INTEGER,
    added_at REAL DEFAULT (strftime('%s','now')),
    artwork_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(album_artist, artist);
CREATE INDEX IF NOT EXISTS idx_tracks_album  ON tracks(album);
CREATE INDEX IF NOT EXISTS idx_tracks_title  ON tracks(title);
"""

# Versioned migrations applied in order after _SCHEMA_V0.
# Each entry: (target_version, sql).  Always pair an ALTER TABLE with its
# CREATE INDEX in consecutive entries at the same version so they live and
# die together.  Never edit existing entries — only append new ones.
_MIGRATIONS: list[tuple[int, str]] = [
    # v1 — media type (audio / video) classification
    (1, "ALTER TABLE tracks ADD COLUMN media_type TEXT NOT NULL DEFAULT 'audio'"),
    (1, "CREATE INDEX IF NOT EXISTS idx_tracks_media_type ON tracks(media_type)"),
    # v2 — MusicBrainz disc ID for duplicate-CD detection
    (2, "ALTER TABLE tracks ADD COLUMN disc_id TEXT"),
    (2, "CREATE INDEX IF NOT EXISTS idx_tracks_disc_id ON tracks(disc_id)"),
    # v3 — star ratings and play statistics
    (3, "ALTER TABLE tracks ADD COLUMN rating INTEGER NOT NULL DEFAULT 0"),
    (3, "CREATE INDEX IF NOT EXISTS idx_tracks_rating ON tracks(rating)"),
    (3, "ALTER TABLE tracks ADD COLUMN play_count INTEGER NOT NULL DEFAULT 0"),
    (3, "ALTER TABLE tracks ADD COLUMN last_played REAL"),
    # v4 — named playlists (rules=NULL → manual, rules=JSON → smart)
    (4, "CREATE TABLE IF NOT EXISTS playlists (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, created_at REAL NOT NULL DEFAULT (strftime('%s','now')), rules TEXT)"),
    (4, "CREATE TABLE IF NOT EXISTS playlist_tracks (playlist_id INTEGER NOT NULL, track_id INTEGER NOT NULL, position INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (playlist_id, track_id), FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE, FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE)"),
    (4, "CREATE INDEX IF NOT EXISTS idx_pt_playlist ON playlist_tracks(playlist_id, position)"),
    # v5 — user-liked flag (heart toggle)
    (5, "ALTER TABLE tracks ADD COLUMN liked INTEGER NOT NULL DEFAULT 0"),
    (5, "CREATE INDEX IF NOT EXISTS idx_tracks_liked ON tracks(liked)"),
    # v6 — filesystem state for incremental indexing / watched folders
    (6, "ALTER TABLE tracks ADD COLUMN file_size INTEGER NOT NULL DEFAULT 0"),
    (6, "ALTER TABLE tracks ADD COLUMN file_mtime_ns INTEGER NOT NULL DEFAULT 0"),
    (6, "ALTER TABLE tracks ADD COLUMN last_scanned_at REAL"),
    (6, "ALTER TABLE tracks ADD COLUMN scan_error TEXT"),
    # v7 — user-defined grouping tag (set per-rip on the Rip tab, surfaced as
    # the Group column in the Track panel; mapped to ID3 TIT1 / Vorbis
    # GROUPING / MP4 ©grp / ASF WM/ContentGroupDescription on disk)
    (7, "ALTER TABLE tracks ADD COLUMN grouping TEXT NOT NULL DEFAULT ''"),
    (7, "CREATE INDEX IF NOT EXISTS idx_tracks_grouping ON tracks(grouping)"),
    # v8 — fast duplicate detection via MD5 header hash; CUE sheet virtual tracks
    (8, "ALTER TABLE tracks ADD COLUMN file_hash TEXT"),
    (8, "CREATE INDEX IF NOT EXISTS idx_tracks_file_hash ON tracks(file_hash)"),
    (8, "ALTER TABLE tracks ADD COLUMN cue_image_path TEXT"),
    (8, "ALTER TABLE tracks ADD COLUMN cue_offset_sectors INTEGER"),
    # v9 — AcoustID fingerprint result UUID for acoustic duplicate detection
    (9, "ALTER TABLE tracks ADD COLUMN acoustid_id TEXT"),
    (9, "CREATE INDEX IF NOT EXISTS idx_tracks_acoustid_id ON tracks(acoustid_id)"),
    # v10 — per-video resume position in milliseconds
    (10, "ALTER TABLE tracks ADD COLUMN resume_position INTEGER NOT NULL DEFAULT 0"),
]

_PAGE_SIZE = 500  # rows per page in streaming queries


@dataclass
class Track:
    id: int
    path: str
    title: str
    artist: str
    album_artist: str
    album: str
    track_no: int
    disc_no: int
    year: int
    genre: str
    duration: float
    bitrate: int = 0
    samplerate: int = 0
    artwork_path: str | None = None
    media_type: str = "audio"
    rating: int = 0
    play_count: int = 0
    last_played: float | None = None
    liked: bool = False
    disc_id: str | None = None
    file_size: int = 0
    file_mtime_ns: int = 0
    last_scanned_at: float | None = None
    scan_error: str | None = None
    grouping: str = ""
    playback_uri: str | None = None
    playback_is_location: bool = False
    playback_options: tuple[str, ...] = ()
    is_library_item: bool = True
    resume_position: int = 0

    @property
    def display_artist(self) -> str:
        return self.album_artist or self.artist or "Unknown Artist"

    @property
    def display_album(self) -> str:
        return self.album or ("YouTube Downloads" if self.is_video else "Unknown Album")

    @property
    def is_video(self) -> bool:
        return self.media_type == "video"


@dataclass
class Playlist:
    id: int
    name: str
    created_at: float
    rules: str | None = None  # None = manual playlist; JSON string = smart playlist

    @property
    def is_smart(self) -> bool:
        return self.rules is not None


@dataclass(frozen=True)
class IndexResult:
    """Outcome of indexing one filesystem path."""

    status: Literal["added", "updated", "unchanged", "removed", "failed", "skipped"]
    path: str
    error: str = ""


@dataclass
class ScanSummary:
    """Aggregate outcome for an incremental library scan."""

    added: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    removed: int = 0
    failed: int = 0

    def add_result(self, result: IndexResult) -> None:
        if result.status == "added":
            self.added += 1
        elif result.status == "updated":
            self.updated += 1
        elif result.status == "unchanged":
            self.unchanged += 1
        elif result.status == "removed":
            self.removed += 1
        elif result.status == "failed":
            self.failed += 1
        else:
            self.skipped += 1

    def merge(self, other: "ScanSummary") -> None:
        self.added += other.added
        self.updated += other.updated
        self.unchanged += other.unchanged
        self.skipped += other.skipped
        self.removed += other.removed
        self.failed += other.failed


class Library:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (app_data_dir() / "library.db")
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA foreign_keys = ON")
            # WAL improves reader/writer concurrency; NORMAL is the usual
            # durability tradeoff for WAL, and busy_timeout avoids immediate
            # lock failures during scanner/UI contention.
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA synchronous = NORMAL")
            self.conn.execute("PRAGMA busy_timeout = 5000")
            self.conn.executescript(_SCHEMA_V0)
            self._migrate()
            self.conn.commit()

    def _migrate(self) -> None:
        """Apply any _MIGRATIONS not yet stamped in PRAGMA user_version."""
        current = self.conn.execute("PRAGMA user_version").fetchone()[0]
        target = max((v for v, _ in _MIGRATIONS), default=0)
        if current >= target:
            return
        for version, sql in _MIGRATIONS:
            if version <= current:
                continue
            try:
                self.conn.execute(sql)
            except sqlite3.OperationalError as exc:
                if not _is_safe_migration_skip(exc):
                    raise
                # Index/column already exists from a previous partial run.
                LOG.debug("Migration v%d skipped (%s): %s", version, sql[:60], exc)
        # Write outside the per-statement loop so the stamp is atomic with commit().
        self.conn.execute(f"PRAGMA user_version = {target}")

    def commit(self) -> None:
        with self._lock:
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def __enter__(self) -> "Library":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------ scan
    def scan_paths(
        self,
        roots: Iterable[str | os.PathLike],
        should_cancel: "Callable[[], bool] | None" = None,
    ) -> int:
        """Walk the given roots and add new audio/video files. Returns count added.

        ``should_cancel`` is checked inside the directory walk; when it
        returns True the scan commits whatever has been added so far and
        returns early. This lets callers (typically a worker QThread) get
        out cleanly when the user closes the app mid-scan.
        """
        return self.scan_paths_summary(roots, should_cancel=should_cancel).added

    def scan_paths_summary(
        self,
        roots: Iterable[str | os.PathLike],
        should_cancel: "Callable[[], bool] | None" = None,
        *,
        force: bool = False,
    ) -> ScanSummary:
        """Incrementally index supported media under *roots*.

        Existing rows are refreshed only when the on-disk size or mtime has
        changed, which keeps startup reconciliation cheap for large libraries.
        Missing roots are ignored rather than pruned; explicit remove/delete
        flows own library cleanup so disconnected drives are safe.
        """
        summary = ScanSummary()
        for root in roots:
            root = Path(root)
            if not root.exists():
                continue
            for dirpath, _dirs, files in os.walk(root):
                if should_cancel is not None and should_cancel():
                    with self._lock:
                        self.conn.commit()
                    return summary
                for name in files:
                    ext = os.path.splitext(name)[1].lower()
                    if ext in SUPPORTED_EXTS:
                        full = os.path.join(dirpath, name)
                        summary.add_result(self.index_file(full, force=force))
                    elif ext == SUPPORTED_CUE_EXT:
                        full = os.path.join(dirpath, name)
                        summary.merge(self._index_cue_file(full, force=force))
        summary.removed += self.remove_stale_cue_tracks()
        with self._lock:
            self.conn.commit()
        return summary

    def add_file(self, path: str | os.PathLike, disc_id: str | None = None) -> bool:
        return self.index_file(path, disc_id=disc_id).status == "added"

    def index_file(
        self,
        path: str | os.PathLike,
        disc_id: str | None = None,
        *,
        force: bool = False,
    ) -> IndexResult:
        """Add or refresh one supported media file.

        Ratings, liked state, play counts, playlist membership, and other user
        data live outside the updated metadata columns, so they survive tag
        refreshes and watched-folder updates.
        """
        path = str(path)
        ext = Path(path).suffix.lower()
        if ext not in SUPPORTED_EXTS:
            return IndexResult("skipped", path)
        media_type = "video" if ext in SUPPORTED_VIDEO_EXTS else "audio"

        row = self._track_row_for_path(path)
        stat = _safe_stat(path)
        if stat is None:
            if row is not None and disc_id:
                self._backfill_disc_id(path, disc_id)
            return IndexResult("skipped", path, "File does not exist")

        if row is not None and not force and _row_matches_stat(row, stat):
            if disc_id:
                self._backfill_disc_id(path, disc_id)
            elif media_type == "audio" and not _row_disc_id(row):
                meta = _read_tags(path)
                tag_disc_id = meta.get("disc_id") if meta is not None else ""
                if tag_disc_id:
                    self._backfill_disc_id(path, tag_disc_id)
            return IndexResult("unchanged", path)

        meta = _read_tags(path)
        if meta is None:
            if media_type == "video":
                meta = {
                    "title": Path(path).stem,
                    "artist": "", "album_artist": "", "album": "",
                    "track_no": 0, "disc_no": 1, "year": 0, "genre": "",
                    "grouping": "",
                    "duration": 0.0, "bitrate": 0, "samplerate": 0,
                }
            else:
                self._record_scan_error(
                    path,
                    stat,
                    "Unsupported or unreadable audio metadata",
                    existing=row is not None,
                )
                return IndexResult("failed" if row is not None else "skipped", path)

        # Videos without artist metadata (e.g. yt-dlp downloads where mutagen
        # parses the container but no tags are present) fall back to the parent
        # folder name so they group under "YouTube Downloads" rather than the
        # catch-all "Unknown Artist" display.
        if media_type == "video" and not (meta["artist"] or meta["album_artist"]):
            folder_name = Path(path).parent.name or "Videos"
            if not meta["artist"]:
                meta["artist"] = folder_name
            if not meta["album_artist"]:
                meta["album_artist"] = folder_name
            if not meta["album"]:
                meta["album"] = folder_name
        # Look for adjacent cover art.  YouTube video downloads keep their
        # thumbnail as a same-stem sidecar image next to the media file, so
        # prefer that exact match before falling back to album-folder art.
        file_path = Path(path)
        art = _find_video_artwork(file_path) if media_type == "video" else None
        art = art or _find_local_artwork(file_path.parent)
        previous_hash = (
            row["file_hash"]
            if row is not None and "file_hash" in row.keys()
            else None
        )
        file_hash = (
            previous_hash
            if (
                media_type == "audio"
                and previous_hash is not None
                and row is not None
                and _row_matches_stat(row, stat)
            )
            else None
        )
        now = time.time()
        with self._lock:
            values = (
                meta["title"],
                meta["artist"],
                meta["album_artist"],
                meta["album"],
                meta["track_no"],
                meta["disc_no"],
                meta["year"],
                meta["genre"],
                meta.get("grouping", "") or "",
                meta["duration"],
                meta["bitrate"],
                meta["samplerate"],
                str(art) if art else None,
                media_type,
                disc_id or meta.get("disc_id") or (row["disc_id"] if row is not None and "disc_id" in row.keys() else None),
                int(stat.st_size),
                int(stat.st_mtime_ns),
                now,
                None,
                file_hash,
            )
            acoustid_id = (
                row["acoustid_id"]
                if (
                    row is not None
                    and "acoustid_id" in row.keys()
                    and media_type == "audio"
                    and _row_matches_stat(row, stat)
                )
                else None
            )
            if row is None:
                cur = self.conn.execute(
                    """INSERT OR IGNORE INTO tracks
                       (title, artist, album_artist, album, track_no, disc_no,
                        year, genre, grouping, duration, bitrate, samplerate,
                        artwork_path, media_type, disc_id, file_size,
                        file_mtime_ns, last_scanned_at, scan_error, file_hash, path)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (*values, path),
                )
                if cur.rowcount > 0:
                    return IndexResult("added", path)
                # Concurrent insert from another thread; fall through to UPDATE.

            self.conn.execute(
                """UPDATE tracks
                       SET title = ?, artist = ?, album_artist = ?, album = ?,
                           track_no = ?, disc_no = ?, year = ?, genre = ?,
                           grouping = ?, duration = ?, bitrate = ?, samplerate = ?,
                           artwork_path = ?, media_type = ?, disc_id = ?,
                           file_size = ?, file_mtime_ns = ?, last_scanned_at = ?,
                           scan_error = ?, file_hash = ?, acoustid_id = ?
                       WHERE path = ?""",
                (*values, acoustid_id, path),
            )
            return IndexResult("updated", path)

    def _track_row_for_path(self, path: str) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM tracks WHERE path = ?", (path,)
            ).fetchone()

    def _backfill_disc_id(self, path: str, disc_id: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE tracks SET disc_id = ?"
                " WHERE path = ? AND (disc_id IS NULL OR disc_id = '')",
                (disc_id, path),
            )

    def _record_scan_error(
        self,
        path: str,
        stat: os.stat_result,
        error: str,
        *,
        existing: bool,
    ) -> None:
        if not existing:
            return
        with self._lock:
            self.conn.execute(
                """UPDATE tracks
                   SET file_size = ?, file_mtime_ns = ?, last_scanned_at = ?,
                       scan_error = ?
                   WHERE path = ?""",
                (int(stat.st_size), int(stat.st_mtime_ns), time.time(), error, path),
            )

    def _index_cue_file(
        self,
        cue_path_str: str,
        *,
        force: bool = False,
        commit: bool = False,
    ) -> ScanSummary:
        """Parse a CUE sheet and upsert one library row per audio track it describes."""
        from .cue_parser import parse_cue
        summary = ScanSummary()
        cue_path = Path(cue_path_str)

        cue_stat = _safe_stat(cue_path_str)
        if cue_stat is None:
            summary.failed += 1
            return summary

        try:
            cue_sheet = parse_cue(cue_path)
        except Exception as exc:
            LOG.warning("Failed to parse CUE file %s: %s", cue_path, exc)
            summary.failed += 1
            return summary
        if cue_sheet is None:
            return summary  # empty CUE (no TRACK lines), silently skip

        # Bulk-fetch any existing rows for this CUE file to detect additions / removals.
        with self._lock:
            existing: dict[str, sqlite3.Row] = {
                row["path"]: row
                for row in self.conn.execute(
                    "SELECT * FROM tracks WHERE path LIKE ? AND media_type = 'cue_track'",
                    (f"{cue_path_str}::%",),
                ).fetchall()
            }

        # If nothing changed and all tracks are already indexed, skip.
        first_path = f"{cue_path_str}::1"
        if (
            not force
            and first_path in existing
            and len(existing) == len(cue_sheet.tracks)
            and _row_matches_stat(existing[first_path], cue_stat)
        ):
            summary.unchanged += len(cue_sheet.tracks)
            return summary

        art = _find_local_artwork(cue_path.parent)
        now = time.time()
        new_paths: set[str] = set()
        image_duration = _audio_duration_seconds(cue_sheet.image_path)

        with self._lock:
            for track in cue_sheet.tracks:
                track_path = f"{cue_path_str}::{track.number}"
                new_paths.add(track_path)

                if track.end_sectors is not None:
                    duration = (track.end_sectors - track.start_sectors) / 75.0
                elif image_duration is not None:
                    computed = image_duration - (track.start_sectors / 75.0)
                    duration = computed if computed >= 0.5 else 0.0
                else:
                    duration = 0.0  # last track: length unknown without decoding

                values = (
                    track.title or f"Track {track.number}",
                    track.performer or cue_sheet.performer or "",
                    cue_sheet.performer or "",
                    cue_sheet.album or "",
                    track.number,
                    1,
                    0,
                    "",
                    "",
                    duration,
                    0,
                    0,
                    str(art) if art else None,
                    "cue_track",
                    None,
                    int(cue_stat.st_size),
                    int(cue_stat.st_mtime_ns),
                    now,
                    None,
                    None,
                    str(cue_sheet.image_path) if cue_sheet.image_path else None,
                    track.start_sectors,
                )
                if track_path not in existing:
                    self.conn.execute(
                        """INSERT OR IGNORE INTO tracks
                           (title, artist, album_artist, album, track_no, disc_no,
                            year, genre, grouping, duration, bitrate, samplerate,
                            artwork_path, media_type, disc_id, file_size,
                            file_mtime_ns, last_scanned_at, scan_error, file_hash,
                            cue_image_path, cue_offset_sectors, path)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (*values, track_path),
                    )
                    summary.added += 1
                else:
                    self.conn.execute(
                        """UPDATE tracks
                           SET title=?, artist=?, album_artist=?, album=?,
                               track_no=?, disc_no=?, year=?, genre=?,
                               grouping=?, duration=?, bitrate=?, samplerate=?,
                               artwork_path=?, media_type=?, disc_id=?,
                               file_size=?, file_mtime_ns=?, last_scanned_at=?,
                               scan_error=?, file_hash=?,
                               cue_image_path=?, cue_offset_sectors=?
                           WHERE path=?""",
                        (*values, track_path),
                    )
                    summary.updated += 1

            # Remove rows for tracks that no longer appear in the CUE file.
            for orphan_path in existing:
                if orphan_path not in new_paths:
                    self.conn.execute("DELETE FROM tracks WHERE path = ?", (orphan_path,))
                    summary.removed += 1

            if commit:
                self.conn.commit()

        return summary

    def remove_stale_cue_tracks(self) -> int:
        """Remove CUE virtual tracks whose .cue file OR audio image is gone.

        ``remove_missing`` skips ``cue_track`` rows (their paths are synthetic
        ``foo.cue::N`` strings that never exist on disk), so this method is the
        only path that cleans up CUE rows when either side of the pair vanishes.
        """
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, path, cue_image_path FROM tracks "
                "WHERE media_type = 'cue_track'"
            ).fetchall()

        # Cache existence checks per source file to avoid stat()ing the same
        # .cue or image once per virtual track.
        existence: dict[str, bool] = {}

        def _missing(p: str | None) -> bool:
            if not p:
                return False
            cached = existence.get(p)
            if cached is None:
                cached = not Path(p).exists()
                existence[p] = cached
            return cached

        stale_ids: list[int] = []
        for row in rows:
            cue_path = None
            sep = row["path"].rfind("::")
            if sep > 0:
                cue_path = row["path"][:sep]
            if _missing(cue_path) or _missing(row["cue_image_path"]):
                stale_ids.append(row["id"])

        if not stale_ids:
            return 0

        with self._lock:
            self.conn.executemany(
                "DELETE FROM tracks WHERE id = ?", [(i,) for i in stale_ids]
            )
            self.conn.commit()
        return len(stale_ids)

    def remove_path(self, path: str | os.PathLike, *, commit: bool = True) -> int:
        """Remove a library record for *path* without touching the filesystem."""
        with self._lock:
            cur = self.conn.execute("DELETE FROM tracks WHERE path = ?", (str(path),))
            if commit:
                self.conn.commit()
            return cur.rowcount

    def remove_paths_under(self, folder: str | os.PathLike, *, commit: bool = True) -> int:
        """Remove library records under a deleted watched folder."""
        folder_text = str(folder).rstrip("/\\")
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM tracks WHERE path = ? OR path LIKE ?",
                (folder_text, folder_text + os.sep + "%"),
            )
            if commit:
                self.conn.commit()
            return cur.rowcount

    def move_path(
        self,
        old_path: str | os.PathLike,
        new_path: str | os.PathLike,
        *,
        commit: bool = True,
    ) -> IndexResult:
        """Move a library record to *new_path*, preserving user metadata."""
        old_text = str(old_path)
        new_text = str(new_path)
        if old_text == new_text:
            return IndexResult("unchanged", new_text)
        with self._lock:
            old_row = self.conn.execute(
                "SELECT id FROM tracks WHERE path = ?", (old_text,)
            ).fetchone()
            if old_row is None:
                return self.index_file(new_text)
            existing_dest = self.conn.execute(
                "SELECT id FROM tracks WHERE path = ?", (new_text,)
            ).fetchone()
            if existing_dest is not None and existing_dest["id"] != old_row["id"]:
                self.conn.execute("DELETE FROM tracks WHERE id = ?", (old_row["id"],))
                if commit:
                    self.conn.commit()
                return IndexResult("removed", old_text)
            self.conn.execute(
                "UPDATE tracks SET path = ?, file_size = 0, file_mtime_ns = 0 WHERE id = ?",
                (new_text, old_row["id"]),
            )
        result = self.index_file(new_text)
        if commit:
            self.commit()
        return result

    def move_paths_under(
        self,
        old_folder: str | os.PathLike,
        new_folder: str | os.PathLike,
        *,
        commit: bool = True,
        should_cancel: "Callable[[], bool] | None" = None,
    ) -> ScanSummary:
        """Move all library records under one folder to another folder.

        This preserves track IDs and dependent user data such as playlist rows,
        ratings, play counts, and liked state across album/folder renames.
        """
        old_root = Path(old_folder)
        new_root = Path(new_folder)
        old_text = str(old_root).rstrip("/\\")
        summary = ScanSummary()
        refresh_paths: list[Path] = []
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, path FROM tracks WHERE path = ? OR path LIKE ?",
                (old_text, old_text + os.sep + "%"),
            ).fetchall()
            for row in rows:
                old_path = Path(row["path"])
                try:
                    rel = old_path.relative_to(old_root)
                except ValueError:
                    rel = Path(old_path.name)
                new_path = str(new_root / rel)
                existing_dest = self.conn.execute(
                    "SELECT id FROM tracks WHERE path = ?", (new_path,)
                ).fetchone()
                if existing_dest is not None and existing_dest["id"] != row["id"]:
                    self.conn.execute("DELETE FROM tracks WHERE id = ?", (row["id"],))
                    summary.removed += 1
                    continue
                self.conn.execute(
                    "UPDATE tracks SET path = ?, file_size = 0, file_mtime_ns = 0 WHERE id = ?",
                    (new_path, row["id"]),
                )
                refresh_paths.append(Path(new_path))

        for new_path in refresh_paths:
            if should_cancel is not None and should_cancel():
                break
            if new_path.exists():
                result = self.index_file(new_path)
                if result.status == "updated":
                    summary.updated += 1
                elif result.status == "added":
                    # Should be rare because the row was rewritten above, but
                    # count it accurately if an older DB inconsistency appears.
                    summary.added += 1
                elif result.status == "unchanged":
                    summary.unchanged += 1
                elif result.status == "failed":
                    summary.failed += 1
                else:
                    summary.skipped += 1
            else:
                summary.removed += self.remove_path(new_path, commit=False)
        if new_root.exists() and (should_cancel is None or not should_cancel()):
            summary.merge(
                self.scan_paths_summary([new_root], should_cancel=should_cancel)
            )
        if commit:
            self.commit()
        return summary

    # ------------------------------------------------------------------ queries
    def all_artists(self, media_type: str | None = None, genre: str | None = None) -> list[str]:
        conditions: list[str] = ["1=1"]
        params: list = []
        if media_type is not None:
            conditions.append("media_type = ?")
            params.append(media_type)
        if genre is not None:
            conditions.append("genre = ?")
            params.append(genre)
        where = " AND ".join(conditions)
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT DISTINCT {DISPLAY_ARTIST_SQL} AS a
                    FROM tracks WHERE {where}
                    ORDER BY a COLLATE NOCASE""",
                params,
            ).fetchall()
        return [r["a"] for r in rows]

    def albums_for_artist(
        self, artist: str, media_type: str | None = None
    ) -> list[tuple[str, str | None]]:
        filter_sql = "" if media_type is None else "AND media_type = ?"
        params = (artist, media_type) if media_type is not None else (artist,)
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT {DISPLAY_ALBUM_SQL} AS display_album, MAX(artwork_path) AS art
                    FROM tracks
                    WHERE {DISPLAY_ARTIST_SQL} = ? {filter_sql}
                    GROUP BY display_album
                    ORDER BY MIN(year), display_album COLLATE NOCASE""",
                params,
            ).fetchall()
        return [(r["display_album"], r["art"]) for r in rows]

    def all_albums(self, media_type: str | None = None) -> list[tuple[str, str, str | None]]:
        filter_sql = "" if media_type is None else "WHERE media_type = ?"
        params: tuple = () if media_type is None else (media_type,)
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT {DISPLAY_ARTIST_SQL} AS a,
                           {DISPLAY_ALBUM_SQL} AS display_album, MAX(artwork_path) AS art
                    FROM tracks {filter_sql}
                    GROUP BY a, display_album
                    ORDER BY a COLLATE NOCASE, display_album COLLATE NOCASE""",
                params,
            ).fetchall()
        return [(r["a"], r["display_album"], r["art"]) for r in rows]

    def tracks_for_album(
        self, artist: str, album: str, media_type: str | None = None
    ) -> list[Track]:
        filter_sql = "" if media_type is None else "AND media_type = ?"
        params = (artist, album, media_type) if media_type is not None else (artist, album)
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT * FROM tracks
                    WHERE {DISPLAY_ARTIST_SQL} = ? AND {DISPLAY_ALBUM_SQL} = ? {filter_sql}
                    ORDER BY disc_no, track_no, title COLLATE NOCASE""",
                params,
            ).fetchall()
        return [_row_to_track(r) for r in rows]

    def tracks_for_artist(
        self, artist: str, media_type: str | None = None
    ) -> list[Track]:
        """Return all tracks for one display artist in album/track order."""
        filter_sql = "" if media_type is None else "AND media_type = ?"
        params = (artist, media_type) if media_type is not None else (artist,)
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT * FROM tracks
                    WHERE {DISPLAY_ARTIST_SQL} = ? {filter_sql}
                    ORDER BY {DISPLAY_ALBUM_SQL} COLLATE NOCASE, disc_no, track_no,
                             title COLLATE NOCASE""",
                params,
            ).fetchall()
        return [_row_to_track(r) for r in rows]

    def search(self, query: str, media_type: str | None = None) -> list[Track]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        filter_sql = "" if media_type is None else "AND media_type = ?"
        base_params = (like, like, like, like, like, like)
        params = base_params + (media_type,) if media_type is not None else base_params
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT * FROM tracks
                   WHERE (title LIKE ? ESCAPE '\\'
                      OR artist LIKE ? ESCAPE '\\'
                      OR album_artist LIKE ? ESCAPE '\\'
                      OR album LIKE ? ESCAPE '\\'
                      OR {DISPLAY_ARTIST_SQL} LIKE ? ESCAPE '\\'
                      OR {DISPLAY_ALBUM_SQL} LIKE ? ESCAPE '\\')
                   {filter_sql}
                   ORDER BY {DISPLAY_ARTIST_SQL}, {DISPLAY_ALBUM_SQL}, disc_no, track_no
                   LIMIT 500""",
                params,
            ).fetchall()
        return [_row_to_track(r) for r in rows]

    def all_tracks(self, media_type: str | None = None) -> Iterator[Track]:
        """Return a consistent snapshot of every track in id order."""
        filter_sql = "" if media_type is None else "AND media_type = ?"
        params = () if media_type is None else (media_type,)
        with self._lock:
            rows = self.conn.execute(
                f"SELECT * FROM tracks WHERE id > 0 {filter_sql} ORDER BY id",
                params,
            ).fetchall()
        return iter(_row_to_track(r) for r in rows)

    def count_tracks(self, media_type: str | None = None) -> int:
        """Return the number of tracks, optionally restricted by media type."""
        filter_sql = "" if media_type is None else "WHERE media_type = ?"
        params = () if media_type is None else (media_type,)
        with self._lock:
            row = self.conn.execute(
                f"SELECT COUNT(*) FROM tracks {filter_sql}",
                params,
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def track_by_id(self, track_id: int) -> Track | None:
        """Return one track by database id, or None when it is not indexed."""
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM tracks WHERE id = ?", (int(track_id),)
            ).fetchone()
        return _row_to_track(row) if row is not None else None

    def has_disc(self, disc_id: str, min_tracks: int = 1) -> bool:
        """Return True if at least *min_tracks* library tracks carry this disc ID."""
        if not disc_id:
            return False
        min_tracks = max(1, min_tracks)  # never let a 0-track TOC false-positive
        with self._lock:
            count = self.conn.execute(
                "SELECT COUNT(*) FROM tracks WHERE disc_id = ?", (disc_id,)
            ).fetchone()[0]
        return count >= min_tracks

    def album_for_disc(self, disc_id: str) -> tuple[str, str] | None:
        """Return (display_artist, album) for the first track carrying this disc ID, or None."""
        with self._lock:
            row = self.conn.execute(
                f"SELECT {DISPLAY_ARTIST_SQL} AS a, {DISPLAY_ALBUM_SQL} AS b"
                " FROM tracks WHERE disc_id = ? LIMIT 1",
                (disc_id,),
            ).fetchone()
        return (row["a"], row["b"]) if row else None

    def find_album_match(
        self,
        artist: str,
        album: str,
        track_count: int,
    ) -> tuple[str, str] | None:
        """Return (display_artist, display_album) if the library already has an
        album whose artist, album name, and track count all match the given
        values.  Comparison is case-insensitive.  Returns None when no match is
        found.
        """
        if not artist or not album or track_count < 1:
            return None
        with self._lock:
            row = self.conn.execute(
                f"""SELECT {DISPLAY_ARTIST_SQL} AS a,
                           {DISPLAY_ALBUM_SQL}  AS b,
                           COUNT(*)             AS cnt
                    FROM tracks
                    WHERE media_type = 'audio'
                    GROUP BY a, b
                    HAVING a = ? COLLATE NOCASE
                       AND b = ? COLLATE NOCASE
                       AND cnt = ?
                    LIMIT 1""",
                (artist, album, track_count),
            ).fetchone()
        return (row["a"], row["b"]) if row else None

    def library_stats(self) -> dict:
        """Return aggregate statistics for the entire library."""
        with self._lock:
            row = self.conn.execute(
                f"""SELECT
                        COUNT(DISTINCT {DISPLAY_ARTIST_SQL}) AS artist_count,
                        COUNT(*) AS track_count,
                        COALESCE(SUM(duration), 0) AS total_duration,
                        COALESCE(SUM(file_size), 0) AS total_file_size
                    FROM tracks""",
            ).fetchone()
            album_count = self.conn.execute(
                f"""SELECT COUNT(*) FROM
                        (SELECT DISTINCT {DISPLAY_ARTIST_SQL}, {DISPLAY_ALBUM_SQL} FROM tracks)""",
            ).fetchone()[0]
        return {
            "artist_count": int(row["artist_count"]),
            "album_count": int(album_count),
            "track_count": int(row["track_count"]),
            "total_duration": float(row["total_duration"]),
            "total_file_size": int(row["total_file_size"]),
        }

    def update_track(self, track_id: int, fields: dict) -> None:
        allowed = {"title", "artist", "album_artist", "album", "track_no", "disc_no", "year", "genre", "grouping", "artwork_path"}
        safe = {k: v for k, v in fields.items() if k in allowed}
        if not safe:
            return
        set_clause = ", ".join(f"{k} = ?" for k in safe)
        with self._lock:
            self.conn.execute(
                f"UPDATE tracks SET {set_clause} WHERE id = ?",
                [*safe.values(), track_id],
            )
            self.conn.commit()

    def update_liked(self, track_id: int, liked: bool) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE tracks SET liked = ? WHERE id = ?", (int(liked), track_id)
            )
            self.conn.commit()

    def update_rating(self, track_id: int, rating: int) -> None:
        rating = max(0, min(5, int(rating)))
        with self._lock:
            self.conn.execute(
                "UPDATE tracks SET rating = ? WHERE id = ?", (rating, track_id)
            )
            self.conn.commit()

    def increment_play_count(self, track_id: int) -> None:
        now = time.time()
        with self._lock:
            self.conn.execute(
                "UPDATE tracks SET play_count = play_count + 1, last_played = ? WHERE id = ?",
                (now, track_id),
            )
            self.conn.commit()

    def update_resume_position(self, track_id: int, position_ms: int) -> None:
        """Store the last playback position for a video track."""
        position_ms = max(0, int(position_ms or 0))
        with self._lock:
            self.conn.execute(
                "UPDATE tracks SET resume_position = ? WHERE id = ? AND media_type = 'video'",
                (position_ms, track_id),
            )
            self.conn.commit()

    # ------------------------------------------------------------------ genre queries
    def all_genres(self, media_type: str | None = None) -> list[str]:
        filter_sql = "" if media_type is None else "AND media_type = ?"
        params: tuple = () if media_type is None else (media_type,)
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT DISTINCT genre AS g FROM tracks
                    WHERE genre IS NOT NULL AND genre != '' {filter_sql}
                    ORDER BY genre COLLATE NOCASE""",
                params,
            ).fetchall()
        return [r["g"] for r in rows]

    def media_counts_by_artist(self, media_type: str | None = None) -> list[tuple[str, int]]:
        """Return (display_artist, track_count) pairs, artist-sorted, via SQL GROUP BY."""
        filter_sql = "" if media_type is None else "WHERE media_type = ?"
        params: tuple = () if media_type is None else (media_type,)
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT {DISPLAY_ARTIST_SQL} AS a, COUNT(*) AS n
                    FROM tracks {filter_sql}
                    GROUP BY a
                    ORDER BY a COLLATE NOCASE""",
                params,
            ).fetchall()
        return [(r["a"], int(r["n"])) for r in rows]

    def media_counts_by_album(self, media_type: str | None = None) -> list[tuple[str, str, int]]:
        """Return (display_artist, display_album, track_count) triples, sorted."""
        filter_sql = "" if media_type is None else "WHERE media_type = ?"
        params: tuple = () if media_type is None else (media_type,)
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT {DISPLAY_ARTIST_SQL} AS a, {DISPLAY_ALBUM_SQL} AS b, COUNT(*) AS n
                    FROM tracks {filter_sql}
                    GROUP BY a, b
                    ORDER BY a COLLATE NOCASE, b COLLATE NOCASE""",
                params,
            ).fetchall()
        return [(r["a"], r["b"], int(r["n"])) for r in rows]

    def media_counts_by_genre(self, media_type: str | None = None) -> list[tuple[str, int]]:
        """Return (genre, track_count) pairs for non-empty genres, sorted."""
        filter_sql = "" if media_type is None else "AND media_type = ?"
        params: tuple = () if media_type is None else (media_type,)
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT genre AS g, COUNT(*) AS n
                    FROM tracks
                    WHERE genre IS NOT NULL AND genre != '' {filter_sql}
                    GROUP BY g
                    ORDER BY g COLLATE NOCASE""",
                params,
            ).fetchall()
        return [(r["g"], int(r["n"])) for r in rows]

    def tracks_for_genre(self, genre: str, media_type: str | None = None) -> list[Track]:
        filter_sql = "" if media_type is None else "AND media_type = ?"
        params: tuple = (genre, media_type) if media_type is not None else (genre,)
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT * FROM tracks WHERE genre = ? {filter_sql}
                    ORDER BY {DISPLAY_ARTIST_SQL}, {DISPLAY_ALBUM_SQL}, disc_no, track_no""",
                params,
            ).fetchall()
        return [_row_to_track(r) for r in rows]

    # ------------------------------------------------------------------ virtual collections
    def liked(self, media_type: str | None = None) -> list[Track]:
        filter_sql = "" if media_type is None else "AND media_type = ?"
        params: tuple = (media_type,) if media_type is not None else ()
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT * FROM tracks WHERE liked = 1 {filter_sql}
                    ORDER BY {DISPLAY_ARTIST_SQL}, {DISPLAY_ALBUM_SQL}, disc_no, track_no""",
                params,
            ).fetchall()
        return [_row_to_track(r) for r in rows]

    def recently_added(self, limit: int = 50, media_type: str | None = None) -> list[Track]:
        filter_sql = "" if media_type is None else "AND media_type = ?"
        params: tuple = (media_type, limit) if media_type is not None else (limit,)
        with self._lock:
            rows = self.conn.execute(
                f"SELECT * FROM tracks WHERE 1=1 {filter_sql} ORDER BY added_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [_row_to_track(r) for r in rows]

    def recently_played(self, limit: int = 50, media_type: str | None = None) -> list[Track]:
        filter_sql = "" if media_type is None else "AND media_type = ?"
        params: tuple = (media_type, limit) if media_type is not None else (limit,)
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT * FROM tracks WHERE last_played IS NOT NULL {filter_sql}
                    ORDER BY last_played DESC LIMIT ?""",
                params,
            ).fetchall()
        return [_row_to_track(r) for r in rows]

    def most_played(self, limit: int = 50, media_type: str | None = None) -> list[Track]:
        filter_sql = "" if media_type is None else "AND media_type = ?"
        params: tuple = (media_type, limit) if media_type is not None else (limit,)
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT * FROM tracks WHERE play_count > 0 {filter_sql}
                    ORDER BY play_count DESC LIMIT ?""",
                params,
            ).fetchall()
        return [_row_to_track(r) for r in rows]

    def top_rated(self, min_rating: int = 4, limit: int = 100, media_type: str | None = None) -> list[Track]:
        filter_sql = "" if media_type is None else "AND media_type = ?"
        params: tuple = (min_rating, media_type, limit) if media_type is not None else (min_rating, limit)
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT * FROM tracks WHERE rating >= ? {filter_sql}
                    ORDER BY rating DESC, {DISPLAY_ARTIST_SQL}, {DISPLAY_ALBUM_SQL}
                    LIMIT ?""",
                params,
            ).fetchall()
        return [_row_to_track(r) for r in rows]

    def find_duplicates(self) -> list[list[Track]]:
        """Return groups of tracks sharing the same display_artist + normalised title."""
        with self._lock:
            rows = self.conn.execute(
                f"""WITH dupe_keys AS (
                        SELECT {DISPLAY_ARTIST_SQL} AS display_artist,
                               LOWER(TRIM(title)) AS norm_title
                        FROM tracks
                        WHERE title IS NOT NULL AND TRIM(title) != ''
                        GROUP BY display_artist, norm_title
                        HAVING COUNT(*) > 1
                    )
                    SELECT tracks.*,
                           {DISPLAY_ARTIST_SQL} AS display_artist,
                           LOWER(TRIM(tracks.title)) AS norm_title
                    FROM tracks
                    JOIN dupe_keys
                      ON dupe_keys.display_artist = {DISPLAY_ARTIST_SQL}
                     AND dupe_keys.norm_title = LOWER(TRIM(tracks.title))
                    ORDER BY dupe_keys.display_artist COLLATE NOCASE,
                             dupe_keys.norm_title COLLATE NOCASE,
                             tracks.bitrate DESC,
                             tracks.samplerate DESC,
                             tracks.duration DESC"""
            ).fetchall()
        groups: list[list[Track]] = []
        current_key: tuple[str, str] | None = None
        current_group: list[Track] = []
        for row in rows:
            key = (row["display_artist"], row["norm_title"])
            if current_key is not None and key != current_key:
                groups.append(current_group)
                current_group = []
            current_key = key
            current_group.append(_row_to_track(row))
        if current_group:
            groups.append(current_group)
        return groups

    def find_duplicates_by_hash(self) -> list[list[Track]]:
        """Return groups of audio tracks sharing an identical MD5 header hash."""
        self._backfill_missing_hashes()
        with self._lock:
            rows = self.conn.execute(
                """WITH dupe_keys AS (
                       SELECT file_hash FROM tracks
                       WHERE file_hash IS NOT NULL AND media_type = 'audio'
                       GROUP BY file_hash HAVING COUNT(*) > 1
                   )
                   SELECT tracks.*
                   FROM tracks
                   JOIN dupe_keys ON dupe_keys.file_hash = tracks.file_hash
                   ORDER BY tracks.file_hash,
                            tracks.bitrate DESC,
                            tracks.samplerate DESC,
                            tracks.duration DESC"""
            ).fetchall()
        groups: list[list[Track]] = []
        current_hash: str | None = None
        current_group: list[Track] = []
        for row in rows:
            h = row["file_hash"]
            if current_hash is not None and h != current_hash:
                groups.append(current_group)
                current_group = []
            current_hash = h
            current_group.append(_row_to_track(row))
        if current_group:
            groups.append(current_group)
        return groups

    def _backfill_missing_hashes(self) -> None:
        """Populate missing audio file hashes before exact duplicate lookup."""
        with self._lock:
            rows = self.conn.execute(
                """SELECT id, path FROM tracks
                   WHERE media_type = 'audio'
                     AND (file_hash IS NULL OR file_hash = '')"""
            ).fetchall()
        if not rows:
            return

        updates: list[tuple[str, int]] = []
        for row in rows:
            file_hash = _compute_file_hash(row["path"])
            if file_hash:
                updates.append((file_hash, int(row["id"])))

        if updates:
            with self._lock:
                self.conn.executemany(
                    "UPDATE tracks SET file_hash = ? WHERE id = ? AND (file_hash IS NULL OR file_hash = '')",
                    updates,
                )
                self.conn.commit()

    def find_duplicates_by_fingerprint(self) -> list[list[Track]]:
        """Return groups of audio tracks sharing the same AcoustID UUID."""
        with self._lock:
            rows = self.conn.execute(
                """WITH dupe_keys AS (
                       SELECT acoustid_id FROM tracks
                       WHERE acoustid_id IS NOT NULL AND acoustid_id != ''
                         AND media_type = 'audio'
                       GROUP BY acoustid_id HAVING COUNT(*) > 1
                   )
                   SELECT tracks.*
                   FROM tracks
                   JOIN dupe_keys ON dupe_keys.acoustid_id = tracks.acoustid_id
                   ORDER BY tracks.acoustid_id,
                            tracks.bitrate DESC,
                            tracks.samplerate DESC,
                            tracks.duration DESC"""
            ).fetchall()
        groups: list[list[Track]] = []
        current_id: str | None = None
        current_group: list[Track] = []
        for row in rows:
            aid = row["acoustid_id"]
            if current_id is not None and aid != current_id:
                groups.append(current_group)
                current_group = []
            current_id = aid
            current_group.append(_row_to_track(row))
        if current_group:
            groups.append(current_group)
        return groups

    def update_acoustid(self, track_id: int, acoustid_id: str) -> None:
        """Store an AcoustID UUID on a track row."""
        with self._lock:
            self.conn.execute(
                "UPDATE tracks SET acoustid_id = ? WHERE id = ?",
                (acoustid_id or None, track_id),
            )
            self.conn.commit()

    def tracks_without_acoustid(self) -> list[Track]:
        """Return audio tracks that have no acoustid_id stored yet."""
        return list(self.iter_tracks_without_acoustid())

    def count_tracks_without_acoustid(self) -> int:
        """Return the number of audio tracks missing an AcoustID UUID."""
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM tracks WHERE media_type = 'audio' "
                "AND (acoustid_id IS NULL OR acoustid_id = '')"
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def iter_tracks_without_acoustid(self, batch_size: int = _PAGE_SIZE) -> Iterator[Track]:
        """Yield audio tracks missing an AcoustID UUID in bounded pages."""
        batch_size = max(1, int(batch_size))
        offset = 0
        while True:
            with self._lock:
                rows = self.conn.execute(
                    "SELECT * FROM tracks WHERE media_type = 'audio' "
                    "AND (acoustid_id IS NULL OR acoustid_id = '') "
                    "ORDER BY artist COLLATE NOCASE, album COLLATE NOCASE, track_no "
                    "LIMIT ? OFFSET ?",
                    (batch_size, offset),
                ).fetchall()
            if not rows:
                break
            for row in rows:
                yield _row_to_track(row)
            offset += len(rows)
            if len(rows) < batch_size:
                break

    # ------------------------------------------------------------------ playlist CRUD
    def all_playlists(self) -> list[Playlist]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, name, created_at, rules FROM playlists ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [
            Playlist(id=r["id"], name=r["name"], created_at=r["created_at"] or 0.0, rules=r["rules"])
            for r in rows
        ]

    def smart_playlist_tracks(self, rules_json: str) -> list[Track]:
        from .smart_playlist import spec_from_json, spec_order_and_limit, spec_to_where
        spec = spec_from_json(rules_json)
        where, params = spec_to_where(spec)
        order, limit, limit_params = spec_order_and_limit(spec)
        query = (
            f"SELECT * FROM tracks "
            f"WHERE media_type = 'audio' AND ({where}) "
            f"ORDER BY {order}"
            + (f" {limit}" if limit else "")
        )
        with self._lock:
            rows = self.conn.execute(query, [*params, *limit_params]).fetchall()
        return [_row_to_track(r) for r in rows]

    def create_smart_playlist(self, name: str, rules_json: str) -> int:
        now = time.time()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO playlists (name, created_at, rules) VALUES (?, ?, ?)",
                (name.strip(), now, rules_json),
            )
            self.conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    def update_playlist_rules(self, playlist_id: int, rules_json: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE playlists SET rules = ? WHERE id = ?", (rules_json, playlist_id)
            )
            self.conn.commit()

    def create_playlist(self, name: str) -> int:
        now = time.time()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO playlists (name, created_at) VALUES (?, ?)", (name.strip(), now)
            )
            self.conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    def rename_playlist(self, playlist_id: int, name: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE playlists SET name = ? WHERE id = ?", (name.strip(), playlist_id)
            )
            self.conn.commit()

    def delete_playlist(self, playlist_id: int) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
            self.conn.commit()

    def playlist_tracks(self, playlist_id: int) -> list[Track]:
        with self._lock:
            rows = self.conn.execute(
                """SELECT t.* FROM tracks t
                   JOIN playlist_tracks pt ON pt.track_id = t.id
                   WHERE pt.playlist_id = ?
                   ORDER BY pt.position, pt.rowid""",
                (playlist_id,),
            ).fetchall()
        return [_row_to_track(r) for r in rows]

    def add_to_playlist(self, playlist_id: int, track_ids: list[int]) -> None:
        with self._lock:
            row = self.conn.execute(
                "SELECT COALESCE(MAX(position), -1) FROM playlist_tracks WHERE playlist_id = ?",
                (playlist_id,),
            ).fetchone()
            pos = (row[0] + 1) if row else 0
            for tid in track_ids:
                self.conn.execute(
                    "INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",
                    (playlist_id, tid, pos),
                )
                pos += 1
            self.conn.commit()

    def remove_from_playlist(self, playlist_id: int, track_id: int) -> None:
        with self._lock:
            self.conn.execute(
                "DELETE FROM playlist_tracks WHERE playlist_id = ? AND track_id = ?",
                (playlist_id, track_id),
            )
            self.conn.commit()

    def reorder_playlist(self, playlist_id: int, ordered_track_ids: list[int]) -> None:
        with self._lock:
            for pos, tid in enumerate(ordered_track_ids):
                self.conn.execute(
                    "UPDATE playlist_tracks SET position = ? WHERE playlist_id = ? AND track_id = ?",
                    (pos, playlist_id, tid),
                )
            self.conn.commit()

    def delete_track(self, track_id: int) -> None:
        """Remove a single track record from the library (does not delete the file)."""
        with self._lock:
            self.conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
            self.conn.commit()

    def tracks_for_paths(self, paths: list[str]) -> list[Track]:
        """Return Track objects for the given file paths, preserving order, skipping unknowns."""
        if not paths:
            return []
        placeholders = ",".join("?" * len(paths))
        with self._lock:
            rows = self.conn.execute(
                f"SELECT * FROM tracks WHERE path IN ({placeholders})", paths
            ).fetchall()
        path_to_track = {r["path"]: _row_to_track(r) for r in rows}
        return [path_to_track[p] for p in paths if p in path_to_track]

    def remove_missing(self) -> int:
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, path FROM tracks WHERE media_type != 'cue_track'"
            ).fetchall()
        # Path existence checks run outside the lock to avoid blocking queries.
        missing_ids = [r["id"] for r in rows if not Path(r["path"]).exists()]
        if not missing_ids:
            return 0
        with self._lock:
            self.conn.executemany(
                "DELETE FROM tracks WHERE id = ?", [(id_,) for id_ in missing_ids]
            )
            self.conn.commit()
        return len(missing_ids)

    def remove_missing_under_existing_roots(self, roots: Iterable[str | os.PathLike]) -> int:
        """Remove missing rows only for library roots that are currently reachable."""
        existing_roots: list[str] = []
        for root in roots:
            try:
                root_path = Path(root)
                if root_path.exists():
                    existing_roots.append(os.path.normcase(os.path.abspath(root_path)))
            except OSError:
                continue
        if not existing_roots:
            return 0

        with self._lock:
            rows = self.conn.execute(
                "SELECT id, path FROM tracks WHERE media_type != 'cue_track'"
            ).fetchall()

        missing_ids: list[int] = []
        for row in rows:
            path = row["path"]
            if Path(path).exists():
                continue
            try:
                path_norm = os.path.normcase(os.path.abspath(path))
                if any(os.path.commonpath([root, path_norm]) == root for root in existing_roots):
                    missing_ids.append(row["id"])
            except (OSError, ValueError):
                continue

        if not missing_ids:
            return 0
        with self._lock:
            self.conn.executemany(
                "DELETE FROM tracks WHERE id = ?", [(id_,) for id_ in missing_ids]
            )
            self.conn.commit()
        return len(missing_ids)


def _row_to_track(r: sqlite3.Row) -> Track:
    keys = r.keys()
    media_type = r["media_type"] if r["media_type"] else "audio"

    # CUE virtual tracks route playback through the parent image file.
    playback_uri: str | None = None
    playback_options: tuple[str, ...] = ()
    if media_type == "cue_track" and "cue_image_path" in keys and r["cue_image_path"]:
        start_s = (r["cue_offset_sectors"] or 0) / 75.0
        dur = r["duration"] or 0.0
        playback_uri = r["cue_image_path"]
        # libVLC media options use the ":opt=value" form (the "--opt=value" form
        # is for vlc.Instance() flags and is silently ignored by media.add_option).
        playback_options = (f":start-time={start_s:.3f}",)
        if dur > 0:
            playback_options = (*playback_options, f":stop-time={start_s + dur:.3f}")

    return Track(
        id=r["id"],
        path=r["path"],
        title=r["title"] or Path(r["path"]).stem,
        artist=r["artist"] or "",
        album_artist=r["album_artist"] or "",
        album=r["album"] or "",
        track_no=r["track_no"] or 0,
        disc_no=r["disc_no"] or 0,
        year=r["year"] or 0,
        genre=r["genre"] or "",
        duration=r["duration"] or 0.0,
        bitrate=r["bitrate"] or 0,
        samplerate=r["samplerate"] or 0,
        artwork_path=r["artwork_path"],
        media_type=media_type,
        rating=int(r["rating"] or 0) if "rating" in keys else 0,
        play_count=int(r["play_count"] or 0) if "play_count" in keys else 0,
        last_played=r["last_played"] if "last_played" in keys else None,
        liked=bool(r["liked"]) if "liked" in keys else False,
        disc_id=r["disc_id"] if "disc_id" in keys else None,
        file_size=int(r["file_size"] or 0) if "file_size" in keys else 0,
        file_mtime_ns=int(r["file_mtime_ns"] or 0) if "file_mtime_ns" in keys else 0,
        last_scanned_at=r["last_scanned_at"] if "last_scanned_at" in keys else None,
        scan_error=r["scan_error"] if "scan_error" in keys else None,
        grouping=(r["grouping"] or "") if "grouping" in keys else "",
        playback_uri=playback_uri,
        playback_options=playback_options,
        resume_position=int(r["resume_position"] or 0) if "resume_position" in keys else 0,
    )


def _compute_file_hash(path: str) -> str | None:
    """Return an MD5 hex digest of a small sample of *path*, or None on error.

    Samples three 64 KB regions — start, middle, and end — plus the total file
    size.  Hashing only the header is fragile for formats whose first bytes are
    near-identical between distinct files (e.g. two FLAC re-encodes share the
    same STREAMINFO layout); sampling the body and tail makes false positives
    far less likely while keeping the hash cheap for large files.
    """
    chunk = 65536
    try:
        size = os.path.getsize(path)
        h = hashlib.md5()
        h.update(size.to_bytes(8, "little"))
        with open(path, "rb") as fh:
            h.update(fh.read(chunk))
            if size > chunk * 2:
                fh.seek(max(chunk, size // 2 - chunk // 2))
                h.update(fh.read(chunk))
            if size > chunk:
                fh.seek(max(0, size - chunk))
                h.update(fh.read(chunk))
        return h.hexdigest()
    except OSError:
        return None


def _is_safe_migration_skip(exc: sqlite3.OperationalError) -> bool:
    """Return True for idempotent migration reruns after a partial previous run."""
    msg = str(exc).lower()
    return "duplicate column name" in msg or "already exists" in msg


def _safe_stat(path: str) -> os.stat_result | None:
    try:
        return os.stat(path)
    except OSError:
        return None


def _row_matches_stat(row: sqlite3.Row, stat: os.stat_result) -> bool:
    keys = row.keys()
    if "file_size" not in keys or "file_mtime_ns" not in keys:
        return False
    return (
        int(row["file_size"] or 0) == int(stat.st_size)
        and int(row["file_mtime_ns"] or 0) == int(stat.st_mtime_ns)
        and not (row["scan_error"] if "scan_error" in keys else None)
    )


def _row_disc_id(row: sqlite3.Row) -> str:
    if "disc_id" not in row.keys():
        return ""
    return str(row["disc_id"] or "").strip()


def _read_tags(path: str) -> dict | None:
    try:
        f = MutagenFile(path, easy=True)
    except Exception as exc:
        LOG.warning("Failed to read tags from %s: %s", path, exc)
        return None
    if f is None:
        return None
    info = getattr(f, "info", None)
    def first(key: str) -> str:
        v = f.get(key)
        if isinstance(v, list) and v:
            return str(v[0])
        return ""
    def to_int(s: str) -> int:
        if not s:
            return 0
        s = s.split("/")[0].strip()
        try:
            return int(s)
        except ValueError:
            try:
                return int(s[:4])
            except ValueError:
                return 0
    disc_id = first("musicbrainz_discid")
    if not disc_id:
        disc_id = first("MusicBrainz/Disc Id")
    return {
        "title": first("title") or Path(path).stem,
        "artist": first("artist"),
        "album_artist": first("albumartist") or first("artist"),
        "album": first("album"),
        "track_no": to_int(first("tracknumber")),
        "disc_no": to_int(first("discnumber")) or 1,
        "year": to_int(first("date") or first("year")),
        "genre": first("genre"),
        "grouping": first("grouping"),
        "duration": float(getattr(info, "length", 0.0) or 0.0),
        "bitrate": int(getattr(info, "bitrate", 0) or 0),
        "samplerate": int(getattr(info, "sample_rate", 0) or 0),
        "disc_id": disc_id,
    }


def _audio_duration_seconds(path: Path | None) -> float | None:
    """Return an audio file duration for CUE boundary calculation, if readable."""
    if path is None:
        return None
    try:
        f = MutagenFile(path, easy=True)
    except Exception as exc:
        LOG.debug("Failed to read CUE image duration from %s: %s", path, exc)
        return None
    if f is None:
        return None
    info = getattr(f, "info", None)
    duration = float(getattr(info, "length", 0.0) or 0.0)
    return duration if duration > 0 else None


def _find_video_artwork(path: Path) -> Path | None:
    """Return an exact same-stem thumbnail sidecar for a video file, if present."""
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = path.with_suffix(ext)
        if p.exists():
            return p
    return None


def _find_local_artwork(folder: Path) -> Path | None:
    for name in ("cover.jpg", "cover.png", "folder.jpg", "folder.png", "front.jpg"):
        p = folder / name
        if p.exists():
            return p
    return None
