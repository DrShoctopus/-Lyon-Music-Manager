# Report 1: Critical Errors, Bugs, and Memory Risks

Review date: 2026-05-15

Scope: static review of the Python/PySide desktop app, with emphasis on packaging, worker lifecycles, subprocess handling, native resources, SQLite, and network sessions.

Verification performed:

- `python3 -m compileall -q main.py lyon tests`: passed.
- `python3 -m pytest -q`: not run because this machine's active Python has no `pytest`.
- UI/runtime smoke test: not run because this machine's active Python has no `PySide6`.

## Highest Priority Findings

### P0: Windows packaging spec points at the wrong project root

Evidence: `build/lyon.spec:15` sets `ROOT = Path(SPECPATH).resolve().parent`, but when the spec lives in `build/`, that resolves to the `build/` directory. The spec then looks for `build/main.py`, `build/bin`, and `build/docs/brand` at `build/lyon.spec:16-22` and `build/lyon.spec:67-71`.

Impact: the documented `pyinstaller build/lyon.spec` path can fail outright or produce a package missing runtime binaries and brand assets.

Suggested fix:

- Change `ROOT` to the repo root, for example `Path(SPECPATH).resolve().parent.parent`.
- Set `GENERATED_ICON = ROOT / "build" / "lyon-app-icon.ico"` after that root correction.
- Add CI assertions before PyInstaller: `Test-Path main.py`, `Test-Path docs\brand\lyon-app-icon.png`, and `Test-Path bin\ffmpeg.exe`.

### P0: libdiscid DLL directory handle is discarded

Evidence: `lyon/core/cd_detect.py:145` calls `os.add_dll_directory(path_str)` but does not store the returned handle.

Impact: on Windows, the added DLL directory can be removed immediately when the handle is garbage collected. Bundled `discid.dll` may fail to load, causing CD detection to silently fall back or fail.

Suggested fix:

- Mirror `lyon/core/playback_backend.py` and retain handles in a module-level list.
- Add a shutdown function to close those handles, then call it from `MainWindow.closeEvent`.
- Add a Windows CI smoke test that imports `discid` with only the bundled `bin` DLL available.

### P0: YouTube search can leave orphaned QThreads

Evidence: `_SearchWorker.run()` blocks in `yt_dlp.extract_info()` at `lyon/ui/youtube_view.py:56-61`. Starting a new search only disconnects signals and calls `quit()` at `lyon/ui/youtube_view.py:219-223`; it does not cancel the blocking call, wait for the old thread, or retain it until completion.

Impact: repeated searches can accumulate background threads. Closing the app while a search is in flight risks Qt's "QThread: Destroyed while thread is still running" abort.

Suggested fix:

- Disable a new search until the current worker finishes, or maintain a worker generation id and keep old workers alive until `finished`.
- Add `YouTubeView.shutdown()` that disconnects UI slots, requests interruption, waits briefly, and only then uses `terminate()` as a last resort.
- Call `self.youtube_view.shutdown()` from `MainWindow.closeEvent` before destroying widgets.

### P0: YouTube downloads can close while the worker is still running

Evidence: `YtDownloadDialog.closeEvent()` cancels and waits only 3000 ms at `lyon/ui/yt_download_dialog.py:213-217`, then accepts the close even if the thread is still running.

Impact: a slow network download or stuck postprocessor can outlive its parent dialog, causing crashes or callbacks into destroyed UI objects.

Suggested fix:

- On close during an active download, either ignore the close and show "Cancelling..." until the worker finishes, or disconnect UI slots and keep the dialog/worker alive until completion.
- Connect the worker to `deleteLater()` after it finishes.
- Add a forced termination path only after signals are disconnected and partial files are cleaned up.

### P1: yt-dlp import failure leaves the dialog disabled

Evidence: `YtDownloadWorker.run()` emits `error` and returns on `ImportError` at `lyon/core/yt_downloader.py:104-111`. The dialog only re-enables controls in `_on_finished()` at `lyon/ui/yt_download_dialog.py:205-211`.

Impact: if `yt-dlp` is unavailable or broken at runtime, the Download button remains disabled and Cancel remains enabled.

Suggested fix:

