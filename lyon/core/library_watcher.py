"""Watched-folder indexing support for the local media library."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from .library import Library, ScanSummary, SUPPORTED_EXTS

try:  # pragma: no cover - dependency availability is environment-specific
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except Exception:  # pragma: no cover - exercised by availability checks
    FileSystemEvent = object  # type: ignore[assignment]
    FileSystemEventHandler = object  # type: ignore[assignment]
    Observer = None  # type: ignore[assignment]


_TEMP_SUFFIXES = {
    ".tmp", ".part", ".crdownload", ".download", ".partial", ".swp",
}
_ARTWORK_FILENAMES = {
    "cover.jpg", "cover.png", "folder.jpg", "folder.png", "front.jpg",
}
_ARTWORK_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass
class WatchBatch:
    """Coalesced filesystem work produced by watched folders."""

    changed_paths: set[str] = field(default_factory=set)
    deleted_paths: set[str] = field(default_factory=set)
    moved_paths: dict[str, str] = field(default_factory=dict)
    moved_folders: dict[str, str] = field(default_factory=dict)
    scan_roots: set[str] = field(default_factory=set)

    def is_empty(self) -> bool:
        return not (
            self.changed_paths
            or self.deleted_paths
            or self.moved_paths
            or self.moved_folders
            or self.scan_roots
        )


class LibraryFolderWatcher(QObject):
    """Small Qt wrapper around watchdog's recursive observer."""

    paths_changed = Signal(list)
    paths_deleted = Signal(list)
    paths_moved = Signal(list)   # list[(src, dest)]
    folders_moved = Signal(list)  # list[(src, dest)]
    folders_changed = Signal(list)
    watch_error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._observer = None
        self._roots: list[str] = []

    @staticmethod
    def is_available() -> bool:
        return Observer is not None

    def is_running(self) -> bool:
        return bool(self._observer and self._observer.is_alive())

    def start(self, roots: list[str]) -> None:
        self.stop()
        if Observer is None:
            self.watch_error.emit("Install watchdog to enable watched library folders.")
            return

        existing_roots = [
            str(Path(root))
            for root in roots
            if root and Path(root).exists() and Path(root).is_dir()
        ]
        if not existing_roots:
            return

        observer = Observer()
        handler = _WatchdogHandler(self)
        scheduled = 0
        for root in existing_roots:
            try:
                observer.schedule(handler, root, recursive=True)
                scheduled += 1
            except OSError as exc:
                self.watch_error.emit(f"Could not watch {root}: {exc}")
        if scheduled == 0:
            return
        try:
            observer.start()
        except Exception as exc:  # noqa: BLE001
            self.watch_error.emit(f"Could not start library watcher: {exc}")
            observer.stop()
            observer.join(timeout=1)
            return
        self._observer = observer
        self._roots = existing_roots

    def stop(self) -> None:
        observer = self._observer
        self._observer = None
        self._roots = []
        if observer is None:
            return
        observer.stop()
        observer.join(timeout=2)


class _WatchdogHandler(FileSystemEventHandler):
    def __init__(self, owner: LibraryFolderWatcher) -> None:
        super().__init__()
        self._owner = owner

    def on_created(self, event: FileSystemEvent) -> None:
        path = _event_path(event)
        if _event_is_directory(event):
            self._owner.folders_changed.emit([path])
        elif _is_indexable(path):
            self._owner.paths_changed.emit([path])
        elif _is_artwork_sidecar(path):
            self._owner.folders_changed.emit([str(Path(path).parent)])

    def on_modified(self, event: FileSystemEvent) -> None:
        path = _event_path(event)
        if not _event_is_directory(event) and _is_indexable(path):
            self._owner.paths_changed.emit([path])
        elif not _event_is_directory(event) and _is_artwork_sidecar(path):
            self._owner.folders_changed.emit([str(Path(path).parent)])

    def on_deleted(self, event: FileSystemEvent) -> None:
        path = _event_path(event)
        if _event_is_directory(event) or _is_indexable(path):
            self._owner.paths_deleted.emit([path])
        elif _is_artwork_sidecar(path):
            self._owner.folders_changed.emit([str(Path(path).parent)])

    def on_moved(self, event: FileSystemEvent) -> None:
        src = _event_path(event)
        dest = str(getattr(event, "dest_path", ""))
        if _event_is_directory(event):
            if src and dest:
                self._owner.folders_moved.emit([(src, dest)])
            elif src:
                self._owner.paths_deleted.emit([src])
            elif dest:
                self._owner.folders_changed.emit([dest])
            return
        src_ok = _is_indexable(src)
        dest_ok = _is_indexable(dest)
        if src_ok and dest_ok:
            self._owner.paths_moved.emit([(src, dest)])
        elif src_ok:
            self._owner.paths_deleted.emit([src])
        elif dest_ok:
            self._owner.paths_changed.emit([dest])
        else:
            art_roots = []
            if _is_artwork_sidecar(src):
                art_roots.append(str(Path(src).parent))
            if _is_artwork_sidecar(dest):
                art_roots.append(str(Path(dest).parent))
            if art_roots:
                self._owner.folders_changed.emit(art_roots)


