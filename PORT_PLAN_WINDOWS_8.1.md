# Sea Lyon Media Manager — Windows 8.1 Port Plan

**Goal:** Sea Lyon runs on Windows 8.1 (64-bit) with full feature parity to the current Windows 10/11 build, from the same source tree.

**Status:** Planning document. No code changes have been made.

**Document version:** 1.0
**Last reviewed:** 2026-05-15

---

## 1. Executive Summary

The single technical blocker is `PySide6 >=6.6` in `requirements.txt`. Qt 6 / PySide6 requires Windows 10 or later — this is a Qt-level constraint, not a Python or installer constraint. To support Windows 8.1, the project must run against PySide2 (Qt 5.15) on Win 8.1 while continuing to run against PySide6 (Qt 6) on Win 10/11.

The recommended approach is the **`qtpy` compatibility shim**: a single codebase imports Qt classes from `qtpy.*` rather than `PySide6.*`, and `qtpy` dynamically routes to whichever Qt binding is installed. This is the standard cross-Qt-version strategy used by Spyder, the matplotlib Qt backend, and many other projects.

**Total estimated effort:** 19–35 working days (4–7 weeks) for initial delivery, plus ~20% sustained tax on every UI change thereafter.

**Strategic caveat:** Windows 8.1 has < 0.5% global market share, reached Microsoft end-of-life in January 2023, and PySide2 5.15.2.1 receives no further public security patches. Before committing to this work, confirm there is a concrete business case (e.g., a specific customer, regulatory environment, or legacy hardware constraint).

---

## 2. Hard Constraints

| Constraint | Value | Source |
|---|---|---|
| Windows 8.1 NT version | 6.3 | Microsoft platform constant |
| Max Python version on Win 8.1 | **3.12** | Python 3.13 release notes — requires Win 10+ |
| Last public PySide2 release on PyPI | **5.15.2.1 (Feb 2021)** | PyPI history |
| Qt 5.15 LTS open-source patch availability | Public patches ended at Qt 5.15.2; KDE Patch Collection continues | Qt Project announcements |
| GitHub Actions Win 8.1 runner | **Does not exist** | GitHub Actions runner image catalog |
| Self-hosted GHA runner on Win 8.1 | **Not feasible** — runner agent requires .NET 6 (Win 10+) | GitHub Actions self-hosted runner requirements |

---

## 3. Strategy Decision Matrix

Three approaches were considered. **A1 is the recommended strategy.** The rest of this plan assumes A1.

| Strategy | Description | Pros | Cons |
|---|---|---|---|
| **A1. `qtpy` shim (recommended)** | Single codebase; `from qtpy import ...`; supports both PySide2 and PySide6 at runtime | One source of truth; standard pattern in Python/Qt | Must avoid Qt 6-only APIs; CI must test both paths |
| A2. Permanent Win 8.1 fork | Maintain a `win81` branch using PySide2 only | Win 10/11 build stays on latest Qt | Every UI change must be applied twice; drift inevitable |
| A3. Downgrade everyone to PySide2 | Whole project moves to Qt 5.15 LTS | Maximum simplicity | Regresses current users to EOL Qt; loses Qt 6 features |

---

## 4. Phase 0 — Spike & Decisions (3–5 days)

**Objective:** prove the `qtpy` approach works on a representative slice of the UI before committing to a full port.

### Tasks
- Set up a Windows 8.1 (64-bit) VM. VMware Workstation Pro, Hyper-V, or VirtualBox all work. Microsoft no longer distributes Win 8.1 evaluation ISOs; you may need an existing license or MSDN/VLSC access.
- Install Python 3.12 (latest version supporting Win 8.1) on the VM. Add to PATH.
- Branch from `main` to `feat/win81-spike`.
- Convert exactly two files to `qtpy`:
  - `lyon/app.py` (the entry point and font/policy setup)
  - `lyon/core/playback_backend.py` (verify the VLC-only backend and unavailable-backend diagnostics remain Qt 5 compatible)
- Add `qtpy>=2.4` and `PySide2==5.15.2.1` to a separate `requirements-qt5.txt`.
- Confirm `pip install -r requirements-qt5.txt` succeeds inside the Win 8.1 VM.
- Manual smoke test: open the app, play one local FLAC via the libVLC backend, open one dialog.