- Emit the worker completion signal in every fatal path, including `ImportError`.
- Prefer renaming the custom `finished = Signal(int, int)` to `download_finished` to avoid shadowing `QThread.finished`.

### P1: libcdio rip cancellation can hang and can leave partial files

Evidence: `_run_ffmpeg()` checks `self._cancel` only while iterating text lines from `proc.stdout` at `lyon/core/ripper.py:901-909`. ffmpeg progress often uses carriage-return stats rather than newline-delimited lines. The cancel path kills and waits, but unlike the raw CD path, it does not unlink `out`.

Impact: Cancel or app shutdown during libcdio ripping can remain blocked until ffmpeg emits a newline or exits. If `Ripper.shutdown()` reaches the forced `QThread.terminate()` path at `lyon/core/ripper.py:1001-1007`, the child ffmpeg process may survive and continue writing.

Suggested fix:

- Rework `_run_ffmpeg()` to poll `proc.poll()` on a short interval while a reader thread drains stdout/stderr.
- Check `self._cancel` on every interval, terminate/kill the process group, wait, and remove partial output in a `finally` block.
- Avoid `QThread.terminate()` for normal cancellation; reserve it for process exit only after children are killed.

### P1: CTDB verification decodes whole tracks into memory

Evidence: `compute_accuraterip_v1_crc()` captures all decoded PCM with `stdout=subprocess.PIPE` at `lyon/core/ctdb_verify.py:55-71`, then stores it again as an `array.array` at `lyon/core/ctdb_verify.py:75-83`.

Impact: this is not a leak, but it is a large peak-memory risk. Long tracks, hidden-track discs, or whole-disc files can spike hundreds of MB and freeze the app during post-rip verification.

Suggested fix:

- Stream ffmpeg stdout with `Popen`, process 4-byte stereo samples incrementally, and keep only a small ring buffer for the last 2940 samples needed by AccurateRip's last-track skip.
- Add a regression test using a fake stdout stream larger than memory-friendly chunk sizes.

### P1: Worker QObject is not scheduled for deletion

Evidence: `Ripper.start()` creates `RipWorker`, moves it to a thread, and connects signals at `lyon/core/ripper.py:971-981`, but never connects `worker.finished` to `worker.deleteLater`.

Impact: Python will likely drop the wrapper reference at `lyon/core/ripper.py:1018-1019`, but the Qt object lifecycle is ambiguous after `moveToThread`. This is a classic PySide leak/crash edge.

Suggested fix:

- Connect `self._worker.finished` to `self._worker.deleteLater`.
- Connect `self._thread.finished` to `self._thread.deleteLater`.
- Ensure `_on_finished()` does not wait on the thread from inside that same thread.

### P2: MusicBrainz user-agent is stale after settings changes

Evidence: `_init()` sets the MusicBrainz user-agent once using cached settings at `lyon/core/metadata.py:88-97`. `Settings.save()` invalidates only the settings cache, not `_initialised`.

Impact: changing the MusicBrainz contact in Settings may not affect future lookups until app restart.

Suggested fix:

- Add `metadata.reset_musicbrainz_useragent()` or make `_init()` compare the last applied tuple to current settings.
- Call it after saving metadata settings.

### P2: Settings dialog drops equalizer preamp and does not update video EQ

Evidence: `MainWindow.open_settings()` calls `self.player.set_equalizer(self.settings.equalizer_enabled, self.settings.equalizer_bands)` at `lyon/ui/main_window.py:343`, omitting `equalizer_preamp`. It also does not call `video_player_view.apply_equalizer(...)`.

Impact: EQ settings saved through Settings can apply differently from EQ settings saved through the equalizer dialog.

Suggested fix:

- Pass `self.settings.equalizer_preamp`.
- Apply the same values to `video_player_view`.
- Add a test that changing EQ settings through `SettingsDialog` preserves preamp in both audio and video paths.

## Test Coverage Gaps

- No tests currently cover `main_window.py`, `youtube_view.py`, or `video_player_view.py`.
- Existing ripper tests cover many path-building and failure cases, but should add cancellation tests for libcdio stdout behavior and partial-file cleanup.
- Add packaging tests for `build/lyon.spec` path resolution.