class LibraryIndexThread(QThread):
    """Apply a coalesced watched-folder batch off the UI thread."""

    finished_with = Signal(object)  # ScanSummary
    failed_with = Signal(str)

    def __init__(
        self,
        library: Library,
        batch: WatchBatch,
        *,
        settle_ms: int = 500,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.library = library
        self.batch = batch
        self.settle_ms = max(0, int(settle_ms))
        self._cancel = False

    def request_stop(self) -> None:
        self._cancel = True
        self.requestInterruption()

    def run(self) -> None:
        summary = ScanSummary()
        try:
            for old_path, new_path in list(self.batch.moved_folders.items()):
                if self._should_cancel():
                    break
                summary.merge(
                    self.library.move_paths_under(
                        old_path,
                        new_path,
                        commit=False,
                        should_cancel=self._should_cancel,
                    )
                )

            for old_path, new_path in list(self.batch.moved_paths.items()):
                if self._should_cancel():
                    break
                self._wait_for_stable_file(new_path)
                summary.add_result(self.library.move_path(old_path, new_path, commit=False))

            for path in sorted(self.batch.deleted_paths):
                if self._should_cancel():
                    break
                if _is_indexable(path):
                    summary.removed += self.library.remove_path(path, commit=False)
                else:
                    summary.removed += self.library.remove_paths_under(path, commit=False)

            for root in sorted(self.batch.scan_roots):
                if self._should_cancel():
                    break
                summary.merge(
                    self.library.scan_paths_summary(
                        [root],
                        should_cancel=self._should_cancel,
                        force=True,
                    )
                )

            for path in sorted(self.batch.changed_paths):
                if self._should_cancel():
                    break
                self._wait_for_stable_file(path)
                summary.add_result(self.library.index_file(path))

            self.library.commit()
            self.finished_with.emit(summary)
        except Exception as exc:  # noqa: BLE001
            self.failed_with.emit(str(exc))

    def _should_cancel(self) -> bool:
        return self._cancel or self.isInterruptionRequested()

    def _wait_for_stable_file(self, path: str) -> None:
        if self.settle_ms <= 0 or not _is_indexable(path):
            return
        first = _stat_signature(path)
        if first is None:
            return
        slept = 0
        step = min(100, self.settle_ms)
        while slept < self.settle_ms and not self._should_cancel():
            time.sleep(step / 1000)
            slept += step
            current = _stat_signature(path)
            if current is not None and current == first:
                return
            first = current


def coalesce_batch(target: WatchBatch, incoming: WatchBatch) -> None:
    """Merge incoming filesystem work into *target* without duplicate paths."""
    target.scan_roots.update(incoming.scan_roots)
    for old_path, new_path in incoming.moved_folders.items():
        target.deleted_paths.discard(old_path)
        target.scan_roots.discard(old_path)
        target.scan_roots.discard(new_path)
        target.moved_folders[old_path] = new_path
    for old_path, new_path in incoming.moved_paths.items():
        target.deleted_paths.discard(old_path)
        target.changed_paths.discard(old_path)
        target.changed_paths.discard(new_path)
        target.moved_paths[old_path] = new_path
    for path in incoming.deleted_paths:
        target.changed_paths.discard(path)
        target.moved_paths.pop(path, None)
        target.deleted_paths.add(path)
    for path in incoming.changed_paths:
        if path not in target.deleted_paths and path not in target.moved_paths.values():
            target.changed_paths.add(path)


def _event_path(event: FileSystemEvent) -> str:
    return str(getattr(event, "src_path", ""))


def _event_is_directory(event: FileSystemEvent) -> bool:
    return bool(getattr(event, "is_directory", False))


def _is_indexable(path: str) -> bool:
    if not path:
        return False
    suffix = Path(path).suffix.lower()
    return suffix in SUPPORTED_EXTS and suffix not in _TEMP_SUFFIXES


def _is_artwork_sidecar(path: str) -> bool:
    if not path:
        return False
    p = Path(path)
    if p.suffix.lower() not in _ARTWORK_SUFFIXES:
        return False
    return p.name.lower() in _ARTWORK_FILENAMES or bool(p.stem)


def _stat_signature(path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return int(st.st_size), int(st.st_mtime_ns)
