"""SQLite-backed music library."""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator

from mutagen import File as MutagenFile

from .settings import app_data_dir

LOG = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma"}
SUPPORTED_VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov"}
SUPPORTED_EXTS = SUPPORTED_AUDIO_EXTS | SUPPORTED_VIDEO_EXTS

DISPLAY_ARTIST_SQL = "COALESCE(NULLIF(album_artist,''), NULLIF(artist,''), 'Unknown Artist')"
DISPLAY_ALBUM_SQL = "COALESCE(NULLIF(album,''), 'Unknown Album')"

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

    @property
    def display_artist(self) -> str:
        return self.album_artist or self.artist or "Unknown Artist"

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


class Library:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (app_data_dir() / "library.db")
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA foreign_keys = ON")
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
        added = 0
        for root in roots:
            root = Path(root)
            if not root.exists():
                continue
            for dirpath, _dirs, files in os.walk(root):
                if should_cancel is not None and should_cancel():
                    with self._lock:
                        self.conn.commit()
                    return added
                for name in files:
                    ext = os.path.splitext(name)[1].lower()
                    if ext not in SUPPORTED_EXTS:
                        continue
                    full = os.path.join(dirpath, name)
                    if self.add_file(full):
                        added += 1
        with self._lock:
            self.conn.commit()
        return added

    def add_file(self, path: str | os.PathLike, disc_id: str | None = None) -> bool:
        path = str(path)
        ext = Path(path).suffix.lower()
        media_type = "video" if ext in SUPPORTED_VIDEO_EXTS else "audio"

        with self._lock:
            if self.conn.execute("SELECT 1 FROM tracks WHERE path = ?", (path,)).fetchone():
                if disc_id:
                    self.conn.execute(
                        "UPDATE tracks SET disc_id = ?"
                        " WHERE path = ? AND (disc_id IS NULL OR disc_id = '')",
                        (disc_id, path),
                    )
                return False
        meta = _read_tags(path)
        if meta is None:
            if media_type == "video":
                folder_name = Path(path).parent.name or "Videos"
                meta = {
                    "title": Path(path).stem,
                    "artist": folder_name, "album_artist": folder_name, "album": folder_name,
                    "track_no": 0, "disc_no": 1, "year": 0, "genre": "",
                    "duration": 0.0, "bitrate": 0, "samplerate": 0,
                }
            else:
                return False
        # Look for adjacent cover art.  YouTube video downloads keep their
        # thumbnail as a same-stem sidecar image next to the media file, so
        # prefer that exact match before falling back to album-folder art.
        file_path = Path(path)
        art = _find_video_artwork(file_path) if media_type == "video" else None
        art = art or _find_local_artwork(file_path.parent)
        with self._lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO tracks
                   (path, title, artist, album_artist, album, track_no, disc_no,
                    year, genre, duration, bitrate, samplerate, artwork_path, media_type,
                    disc_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    path,
                    meta["title"],
                    meta["artist"],
                    meta["album_artist"],
                    meta["album"],
                    meta["track_no"],
                    meta["disc_no"],
                    meta["year"],
                    meta["genre"],
                    meta["duration"],
                    meta["bitrate"],
                    meta["samplerate"],
                    str(art) if art else None,
                    media_type,
                    disc_id or None,
                ),
            )
            inserted = cur.rowcount > 0
            if not inserted and disc_id:
                # Row already existed (scanned earlier, or pre-feature rip).
                # Backfill disc_id so duplicate-CD detection works next time.
                self.conn.execute(
                    "UPDATE tracks SET disc_id = ?"
                    " WHERE path = ? AND (disc_id IS NULL OR disc_id = '')",
                    (disc_id, path),
                )
            return inserted

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

    def all_albums(self) -> list[tuple[str, str, str | None]]:
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT {DISPLAY_ARTIST_SQL} AS a,
                           {DISPLAY_ALBUM_SQL} AS display_album, MAX(artwork_path) AS art
                    FROM tracks
                    GROUP BY a, display_album
                    ORDER BY a COLLATE NOCASE, display_album COLLATE NOCASE"""
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
        """Yield every track in id order, paging to avoid loading the full table at once."""
        filter_sql = "" if media_type is None else "AND media_type = ?"
        last_id = 0
        while True:
            params = (
                (last_id, _PAGE_SIZE)
                if media_type is None
                else (last_id, media_type, _PAGE_SIZE)
            )
            with self._lock:
                rows = self.conn.execute(
                    f"SELECT * FROM tracks WHERE id > ? {filter_sql} ORDER BY id LIMIT ?",
                    params,
                ).fetchall()
            if not rows:
                break
            for r in rows:
                last_id = int(r["id"])
                yield _row_to_track(r)
            if len(rows) < _PAGE_SIZE:
                break

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

    def update_track(self, track_id: int, fields: dict) -> None:
        allowed = {"title", "artist", "album_artist", "album", "track_no", "disc_no", "year", "genre", "artwork_path"}
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
        from .smart_playlist import spec_from_json, spec_to_where, spec_order_and_limit
        spec = spec_from_json(rules_json)
        where, params = spec_to_where(spec)
        order, limit = spec_order_and_limit(spec)
        query = (
            f"SELECT * FROM tracks "
            f"WHERE media_type = 'audio' AND ({where}) "
            f"ORDER BY {order}"
            + (f" {limit}" if limit else "")
        )
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
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
            rows = self.conn.execute("SELECT id, path FROM tracks").fetchall()
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


def _row_to_track(r: sqlite3.Row) -> Track:
    keys = r.keys()
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
        media_type=r["media_type"] if r["media_type"] else "audio",
        rating=int(r["rating"] or 0) if "rating" in keys else 0,
        play_count=int(r["play_count"] or 0) if "play_count" in keys else 0,
        last_played=r["last_played"] if "last_played" in keys else None,
        liked=bool(r["liked"]) if "liked" in keys else False,
        disc_id=r["disc_id"] if "disc_id" in keys else None,
    )


def _is_safe_migration_skip(exc: sqlite3.OperationalError) -> bool:
    """Return True for idempotent migration reruns after a partial previous run."""
    msg = str(exc).lower()
    return "duplicate column name" in msg or "already exists" in msg


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
    return {
        "title": first("title") or Path(path).stem,
        "artist": first("artist"),
        "album_artist": first("albumartist") or first("artist"),
        "album": first("album"),
        "track_no": to_int(first("tracknumber")),
        "disc_no": to_int(first("discnumber")) or 1,
        "year": to_int(first("date") or first("year")),
        "genre": first("genre"),
        "duration": float(getattr(info, "length", 0.0) or 0.0),
        "bitrate": int(getattr(info, "bitrate", 0) or 0),
        "samplerate": int(getattr(info, "sample_rate", 0) or 0),
    }


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