### Decision artifact
A written go/no-go document covering:
- Did the spike succeed?
- List of every Qt 6-only API the spike encountered.
- Estimated multiplier on the rest of the work (smooth spike → use the estimates below; rough spike → add 50%).

### Exit criterion
Lyon launches on the Win 8.1 VM, plays a track, and exits cleanly. If this does not happen within 5 days, **stop and reconsider the project.**

---

## 5. Phase 1 — Compatibility Foundation (5–10 days)

**Objective:** the codebase is binding-agnostic — running against PySide6 produces no behavioral change from current `main`.

### 5.1 Add the shim

```text
requirements.txt              → keeps PySide6>=6.6
requirements-qt5.txt          → PySide2==5.15.2.1 + qtpy>=2.4
requirements-qt6.txt          → PySide6>=6.6 + qtpy>=2.4 (parity)
```

Add `qtpy>=2.4` to the main `requirements.txt` so it is available regardless of which Qt binding is selected.

### 5.2 Mechanical import rewrite

Replace `PySide6` imports across the project. Affected files (verified):

```
lyon/app.py
lyon/ui/main_window.py
lyon/ui/library_view.py
lyon/ui/now_playing.py
lyon/ui/queue_dialog.py
lyon/ui/equalizer_dialog.py
lyon/ui/ripper_view.py
lyon/ui/settings_dialog.py
lyon/ui/diagnostics_dialog.py
lyon/ui/first_run_dialog.py
lyon/ui/video_player_view.py
lyon/ui/widgets.py
lyon/ui/youtube_view.py
lyon/ui/yt_download_dialog.py
lyon/ui/styles.py
lyon/ui/branding.py
lyon/core/playback_backend.py
lyon/core/ripper.py
lyon/core/yt_downloader.py
```

Pattern:

```python
# Before
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

# After
from qtpy.QtCore import Qt, QUrl
from qtpy.QtWidgets import QAction   # qtpy normalizes QAction to QtWidgets
from qtpy.QtWidgets import QApplication
```

**Note on `QAction`:** in PySide6 / Qt 6, `QAction` is in `QtGui`. In PySide2 / Qt 5, it is in `QtWidgets`. `qtpy` exposes it from `QtWidgets` in both bindings to give you a single import path. The current code uses `from PySide6.QtGui import QAction` (verified in [main_window.py:5](lyon/ui/main_window.py:5)) — every such line must change.

### 5.3 Qt 6-only API audit and conditional handling

The former QtMultimedia fallback backend has been removed. Playback now requires
libVLC; if python-vlc or libVLC cannot be created, the app uses a non-playing
backend so the rest of the application can still launch and show diagnostics.

**Note on `HighDpiScaleFactorRoundingPolicy`:** the `Qt.HighDpiScaleFactorRoundingPolicy.PassThrough` reference at [app.py:17](lyon/app.py:17) is available in Qt 5.14 and later — **no conditional branch needed**. The scoped-enum syntax works in PySide2 5.15.

### 5.4 Regression validation

After all import rewrites, run the existing Win 10/11 build path:

- `pip install -r requirements-qt6.txt`
- `python main.py` on the dev machine
- Manually exercise every menu item, every dialog, VLC playback, and the VLC-unavailable diagnostics path
- Build the existing PyInstaller bundle: `pyinstaller build/lyon.spec`
- Run the bundle, repeat the smoke test

**Exit criterion:** byte-for-byte feature parity with pre-port behavior on Win 10/11. If any regression is observed, fix before continuing to Phase 2.

---

## 6. Phase 2 — Win 8.1 Runtime Bring-Up (5–10 days)

**Objective:** every feature works correctly inside the Win 8.1 VM.

### 6.1 Build on Win 10 / target Win 8.1

PyInstaller does not cross-compile — but a bundle produced on Win 10 using Python 3.12 + PySide2 5.15.2.1 will run on Win 8.1 because:
- Python 3.12 is the Win 8.1 floor (Python 3.13+ drops it).
- PySide2 5.15 binaries are linked against the Universal CRT, present on Win 8.1.
- libVLC 3.0.21 supports Windows 7+.

The build host should be Windows 10/11 with the Qt 5 requirements installed. The resulting `dist/LyonMusicManager/` runs on Win 8.1.

### 6.2 Feature validation matrix

Validate each feature on the Win 8.1 VM, ordered by risk:

| Feature | Win 8.1 risk | Expected outcome | Notes |
|---|---|---|---|
| App launch + splash | Low | Splash shows, main window opens | Verify Segoe UI font renders (Win 8.1 has it) |
| libVLC playback | Low | Audio plays | VLC 3.0.x supports Win 7+ |
| EQ controls | Low | Audible EQ change | Same `AudioEqualizer` API in VLC 3.x |
| Library scan | Low | Files indexed | Pure Python |
| MusicBrainz lookup | Low | Metadata fetched | Requires internet |
| CD detection | **Medium** | Audio CD detected | Windows kernel32 APIs stable since NT 6.0 |
| CD ripping (libcdio path) | **Medium** | FLAC produced | ffmpeg Windows static build runs on Win 8.1 |
| CD ripping (raw reader fallback) | **Medium** | FLAC produced | `DeviceIoControl` works on Win 8.1 |
| CTDB verification | Low | Accurate matches | Pure Python + ffmpeg |
| YouTube download | Low | MP4/FLAC produced | yt-dlp pure Python; ffmpeg post-processing |
| Eject CD | Low | Tray opens | `mciSendStringW` works on Win 8.1 |
| Settings persistence | Low | settings.json written | `%APPDATA%` exists on Win 8.1 |
| Runtime diagnostics dialog | Low | All checks displayed | Pure Python |

### 6.3 Known fragile spots

- **High-DPI rendering**: Win 8.1's high-DPI subsystem is less mature than Win 10's. Spot-check the UI at 125%, 150%, and 200% scale. The `PassThrough` policy at [app.py:17](lyon/app.py:17) should produce consistent results.
- **TLS / requests**: Win 8.1's built-in TLS support handles TLS 1.2 (MusicBrainz, CTDB, YouTube all require this). Older Win 8.1 without the April 2014 update may not — confirm the VM has all updates.
- **No QtWebEngine dependency**: confirmed via grep that no file in `lyon/` imports `QtWebEngine`. This was a potential blocker (QtWebEngine never supported Win 8.1) but it doesn't apply.

### Exit criterion
Every entry in the feature validation matrix is green. Any failure must be either fixed or explicitly documented as a Win 8.1 limitation.

---

## 7. Phase 3 — Dual Build Pipeline (3–5 days)

**Objective:** CI produces both a Win 10/11 installer and a Win 8.1-compatible installer automatically from every push.

### 7.1 GitHub Actions workflow split

Modify [.github/workflows/windows-build.yml](.github/workflows/windows-build.yml) to define a build matrix:

```yaml
strategy:
  matrix:
    include:
      - target: win10
        python: "3.11"
        requirements: requirements-qt6.txt
        installer_suffix: ""
        min_version: "10.0"
      - target: win81
        python: "3.12"
        requirements: requirements-qt5.txt
        installer_suffix: "-Win81"
        min_version: "6.3"
```

Both jobs run on `windows-latest` (Windows Server 2022). Outputs:
- `SeaLyonMediaManager-X.Y.Z-Setup.exe` (Win 10/11)
- `SeaLyonMediaManager-X.Y.Z-Setup-Win81.exe` (Win 8.1-compatible)

### 7.2 Installer adjustments

Duplicate or parameterize [build/lyon.iss](build/lyon.iss):
- `lyon.iss` (existing): `MinVersion=10.0`
- `lyon-win81.iss` (new): `MinVersion=6.3`

Inno Setup version constants:
- Win 8.0 = NT 6.2 (do not target this — Python 3.9+ requires 8.1)
- Win 8.1 = NT 6.3
- Win 10 = NT 10.0

### 7.3 Smoke-testing the Win 8.1 artifact

GitHub Actions has no Win 8.1 runner and **no self-hosted runner workaround** — the GHA runner agent requires .NET 6, which requires Windows 10 1607+.

Workarounds, in order of practicality:

1. **Manual artifact download** (default): every release tag, download the `-Win81` artifact, install on the maintained Win 8.1 VM, run a documented smoke-test checklist (10 minutes).
2. **Non-GHA CI**: Buildkite, TeamCity, or Jenkins agents have less strict OS requirements and can run on Win 8.1. Significant setup cost; only worthwhile if you're already running one of these.
3. **VM automation**: a Win 8.1 VM running a custom poll-and-test script (PowerShell loop that downloads new artifacts from a release endpoint). Brittle; not recommended.

### Exit criterion
Both installers produced by CI; both have been successfully installed and smoke-tested on their respective platforms.

---

## 8. Phase 4 — Hardening & Documentation (3–5 days)

### 8.1 Documentation updates

- Update [docs/BUILD.md](docs/BUILD.md) with the dual-target build instructions, requirements-qt5.txt vs requirements-qt6.txt, and the manual Win 8.1 smoke-test procedure.
- Update [README.md](README.md) system requirements section:
  - Windows 10/11 (recommended) — full feature set, current Qt 6
  - Windows 8.1 (legacy support) — full feature set, Qt 5.15 LTS, no further security patches
- Document the EOL position of Win 8.1 support in `docs/win81-support-policy.md`. Make it explicit when this support tier will be dropped (e.g., 2027 or when PySide2 5.15.2.1 develops a non-patchable CVE).

### 8.2 Runtime affordances

- On first launch under PySide2, the splash or About dialog shows a one-time banner: *"Sea Lyon is running in legacy compatibility mode on Windows 8.1. Some features may behave differently than on Windows 10/11."* — controlled by a `first_run_completed`-style flag in Settings.
- Diagnostics dialog includes the active Qt binding (`PySide2 5.15.2.1` or `PySide6 6.6.x`) for support purposes.

### 8.3 Maintained test surface

Add to `docs/win81-smoke-test.md`:
- Step-by-step Win 8.1 smoke test that a maintainer runs before tagging a release.
- Acceptance: every step ticks, or a clear ticket is filed.

### Exit criterion
Docs updated, runtime affordances merged, smoke-test checklist in repo, EOL policy published.

---

## 9. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| libVLC cannot initialize on Win 8.1 | Medium | Medium | App launches with playback disabled and diagnostics guidance; packaged releases must bundle/test libVLC. |
| `PySide2 5.15.2.1` develops a non-patchable security CVE | Medium | High | EOL policy already published. Have a graceful sunset plan. |
| A new feature requires a Qt 6-only API | High | Medium | Engineering policy: every new feature must check the qtpy compatibility table in `docs/win81-support-policy.md`. |
| Win 8.1 user reports an obscure bug | Medium | Low | Bug is filed with `legacy/win81` label and triaged at lower priority. |
| GitHub Actions deprecates `windows-latest` running PySide2 build | Low | Medium | Pin the build image (`windows-2022`) explicitly. |
| Microsoft pushes a Win 8.1 security update that breaks something | Low | Low | Win 8.1 is already past mainstream support; minimal additional risk. |

---

## 10. Open Questions

1. **Business case**: who is the Win 8.1 user? Internal user? External customer? Regulatory requirement? The answer determines whether the ongoing ~20% UI-change tax is worth it.
2. **EOL date**: when will Win 8.1 support be dropped? Recommend setting a specific calendar date now (e.g., 24 months from release) to avoid indefinite scope creep.
3. **Win 8.1 vs Win 8.0**: this plan targets 8.1 only. Win 8.0 is excluded because Python 3.9+ requires 8.1. Confirm 8.0 is not in scope.
4. **VM provisioning**: who owns the Win 8.1 test VM? It needs to be maintained, snapshot-protected, and updated as required.

---

## 11. Effort Summary

| Phase | Estimate | Critical-path? |
|---|---|---|
| Phase 0 — Spike & Decisions | 3–5 days | Yes — gates everything else |
| Phase 1 — Compatibility Foundation | 5–10 days | Yes |
| Phase 2 — Win 8.1 Runtime Bring-Up | 5–10 days | Yes |
| Phase 3 — Dual Build Pipeline | 3–5 days | No (can run in parallel with Phase 4) |
| Phase 4 — Hardening & Documentation | 3–5 days | No |
| **Total** | **19–35 working days (~4–7 weeks)** | |

**Ongoing maintenance tax:** estimate +20% on every UI change for Qt 5 / Qt 6 validation. Estimate +1 hour per release for manual Win 8.1 smoke test.

---

## 12. Recommended Decision

If the business case exists: proceed with Phase 0 immediately and treat its exit criterion as the true go/no-go gate.

If the business case is speculative: **do not start this work.** The macOS ARM64 port (separate plan) is a strictly higher-ROI investment.
