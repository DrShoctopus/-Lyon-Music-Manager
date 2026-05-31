"""In-app knowledge base covering every feature in detail."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import __app_name__, __version__

# ---------------------------------------------------------------------------
# Content
#
# Each entry is (slug, title, html_body).  Children are nested through the
# tree below.  Bodies are plain HTML rendered by QTextBrowser, so they support
# headings, lists, tables and the <a href="kb:slug"> cross-link scheme.
# ---------------------------------------------------------------------------


def _wrap(title: str, body: str) -> str:
    return (
        "<html><head><style>"
        "body { font-family: 'Segoe UI', Tahoma, sans-serif; font-size: 10.5pt; "
        "color: #eef7ff; line-height: 1.45; }"
        "h1 { font-size: 17pt; color: #6ed1ff; margin: 0 0 12px 0; }"
        "h2 { font-size: 13pt; color: #9ad9ff; margin: 18px 0 6px 0; "
        "border-bottom: 1px solid #25323f; padding-bottom: 2px; }"
        "h3 { font-size: 11pt; color: #cfe7ff; margin: 14px 0 4px 0; }"
        "p { margin: 6px 0; }"
        "ol, ul { margin: 6px 0 6px 22px; padding: 0; }"
        "li { margin: 3px 0; }"
        "code, kbd { background: #1a232c; color: #f5d27b; padding: 1px 5px; "
        "border-radius: 3px; font-family: Consolas, monospace; }"
        "kbd { color: #a7f3d0; }"
        ".tip { background: #122131; border-left: 3px solid #4aa3ff; "
        "padding: 8px 12px; margin: 10px 0; border-radius: 4px; }"
        ".warn { background: #2a1b14; border-left: 3px solid #f1a861; "
        "padding: 8px 12px; margin: 10px 0; border-radius: 4px; }"
        ".step { background: #0e1820; border-left: 3px solid #7bdcff; "
        "padding: 6px 12px; margin: 8px 0; border-radius: 4px; }"
        "a { color: #7bdcff; text-decoration: none; }"
        "table { border-collapse: collapse; margin: 8px 0; }"
        "th, td { border: 1px solid #25323f; padding: 4px 10px; text-align: left; }"
        "th { background: #16222e; color: #cfe7ff; }"
        "</style></head><body>"
        f"<h1>{title}</h1>{body}</body></html>"
    )


WELCOME = _wrap(
    f"Welcome to {__app_name__}",
    f"""
    <p>{__app_name__} (version {__version__}) is a desktop media manager
    that combines a music library, CD ripper, audio/video player, podcast and
    internet-radio reader, and a YouTube search/download tool in a single
    Windows Media Player-inspired interface.</p>

    <p>This knowledge base documents every screen and feature in the app.
    Pick a topic from the tree on the left, or use the search box above it to
    jump directly to a feature by name.</p>

    <h2>How the app is organised</h2>
    <ul>
      <li><b>Tabs</b> across the top of the window switch between the major
      areas: Library, Now Playing, Podcasts, Radio, Video, Disc, Rip and
      YouTube. Each tab has its own keyboard shortcut
      (<kbd>Ctrl+1</kbd> through <kbd>Ctrl+8</kbd>).</li>
      <li>The <b>transport bar</b> at the bottom is always visible and
      controls whatever is currently playing.</li>
      <li>The <b>menu bar</b> at the very top gives you File, Playback, View,
      Settings and Help actions.</li>
    </ul>

    <h2>If you are brand new</h2>
    <ol>
      <li>Read <a href="kb:flow-rip-cd">"From Opening the App to Ripping a CD"</a>
      for a complete start-to-finish walkthrough.</li>
      <li>Then read <a href="kb:library">Library Management</a> to learn how
      to organise your music collection.</li>
      <li>Use <a href="kb:diagnostics">Runtime Diagnostics</a> if a feature is
      greyed out or missing — it tells you exactly which native component
      (ffmpeg, VLC, libdiscid) needs attention.</li>
    </ol>

    <p style="margin-top:18px; padding-top:12px; border-top:1px solid #25323f;
    color:#9ad9ff; font-style:italic;">{__app_name__} is inspired by and
    dedicated to my Grandfather, Chuck Lyon — it bears his name, and the love
    of music he shares runs through everything it does.</p>
    """,
)


FLOW_RIP_CD = _wrap(
    "From Opening the App to Ripping a CD",
    """
    <p>This is the complete process flow for a brand-new install. Follow the
    steps in order. Each step lists exactly what to click and what to expect
    on screen.</p>

    <h2>Step 1 — Launch the app</h2>
    <div class="step">
      <p>Launch <b>Sea Lyon Media Manager</b> from the Start menu (Windows) or
      the Applications folder (macOS). From the portable Windows build you can
      double-click <code>LyonMusicManager.exe</code>; from a source checkout
      run <code>py main.py</code>.</p>
      <p>A splash screen appears for a moment, then the main window opens
      with the <b>Library</b> tab in front.</p>
    </div>

    <h2>Step 2 — First-run setup</h2>
    <div class="step">
      <p>On the very first launch a setup dialog
      (<i>"Let's finish setting up Sea Lyon Media Manager"</i>) appears. You
      will see:</p>
      <ul>
        <li><b>Music folder for new rips</b> — the folder where ripped CDs and
        YouTube downloads will be saved by default. The suggested path is
        <code>%USERPROFILE%\\Music\\Lyon</code> on Windows or
        <code>~/Music/Lyon</code> on macOS. Accept it or click <i>Browse…</i>
        to choose a different location.</li>
        <li><b>Library folders to scan</b> — one or more folders that already
        contain music or video files. Click <i>Add Folder…</i> to include each
        one. You can skip this if you only want to rip CDs to start with.</li>
      </ul>
      <p>Click <b>Save Setup</b>. The app scans the listed folders in the
      background and populates the library. (Choose <b>Skip Setup</b> to take
      care of this later from the File and Settings menus.)</p>
    </div>

    <h2>Step 3 — Verify your runtime is healthy</h2>
    <div class="step">
      <p>Open <b>Help → Runtime Diagnostics</b>. A table shows each native
      dependency (ffmpeg, VLC/libVLC, libdiscid, Python packages) with a
      status of OK, WARNING or MISSING.</p>
      <p>For CD ripping you need <b>ffmpeg</b> and <b>libdiscid</b> to be OK.
      For audio playback you need <b>VLC/libVLC</b>. The <i>How to fix</i>
      column tells you exactly what to do — the installed macOS app bundles
      these already, while on Windows (and source checkouts) it names the file
      to drop into <code>bin\\</code>.</p>
    </div>

    <h2>Step 4 — Configure ripping preferences (one time only)</h2>
    <div class="step">
      <ol>
        <li>Open <b>Settings → CD Ripping</b>.</li>
        <li>Pick an <b>Output format</b>. FLAC is recommended for archival
        rips; choose MP3, M4A, OGG or Opus for smaller lossy files.</li>
        <li>Set the <b>FLAC compression</b> level (lossless) or the
        <b>Bitrate</b> (lossy).</li>
        <li>Tick <b>Eject disc after rip</b> if you want hands-free
        operation.</li>
        <li>Tick <b>Verify rip accuracy against CUETools DB</b> for FLAC rips
        to confirm bit-perfect results.</li>
        <li>Under the <b>Metadata</b> tab, confirm <i>Look up metadata
        online automatically</i> and <i>Download cover art</i> are
        enabled, and that the MusicBrainz contact value is set to your own
        email — see <a href="kb:settings-metadata">Metadata settings</a>.</li>
        <li>Click <b>OK</b> to save.</li>
      </ol>
    </div>

    <h2>Step 5 — Insert your CD</h2>
    <div class="step">
      <p>Put the audio disc into your optical drive. Wait until Windows
      recognises it (the drive light stops blinking).</p>
    </div>

    <h2>Step 6 — Open the Rip tab</h2>
    <div class="step">
      <p>Click the <b>Rip</b> tab (or press <kbd>Ctrl+6</kbd>). The Rip view
      contains:</p>
      <ul>
        <li>A <b>CD Drive</b> dropdown listing every optical drive the system
        reports.</li>
        <li>Buttons: <b>Refresh Drives</b>, <b>Read Disc</b>, <b>Rip CD</b>,
        <b>Cancel</b>.</li>
        <li>An album metadata panel (cover art, Artist, Album, Year,
        Group/AlbumArtist).</li>
        <li>A track table showing track number, title and status.</li>
        <li>A status line at the bottom.</li>
      </ul>
    </div>

    <h2>Step 7 — Read the disc</h2>
    <div class="step">
      <ol>
        <li>Pick your drive from the dropdown if it is not selected.</li>
        <li>Click <b>Read Disc</b>. The status line shows
        <i>"Reading disc…"</i> (naming the drive on Windows).</li>
        <li>The app reads the Table-of-Contents, computes the MusicBrainz
        disc ID, and queries CUETools DB, MusicBrainz and TheAudioDB in
        sequence.</li>
        <li>When the lookup completes, the album fields and track titles fill
        in automatically and the cover art appears on the left.</li>
      </ol>
      <p class="tip"><b>Already-in-library check.</b> If this disc was ripped
      previously, the status line says <i>"Already in library — disc
      ejected"</i> and the drive opens automatically. This prevents
      accidental duplicate rips.</p>
    </div>

    <h2>Step 8 — Correct the metadata (optional)</h2>
    <div class="step">
      <p>If anything is wrong — wrong release, mis-spelt title, etc. — you
      have three options:</p>
      <ul>
        <li>Type directly into the Artist / Album / Year / Group fields and
        the track titles in the table.</li>
        <li>Click <b>Search Online</b> to re-query MusicBrainz / TheAudioDB
        with the current Artist + Album values; choose a different match.</li>
        <li>Click <b>Clear Metadata</b> to wipe the fields and start
        over.</li>
      </ul>
      <p>The <b>Will save to:</b> line under the table previews the exact
      folder path the rip will go to so you can verify before starting.</p>
    </div>

    <h2>Step 9 — Start ripping</h2>
    <div class="step">
      <ol>
        <li>Click <b>Rip CD</b>.</li>
        <li>Each track shows a live percentage in the Status column. The
        currently-active track is highlighted.</li>
        <li>The transport bar progress also reflects overall progress; the
        taskbar icon shows a progress overlay on Windows.</li>
        <li>If a file already exists at the target path, the app warns you
        and lets you cancel before overwriting.</li>
      </ol>
    </div>

    <h2>Step 10 — Verification and post-rip actions</h2>
    <div class="step">
      <p>For FLAC rips with CUETools DB verification enabled:</p>
      <ul>
        <li>After each track is ripped, the app re-reads the file and
        compares its AccurateRip v1 checksum against the CTDB database.</li>
        <li>The track status becomes <b>Done ✓</b> on match,
        <b>Verified (offset)</b> if matched after a sample shift, or
        <b>Unverified</b> if no match was found.</li>
      </ul>
      <p>If <b>Eject after rip</b> is enabled, the disc tray opens
      automatically when all tracks finish.</p>
      <p>Any failed tracks stay in the table with a <b>Failed</b> status;
      click <b>Retry Failed Tracks</b> to re-rip just those.</p>
    </div>

    <h2>Step 11 — The library imports the rip automatically</h2>
    <div class="step">
      <p>Each successfully ripped track is added to the library as soon as
      its file is written. Switch to the <b>Library</b> tab and you will see
      the new album under its Artist immediately — no manual rescan
      required.</p>
    </div>

    <h2>Step 12 — Play your rip</h2>
    <div class="step">
      <ol>
        <li>Open <b>Library</b> (<kbd>Ctrl+1</kbd>).</li>
        <li>Click <b>Albums</b> in the left navigation, locate the new
        album.</li>
        <li>Double-click any track, or right-click the album and choose
        <b>Play</b> / <b>Add to Queue</b>.</li>
        <li>Use the transport bar at the bottom to pause, skip, seek and
        adjust volume.</li>
      </ol>
    </div>

    <p class="tip">Need to rip another disc? Insert it and click <b>Read
    Disc</b> again — there's no need to re-do steps 1–4.</p>

    <p>See also: <a href="kb:rip">Rip view reference</a>,
    <a href="kb:cd-metadata">Disc metadata providers</a>,
    <a href="kb:library">Library Management</a>.</p>
    """,
)


LIBRARY_OVERVIEW = _wrap(
    "Library Management",
    """
    <p>The <b>Library</b> tab is the heart of the app. It indexes every
    audio and video file under the folders you have added, and lets you
    browse, search, rate, organise into playlists, edit metadata, and play
    them. The full index lives in <code>library.db</code> alongside
    <code>settings.json</code> in your app-data folder.</p>

    <h2>Anatomy of the Library screen</h2>
    <ol>
      <li><b>Search box</b> (top) — instant full-text search across title,
      artist, album artist, album and display fallbacks.</li>
      <li><b>Browse selector</b> — switch between Artists, Albums, Genres,
      All Tracks, Playlists and the virtual collections (Liked,
      Top Rated, Recently Played, Most Played).</li>
      <li><b>Left list</b> — the items in the current browse mode (e.g. the
      list of artists).</li>
      <li><b>Playlists pane</b> — your manual and smart playlists, with
      drag-and-drop support.</li>
      <li><b>Tracks table</b> — the songs matching the current selection.
      Sortable columns include #, Title, Artist, Album, Time, Year, Genre,
      Rating, Play Count, Last Played and Date Added.</li>
      <li><b>View-mode buttons</b> at the top of the tracks table:
      <i>▤ List</i>, <i>⊞ Grid</i> (album-art cards), and
      <i>≡ Simple</i> (clean one-line-per-track view).</li>
      <li><b>Enqueue</b> button to add the current selection to the
      playback queue.</li>
    </ol>

    <h2>Easy-to-follow guide</h2>
    <p>Pick the section that matches what you want to do:</p>
    <ul>
      <li><a href="kb:library-add">Add music to your library</a></li>
      <li><a href="kb:library-browse">Browse and search</a></li>
      <li><a href="kb:library-play">Play tracks, albums and artists</a></li>
      <li><a href="kb:library-playlists">Create manual playlists</a></li>
      <li><a href="kb:library-smart">Build smart playlists</a></li>
      <li><a href="kb:library-rate">Rate, like and use virtual
      collections</a></li>
      <li><a href="kb:library-edit">Edit metadata (one track or in
      bulk)</a></li>
      <li><a href="kb:library-fetch">Fetch metadata from MusicBrainz</a></li>
      <li><a href="kb:library-dupes">Find and clean up duplicates</a></li>
      <li><a href="kb:library-maintain">Keep the library healthy</a></li>
    </ul>
    """,
)


LIBRARY_ADD = _wrap(
    "Add music to your library",
    """
    <p>There are four ways to add music files to the library. All of them
    feed into the same SQLite index.</p>

    <h2>1. Add a folder permanently</h2>
    <ol>
      <li>Open <b>File → Add Folder to Library…</b> (or click <b>Add
      Folder</b> on the empty-library prompt).</li>
      <li>Pick a folder. The app scans it recursively and remembers it as a
      "library root".</li>
      <li>If <b>Watch library folders for changes</b> is enabled in
      <b>Settings → Library</b>, new files dropped into that folder later
      are detected automatically.</li>
    </ol>

    <h2>2. Drag-and-drop</h2>
    <p>Drop one or more folders or individual audio/video files onto any
    part of the main window. Folders are added permanently; loose files are
    indexed in place. Supported extensions are:</p>
    <ul>
      <li><b>Audio:</b> .flac, .mp3, .m4a, .aac, .ogg, .opus, .wav, .aiff,
      .aif, .wma, .ape, .mka, .alac</li>
      <li><b>Video:</b> .mp4, .mkv, .webm, .avi, .mov</li>
    </ul>

    <h2>3. Rip a CD</h2>
    <p>Anything ripped through the <b>Rip</b> tab is added to the library as
    each track finishes — no extra step required. See
    <a href="kb:flow-rip-cd">From Opening the App to Ripping a CD</a>.</p>

    <h2>4. Download from YouTube</h2>
    <p>If <i>Automatically add downloads to library</i> is enabled
    (<b>Settings → YouTube</b>), every completed yt-dlp download is
    imported automatically.</p>

    <h2>Re-scan manually</h2>
    <p>If you've added files outside of folder-watching, choose <b>File →
    Rescan Library</b>. The app re-walks every saved root and picks up
    additions and edits since the last scan.</p>

    <p class="tip">The first scan of a large library can take several
    minutes. You can keep using the app — the scanner runs on a background
    thread and updates the table as it goes.</p>
    """,
)


LIBRARY_BROWSE = _wrap(
    "Browse and search",
    """
    <h2>Browse modes</h2>
    <table>
      <tr><th>Mode</th><th>What it shows</th></tr>
      <tr><td>Artists</td><td>Every artist with at least one track.
      Selecting one fills the tracks table with that artist's songs.</td></tr>
      <tr><td>Albums</td><td>Every album. Use Grid view to flip through
      cover-art cards.</td></tr>
      <tr><td>Genres</td><td>Genre tags read from your files.</td></tr>
      <tr><td>All Tracks</td><td>Flat list of every track in the
      library.</td></tr>
      <tr><td>Playlists</td><td>Your manual and smart playlists; see
      <a href="kb:library-playlists">playlists</a>.</td></tr>
      <tr><td>Virtual collections</td><td>Liked, Top Rated, Recently
      Played, Most Played, Recently Added — generated from your listening
      history and ratings.</td></tr>
    </table>

    <h2>Search</h2>
    <p>Click the search box at the top or press <kbd>Ctrl+F</kbd>. Type any
    fragment of a title, artist, album or album-artist; the tracks table
    filters as you type. Search is case-insensitive and works across the
    entire library regardless of which browse mode you are in.</p>

    <h2>Sorting and columns</h2>
    <ol>
      <li>Click any column header to sort by that field.</li>
      <li>Click again to reverse the order.</li>
      <li>Right-click the column header to show or hide individual columns,
      or to restore the default set.</li>
      <li>Numeric columns (#, Time, Rating, Year, Play Count) sort
      numerically, not alphabetically.</li>
    </ol>

    <h2>View modes</h2>
    <ul>
      <li><b>List</b> — the default detailed table.</li>
      <li><b>Grid</b> — album-art cards; double-click a card to drill into
      its tracks.</li>
      <li><b>Simple</b> — a clean one-line-per-track layout when you want
      less visual noise.</li>
    </ul>
    """,
)


LIBRARY_PLAY = _wrap(
    "Play tracks, albums and artists",
    """
    <h2>Basic playback</h2>
    <ul>
      <li><b>Double-click</b> any track — it plays immediately and the rest
      of the current selection becomes the queue.</li>
      <li><b>Right-click</b> a track, album or artist to get the context
      menu: <i>Play</i>, <i>Add to Queue</i>, <i>Play Next</i>,
      <i>Add to Playlist…</i>, <i>Edit Metadata…</i>, and more.</li>
      <li>Select multiple tracks (<kbd>Ctrl+Click</kbd> or
      <kbd>Shift+Click</kbd>) and click <b>Enqueue</b> to queue exactly that
      set.</li>
    </ul>

    <h2>Queue management</h2>
    <p>Press <kbd>Ctrl+Q</kbd> or open <b>Playback → Show Queue</b> to view
    the current queue. You can reorder tracks by drag-and-drop, remove
    items, and clear the queue. The queue is saved on exit and restored on
    next launch.</p>

    <h2>Now Playing</h2>
    <p>Press <kbd>Ctrl+L</kbd> or click the album art in the transport bar
    to jump to the <b>Now Playing</b> view, which shows full-size art,
    synced lyrics, queue preview, and a rating control. See
    <a href="kb:now-playing">Now Playing</a> for details.</p>

    <h2>Transport bar controls</h2>
    <p>The bottom bar exposes: Previous, Play/Pause, Next, Stop, Shuffle,
    Repeat (off / all / one), Mute, Volume slider, Seek slider, current
    track / artist, elapsed / remaining time, equalizer button, cast
    button, queue button, and the sleep timer.</p>
    """,
)


LIBRARY_PLAYLISTS = _wrap(
    "Create manual playlists",
    """
    <h2>Create a playlist</h2>
    <ol>
      <li>Right-click in the <b>Playlists</b> pane on the left.</li>
      <li>Choose <b>New Playlist…</b>.</li>
      <li>Type a name and press Enter.</li>
    </ol>

    <h2>Add tracks to a playlist</h2>
    <p>Three ways:</p>
    <ul>
      <li>Drag tracks from the tracks table onto a playlist row.</li>
      <li>Right-click selected tracks → <b>Add to Playlist…</b>.</li>
      <li>Right-click the current queue and choose <b>Save Queue as
      Playlist…</b> to capture exactly what is in the queue right now.</li>
    </ul>

    <h2>Open / edit / delete</h2>
    <p>Click a playlist to view its contents in the tracks table. Right-click
    a playlist for:</p>
    <ul>
      <li><b>Rename…</b></li>
      <li><b>Remove Track from Playlist</b> (also via the Delete key inside
      the tracks table while a playlist is selected)</li>
      <li><b>Export as M3U…</b> — writes a standard <code>.m3u</code> file
      that other players (Foobar, VLC, etc.) understand</li>
      <li><b>Delete Playlist</b> — removes the playlist; the tracks
      themselves stay in the library</li>
    </ul>

    <h2>Import playlists</h2>
    <p>Drag an <code>.m3u</code> / <code>.m3u8</code> / <code>.pls</code>
    file onto the window, or use <b>File → Add Folder to Library…</b> on a
    folder that contains playlist files. Imported playlists appear in the
    Playlists pane.</p>
    """,
)


LIBRARY_SMART = _wrap(
    "Build smart playlists",
    """
    <p>A smart playlist is a saved query. It auto-refreshes whenever the
    library changes, so it always reflects the current state of your
    collection.</p>

    <h2>Create one</h2>
    <ol>
      <li>Right-click in the Playlists pane → <b>New Smart Playlist…</b>.</li>
      <li>Give it a name.</li>
      <li>Add one or more rules. Each rule has a field, an operator and a
      value. Common combinations:
        <ul>
          <li><b>Genre is Jazz</b> AND <b>Rating ≥ 4</b></li>
          <li><b>Date Added in the last 30 days</b></li>
          <li><b>Play Count is 0</b> (never played)</li>
          <li><b>Artist contains "Beatles"</b></li>
        </ul>
      </li>
      <li>Pick <b>Match all / any rules</b>.</li>
      <li>Optionally set a limit and a sort order (e.g. "Most played, max
      50 tracks").</li>
      <li>Click <b>OK</b>.</li>
    </ol>

    <h2>Edit a smart playlist</h2>
    <p>Right-click the playlist → <b>Edit Smart Playlist…</b>. Changes are
    applied immediately the next time you select it.</p>

    <h2>Available fields</h2>
    <ul>
      <li>Title, Artist, Album Artist, Album, Genre, Year</li>
      <li>Rating (0–5)</li>
      <li>Liked (true/false)</li>
      <li>Play Count</li>
      <li>Last Played, Date Added</li>
      <li>File path, file extension</li>
    </ul>

    <p>Smart playlists are stored as JSON inside the library database, so
    they survive restarts and library rescans.</p>
    """,
)


LIBRARY_RATE = _wrap(
    "Rate, like, and use virtual collections",
    """
    <h2>Rate a track</h2>
    <p>Three places give you the same rating control (1–5 stars; click the
    first star a second time to clear it):</p>
    <ul>
      <li>The <b>Rating</b> column in the tracks table.</li>
      <li>The stars in the <b>Now Playing</b> view.</li>
      <li>The right-click context menu on any track or selection.</li>
    </ul>

    <h2>Like / unlike</h2>
    <p>Click the heart icon in Now Playing, or right-click → <b>Like</b>.
    Liked tracks are added to the <b>Liked</b> virtual collection.</p>

    <h2>Virtual collections</h2>
    <table>
      <tr><th>Collection</th><th>Definition</th></tr>
      <tr><td>Liked</td><td>Every track you've hearted.</td></tr>
      <tr><td>Top Rated</td><td>Tracks with a rating of 4 or 5
      stars.</td></tr>
      <tr><td>Recently Played</td><td>The last 100 tracks you actually
      played (50%+ of duration).</td></tr>
      <tr><td>Most Played</td><td>Highest play counts first.</td></tr>
      <tr><td>Recently Added</td><td>Sorted by Date Added
      descending.</td></tr>
    </table>

    <p>Play counts increment automatically once a track has played past the
    halfway mark. This same threshold is what scrobbles use; see
    <a href="kb:scrobbling">Scrobbling</a>.</p>
    """,
)


LIBRARY_EDIT = _wrap(
    "Edit metadata",
    """
    <h2>Edit a single track</h2>
    <ol>
      <li>Right-click the track → <b>Edit Metadata…</b>.</li>
      <li>Change Title, Artist, Album Artist, Album, Year, Track number,
      Disc number, Genre or comments.</li>
      <li>Optionally drop a new cover-art image onto the artwork box, or
      click <b>Choose Image…</b>.</li>
      <li>Click <b>OK</b>.</li>
    </ol>
    <p>Changes are written to the file on disk with Mutagen (so other apps
    see the new tags) and to the library index simultaneously.</p>

    <h2>Edit multiple tracks at once (batch)</h2>
    <ol>
      <li>Select two or more tracks (<kbd>Ctrl+Click</kbd> /
      <kbd>Shift+Click</kbd>).</li>
      <li>Right-click → <b>Edit Metadata…</b>.</li>
      <li>The dialog opens in <b>Batch</b> mode: each field has a checkbox
      that says <i>"Apply to all selected"</i>.</li>
      <li>Tick only the fields you want to change, fill them in, click
      <b>OK</b>. Fields with unchecked boxes stay as they were on each
      file.</li>
    </ol>

    <p class="warn">Batch edits cannot be undone. The original tags are
    overwritten. If you are not sure, edit one track first to confirm the
    result looks right.</p>

    <h2>Re-read tags from disk</h2>
    <p>If you edited tag data in another app (Mp3tag, Picard, etc.), choose
    <b>File → Rescan Library</b> so the library picks up the changes.</p>
    """,
)


LIBRARY_FETCH = _wrap(
    "Fetch metadata from MusicBrainz",
    """
    <p>For any album already in your library, you can re-run the same
    MusicBrainz / TheAudioDB lookup that the CD ripper uses. This is
    useful when:</p>
    <ul>
      <li>Tracks came in untagged or with bad tags.</li>
      <li>An album is missing cover art.</li>
      <li>You want to switch to a different release (Deluxe edition,
      remastered, etc.).</li>
    </ul>

    <h2>Steps</h2>
    <ol>
      <li>In the library, right-click the album (Albums browse mode) or any
      track in the album → <b>Fetch Album Metadata…</b>.</li>
      <li>The Metadata Fetch dialog appears with a list of candidate
      releases ranked by match score.</li>
      <li>Tick the candidate you want; preview the proposed Artist,
      Album, Year, Track titles and cover art.</li>
      <li>Optionally tick <b>Download cover art</b>.</li>
      <li>Click <b>Apply</b>. Tags and artwork are written to every track
      file in the album.</li>
    </ol>

    <p class="tip">Set a real contact value in <b>Settings → Metadata →
    MusicBrainz Contact</b> before running heavy lookups; without it the
    server may rate-limit you.</p>
    """,
)


LIBRARY_DUPES = _wrap(
    "Find and clean up duplicates",
    """
    <p>The duplicate finder identifies tracks that look like the same song.
    It only touches the library index — your files on disk are never
    deleted.</p>

    <h2>Detection modes</h2>
    <p>Choose a mode from the dropdown at the top of the dialog:</p>
    <ul>
      <li><b>By Title + Artist</b> — matches tracks whose normalised
      Artist and Title tags are identical. Fast and requires no extra
      tools.</li>
      <li><b>By File Hash</b> — compares header, middle and tail samples
      of the audio data, catching re-encodes and renamed copies even when
      tags differ.</li>
      <li><b>By AcoustID Fingerprint</b> — matches by acoustic content
      regardless of tags or format. Requires <code>fpcalc</code> in
      <code>bin/</code> and an AcoustID API key. Tracks must be scanned
      first using <i>Scan Missing Fingerprints…</i>.</li>
    </ul>

    <h2>Run it</h2>
    <ol>
      <li>Open <b>File → Find Duplicates…</b>.</li>
      <li>Pick a detection mode.</li>
      <li>The dialog groups suspected duplicates together. Each group
      contains 2 or more rows.</li>
      <li>For each group, tick the rows you want removed from the library.
      The app pre-selects the lower-quality copy (lower bitrate / shorter
      duration / older Date Added).</li>
      <li>Click <b>Remove Selected from Library</b>.</li>
    </ol>

    <p>The corresponding files stay on disk. If you also want to delete
    them, do that in your file manager — the library will treat them as
    missing on the next scan (see <a href="kb:library-maintain">Keep the
    library healthy</a>).</p>
    """,
)


LIBRARY_MAINTAIN = _wrap(
    "Keep the library healthy",
    """
    <h2>Remove missing files</h2>
    <p>If you've deleted or moved files outside the app, the library still
    knows about them and will show them as greyed-out rows. To clean up:</p>
    <ol>
      <li>Open <b>File → Remove Missing Files</b>.</li>
      <li>Confirm. The app removes every row whose file no longer exists on
      disk.</li>
    </ol>

    <h2>Rescan</h2>
    <p><b>File → Rescan Library</b> walks every saved root again. It picks
    up:</p>
    <ul>
      <li>New files added by other apps (Explorer, Finder, cp/rsync, etc.)</li>
      <li>Tag edits done in another tag editor</li>
      <li>Files whose modification time changed since the last scan</li>
    </ul>

    <h2>Watch folders</h2>
    <p>Enable <b>Settings → Library → Watch library folders for changes</b>
    to have the app detect new files within seconds of them appearing. The
    watcher coalesces rapid bursts (e.g. an album that downloads in
    parallel) into a single scan to keep the UI responsive.</p>

    <h2>Library Statistics</h2>
    <p>Open <b>Help → Library Statistics</b> for a snapshot:</p>
    <ul>
      <li>Total tracks, albums, artists, playlists</li>
      <li>Total play time</li>
      <li>Breakdown by file format</li>
      <li>Date-added trends</li>
    </ul>
    """,
)


NOW_PLAYING = _wrap(
    "Now Playing view",
    """
    <p>Open with <kbd>Ctrl+2</kbd> or by clicking the album art in the
    transport bar.</p>

    <h2>What you see</h2>
    <ul>
      <li><b>Cover art</b>, full-size, with a blurred copy filling the
      background.</li>
      <li><b>Title, Artist, Album, Year, Format strip</b> (codec,
      bitrate, sample rate, channels).</li>
      <li><b>Rating control</b> and <b>Like</b> button.</li>
      <li><b>Queue preview</b> showing the next several tracks.</li>
      <li><b>Album info</b> sourced from the same metadata providers used
      by the ripper.</li>
      <li><b>Lyrics</b> panel — synced (highlighted line) or plain
      depending on availability.</li>
    </ul>

    <h2>Lyrics</h2>
    <p>Lyrics are looked up in this order, stopping at the first hit:</p>
    <ol>
      <li>A <code>.lrc</code> file sitting next to the audio file with the
      same base name.</li>
      <li>Lyrics embedded in the file's own tags (USLT / SYLT for ID3,
      LYRICS tag for Vorbis, etc.).</li>
      <li>LRCLIB if <b>Settings → Metadata → Fetch lyrics online
      (LRCLIB)</b> is enabled.</li>
    </ol>
    <p>The in-memory lyric cache is capped to prevent runaway memory
    growth during long sessions.</p>

    <h2>Edit metadata from here</h2>
    <p>Right-click the title or album area to jump straight to the metadata
    editor for the current track.</p>
    """,
)


PLAYBACK = _wrap(
    "Playback, transport and queue",
    """
    <h2>The transport bar</h2>
    <p>Always visible at the bottom of the window. Controls:</p>
    <ul>
      <li><b>Previous / Play / Pause / Next / Stop</b></li>
      <li><b>Shuffle</b>, <b>Repeat</b> (off / all / one)</li>
      <li><b>Seek slider</b> with elapsed / remaining time</li>
      <li><b>Volume</b> slider and <b>Mute</b> toggle</li>
      <li><b>Equalizer</b> button — see <a href="kb:eq">Equalizer</a></li>
      <li><b>Cast</b> button — see <a href="kb:cast">Cast to DLNA</a></li>
      <li><b>Queue</b> button (also <kbd>Ctrl+Q</kbd>)</li>
      <li><b>Sleep timer</b> menu — 15/30/45/60 minutes or a custom
      value</li>
    </ul>

    <h2>Keyboard shortcuts</h2>
    <table>
      <tr><th>Key</th><th>Action</th></tr>
      <tr><td><kbd>Ctrl+Space</kbd></td><td>Play / Pause</td></tr>
      <tr><td><kbd>Ctrl+Left</kbd></td><td>Previous track</td></tr>
      <tr><td><kbd>Ctrl+Right</kbd></td><td>Next track</td></tr>
      <tr><td><kbd>Ctrl+Q</kbd></td><td>Show Queue</td></tr>
      <tr><td><kbd>Ctrl+F</kbd></td><td>Focus Library search</td></tr>
      <tr><td><kbd>Ctrl+L</kbd></td><td>Jump to Now Playing</td></tr>
    </table>

    <h2>Crossfade and gapless</h2>
    <p><b>Settings → Playback</b> exposes:</p>
    <ul>
      <li><b>Crossfade</b> — set 0 seconds to disable. Higher values fade
      the outgoing and incoming tracks together for that many seconds.</li>
      <li><b>Gapless playback</b> — only works when crossfade is 0. Joins
      consecutive album tracks without the brief silence that VLC inserts
      between files by default.</li>
    </ul>

    <h2>ReplayGain</h2>
    <p>Enable in <b>Settings → Playback</b> to normalise loudness using the
    standard ReplayGain tags written to your files. Modes:</p>
    <ul>
      <li><b>Off</b></li>
      <li><b>Track</b> — every track sounds at the same average loudness</li>
      <li><b>Album</b> — preserves album-internal loudness variation</li>
    </ul>
    <p>Tick <b>Prevent clipping</b> to clamp boosts so positive gain never
    pushes the signal above 0 dBFS.</p>

    <h2>Queue restore</h2>
    <p>The queue and current playback position are saved on exit. The next
    launch restores them — paused, ready to resume.</p>

    <h2>Sleep timer</h2>
    <p>Click the moon icon in the transport bar (or open the menu) and pick
    a duration. Playback fades out and pauses when the timer expires. Open
    the same menu and choose <b>Cancel Timer</b> to abort.</p>

    <h2>Media keys</h2>
    <p>Media keys (Play, Next, Previous) work on Windows automatically.
    macOS uses the optional native hook when the platform integration is
    available.</p>
    """,
)


EQ = _wrap(
    "Equalizer",
    """
    <p>The equalizer is a 10-band libVLC equalizer with a preamp slider.
    Open it from the <b>EQ</b> button in the transport bar, or via
    <b>Settings → Playback → Equalizer</b>.</p>

    <h2>Using it</h2>
    <ol>
      <li>Tick <b>Enable equalizer</b>.</li>
      <li>Drag any of the 10 frequency-band sliders (60 Hz to 16 kHz).</li>
      <li>Use the <b>Preamp</b> slider on the left to compensate for
      headroom if you've boosted bands.</li>
      <li>Pick a built-in curve from the <b>Preset</b> dropdown (Flat, Rock,
      Jazz, Classical, etc.) to start from a known shape.</li>
    </ol>

    <h2>Custom curves</h2>
    <ul>
      <li>Click <b>Save As…</b> to store your current slider positions as a
      named custom curve.</li>
      <li>Custom curves appear at the bottom of the preset list.</li>
      <li><b>Delete Curve</b> removes the currently-selected custom
      curve.</li>
      <li><b>Flat / Reset</b> instantly returns every band to 0 dB.</li>
    </ul>

    <p>The same equalizer state is applied to both music and video playback,
    so a single EQ change affects everywhere audio comes from.</p>

    <p class="warn">If the sliders move but the sound does not change,
    libVLC is not loaded. Open <a href="kb:diagnostics">Runtime
    Diagnostics</a>.</p>
    """,
)


PODCASTS = _wrap(
    "Podcasts",
    """
    <p>Open the <b>Podcasts</b> tab (<kbd>Ctrl+8</kbd>).</p>

    <h2>Subscribe</h2>
    <ul>
      <li><b>Add Feed…</b> — paste an RSS or Atom feed URL.</li>
      <li><b>Import OPML…</b> — bulk-import subscriptions exported from
      another podcast app.</li>
    </ul>

    <h2>Catalog and playback</h2>
    <ol>
      <li>The left pane lists subscribed podcasts. Pick one to see its
      episodes on the right.</li>
      <li>Episodes are searchable; the search box on top filters by title
      or description.</li>
      <li>Double-click an episode to start streaming through the standard
      audio pipeline — equalizer, ReplayGain and Cast all work on it.</li>
      <li>Refresh runs automatically in the background; right-click a
      podcast and choose <b>Refresh now</b> for an immediate update.</li>
    </ol>

    <h2>Maintenance</h2>
    <ul>
      <li><b>Mark all played</b> on a podcast or an individual episode.</li>
      <li><b>Unsubscribe</b> removes the feed and its episode list.</li>
      <li>The User-Agent sent to podcast hosts identifies the app, its
      version, and the configured MusicBrainz contact so polite hosts can
      rate-limit predictably.</li>
    </ul>
    """,
)


RADIO = _wrap(
    "Internet Radio",
    """
    <p>The <b>Radio</b> tab (<kbd>Ctrl+3</kbd>) plays live audio streams. It
    has a quick-play bar at the top and two sub-tabs below it: <b>My
    Stations</b> (your saved list) and <b>Browse</b> (an online directory).</p>

    <h2>Quick-play a stream URL</h2>
    <ol>
      <li>Paste a direct stream URL into the <b>Stream URL</b> box at the top
      and click <b>Play Stream</b> (or press Enter).</li>
      <li>Playback starts immediately. Recently played URLs are remembered and
      offered as autocomplete suggestions next time.</li>
      <li>Once a stream starts, an <b>Add to My Stations</b> prompt appears so
      you can save it permanently with one click.</li>
    </ol>

    <h2>My Stations</h2>
    <p>Your saved stations live on the <b>My Stations</b> sub-tab. The toolbar
    buttons are:</p>
    <ul>
      <li><b>Play</b> — play the selected station (or just double-click it).</li>
      <li><b>Add…</b> — add a station by hand: a name plus the direct stream
      URL (MP3 or AAC over HTTP, or a playlist URL such as <code>.pls</code> /
      <code>.m3u</code>).</li>
      <li><b>Edit…</b> — change the name or URL of the selected station.</li>
      <li><b>Import Playlist…</b> — pick an <code>.m3u</code> or
      <code>.pls</code> file; every URL inside it becomes a saved station.</li>
      <li><b>Export…</b> — write your stations out to an <code>.m3u</code> or
      <code>.pls</code> playlist for backup or sharing.</li>
      <li><b>Remove</b> — delete the selected station from the list.</li>
    </ul>
    <p>The star in the first column toggles a station as a <b>favorite</b>
    (favorites sort to the top). The table also shows Genre, Bitrate, the URL,
    and a <b>Status</b> column reporting each station's last reachability check
    (for example <code>HTTP 200</code> or <code>Connection failed</code>).</p>

    <h2>Browse the online directory</h2>
    <p>The <b>Browse</b> sub-tab searches the free
    <a href="https://www.radio-browser.info/">radio-browser.info</a> directory
    of public stations.</p>
    <ol>
      <li>Type part of a station name, and/or pick a <b>tag/genre</b> and a
      <b>country</b> from the dropdowns.</li>
      <li>Click <b>Search</b>. Matches appear with their Tags, Country,
      Bitrate and listener Votes.</li>
      <li>Select a result and click <b>Play</b> (or double-click) to listen,
      or <b>Add to My Stations</b> to save it.</li>
    </ol>

    <h2>Playback notes</h2>
    <p>Live streams cannot be seeked, so the transport bar's seek slider is
    hidden while a radio source is active. The station name shows up in the
    transport bar and the Now Playing view.</p>
    """,
)


VIDEO = _wrap(
    "Video playback",
    """
    <p>Open the <b>Video</b> tab (<kbd>Ctrl+4</kbd>). Local videos found by
    library scanning appear in the sidebar as thumbnail cards.</p>

    <h2>Controls</h2>
    <ul>
      <li><b>Open File…</b> — play any file on disk, regardless of the
      library.</li>
      <li><b>Play / Pause / Stop / Seek / Volume / Mute</b></li>
      <li><b>Speed</b> — 0.25× through 2×.</li>
      <li><b>Audio track</b> dropdown — pick from embedded audio
      tracks.</li>
      <li><b>Subtitle track</b> dropdown — switch embedded subtitles or
      load an external <code>.srt</code> via <b>Load External
      Subtitles…</b>.</li>
      <li><b>Snapshot</b> — save a PNG or JPEG still through libVLC.</li>
      <li><b>Fullscreen</b> — press <kbd>F11</kbd> or double-click the video
      surface. The OSD shows transient feedback.</li>
    </ul>

    <h2>Auto-pause on tab switch</h2>
    <p>Leaving the Video tab pauses playback automatically. Switch back to
    the Video tab to resume; the player remembers the exact position.</p>

    <h2>Equalizer</h2>
    <p>The audio equalizer applies to video too, so a single setting works
    for music and movies.</p>
    """,
)


DISC = _wrap(
    "Disc tab — Audio CD, DVD, VCD",
    """
    <p>The <b>Disc</b> tab (<kbd>Ctrl+5</kbd>) is a launcher for optical media
    on Windows and macOS. On macOS the <b>Disc</b> and <b>Rip</b> tabs appear
    only while an optical drive is attached.</p>

    <h2>Audio CD</h2>
    <ol>
      <li>Insert an audio CD.</li>
      <li>Open the Disc tab; the drive list refreshes automatically.</li>
      <li>Click <b>Read Disc</b> to populate the track list and look up
      metadata.</li>
      <li>Double-click a track, or click <b>Play All</b>, to play through
      the existing audio queue (transport bar, EQ, Cast all work).</li>
    </ol>

    <h2>DVD / VCD</h2>
    <p>Insert the disc and click <b>Open in Video Player</b>. The Video tab
    activates and libVLC opens the disc as <code>dvd:///</code> or
    <code>vcd:///</code>. Navigation menus and chapter selection use VLC's
    own keyboard shortcuts.</p>

    <h2>Eject</h2>
    <p>The <b>Eject</b> button sends an eject request to the selected drive.
    If a rip is in progress, eject waits until ripping has fully stopped to
    avoid corrupting the output file.</p>
    """,
)


RIP = _wrap(
    "Rip tab reference",
    """
    <p>For a complete walkthrough see
    <a href="kb:flow-rip-cd">From Opening the App to Ripping a CD</a>.
    This page is a per-control reference.</p>

    <h2>Toolbar</h2>
    <table>
      <tr><th>Control</th><th>Purpose</th></tr>
      <tr><td>CD Drive dropdown</td><td>Select which optical drive to use.
      Refresh Drives rescans the system for newly-attached drives.</td></tr>
      <tr><td>Read Disc</td><td>Read TOC, compute disc ID, fetch metadata
      and artwork.</td></tr>
      <tr><td>Rip CD</td><td>Start the rip with the current settings and
      metadata.</td></tr>
      <tr><td>Cancel</td><td>Stop ripping after the current sector; partial
      files are deleted.</td></tr>
    </table>

    <h2>Metadata panel</h2>
    <ul>
      <li><b>Cover art</b> — populated from CTDB, Cover Art Archive or
      TheAudioDB. Drop a new image to override.</li>
      <li><b>Artist / Album / Year / Group</b> — editable fields. Group
      becomes the Album Artist tag on the output files.</li>
      <li><b>Search Online</b> — re-query MusicBrainz/TheAudioDB with the
      current Artist + Album text.</li>
      <li><b>Clear Metadata</b> — empty the fields without re-reading the
      disc.</li>
    </ul>

    <h2>Track table</h2>
    <p>Columns: track number, title (editable), and status (Pending,
    <i>nn%</i>, Done, Done ✓ / Verified, Unverified, Failed). Right-click a
    row for additional actions.</p>

    <h2>Output path preview</h2>
    <p>The <b>Will save to:</b> label shows the exact output folder.
    Pattern: <code>&lt;music root&gt;/&lt;Artist&gt;/&lt;Year&gt; -
    &lt;Album&gt;/&lt;Track&gt; - &lt;Title&gt;.&lt;ext&gt;</code>.
    Unknown-album rips fall back to a numbered folder name so previous
    unknown-album rips are never overwritten.</p>

    <h2>Retry failed tracks</h2>
    <p>Available after a rip finishes if any track failed. Click to re-rip
    just the failures with the same settings.</p>

    <h2>Already-in-library detection</h2>
    <p>Saved disc IDs are checked when you click Read Disc. If the disc was
    already ripped, you'll see <i>"Already in library — disc ejected"</i>
    and the tray opens automatically.</p>
    """,
)


CD_METADATA = _wrap(
    "How disc metadata is resolved",
    """
    <p>When you click <b>Read Disc</b>, providers are queried in a fixed
    order. The first hit wins; later providers only fill gaps.</p>

    <ol>
      <li><b>CUETools DB (CTDB)</b> — uses the TOC checksum. Often returns
      the most accurate per-track titles for archival rips.</li>
      <li><b>MusicBrainz</b> — uses the libdiscid disc ID. Provides the
      release group, MBIDs, and links to Cover Art Archive.</li>
      <li><b>Cover Art Archive</b> — fetches the front cover for the
      MusicBrainz release.</li>
      <li><b>TheAudioDB</b> — used to enrich missing fields like genre,
      mood and biography, and as a secondary art source.</li>
    </ol>

    <h2>Provider toggles</h2>
    <p>Each provider has an on/off switch in <b>Settings → Metadata</b>.
    Turning off CUETools DB or artwork can speed up reads if you only care
    about basic tags from MusicBrainz.</p>

    <h2>Verification (AccurateRip v1)</h2>
    <p>With <b>Verify rip accuracy against CUETools DB</b> enabled and a
    FLAC output format, each finished track is recomputed and compared to
    the CTDB database. Outcomes:</p>
    <ul>
      <li><b>Done ✓</b> — bit-perfect match.</li>
      <li><b>Verified (offset)</b> — match after a small sample shift; this
      indicates your drive has a fixed read offset, not a rip error.</li>
      <li><b>Unverified</b> — no match in CTDB. This is common for obscure
      discs; it doesn't mean the rip is bad.</li>
    </ul>

    <h2>Diagnostics</h2>
    <p>Tick <b>Log detailed metadata diagnostics</b> to capture every
    request, hit and miss to <code>metadata-diagnostics.log</code> in the
    app-data folder for troubleshooting.</p>
    """,
)


YOUTUBE = _wrap(
    "YouTube search and download",
    """
    <p>The <b>YouTube</b> tab (<kbd>Ctrl+7</kbd>) uses yt-dlp's native
    search — no browser engine required.</p>

    <h2>Search</h2>
    <ol>
      <li>Type a query into the search box, press Enter.</li>
      <li>Results appear as cards with thumbnail, title, channel, view
      count and duration.</li>
      <li>Click <b>Download</b> on any card to open the download
      dialog.</li>
    </ol>

    <h2>Download dialog</h2>
    <ul>
      <li><b>Audio only</b> — FLAC or MP3 (ffmpeg is used for
      transcoding).</li>
      <li><b>Video</b> — MP4, MKV or WebM (ffmpeg merges streams when the
      best video and audio are separate).</li>
      <li><b>Playlist</b> tick-box — download every video in the URL's
      playlist instead of just the one.</li>
      <li><b>Output folder</b> — defaults to
      <code>&lt;music root&gt;/YouTube</code>; change in
      <b>Settings → YouTube</b>.</li>
      <li><b>Progress log</b> — the live yt-dlp output, including any
      warnings.</li>
    </ul>

    <h2>Automatic library import</h2>
    <p>With <b>Automatically add downloads to library</b> enabled
    (default), every completed file is indexed immediately. Audio downloads
    show up under Artists; video downloads under the Video tab's catalog
    if the destination is inside a watched library root.</p>

    <p class="warn">YouTube's terms of service govern what you may download.
    The app is provided as a tool; usage compliance is your
    responsibility.</p>
    """,
)


CAST = _wrap(
    "Cast to a DLNA / UPnP renderer",
    """
    <p>Cast lets you play through a smart TV, AV receiver or any
    DLNA/UPnP MediaRenderer on the same LAN.</p>

    <h2>How to cast</h2>
    <ol>
      <li>Click the <b>Cast</b> button in the transport bar.</li>
      <li>The Cast dialog scans the network with SSDP and lists every
      MediaRenderer it finds.</li>
      <li>Pick a target and click <b>Connect</b>.</li>
      <li>Playback transfers; the transport bar shows a "Casting to:" badge
      under the title.</li>
      <li>Pause, seek and volume continue to work — they are sent as
      AVTransport SOAP commands on a background thread, so the UI never
      stutters.</li>
      <li>Click the Cast button again and choose <b>Disconnect</b> to
      return to local playback.</li>
    </ol>

    <h2>Sharing the library over DLNA</h2>
    <p>The other direction is also supported. Enable <b>Settings → DLNA →
    Share library over DLNA / UPnP</b>. Other devices on the network can
    then browse your library as a MediaServer. The server runs on a port
    of its choice (random by default; configurable in Settings) and
    advertises via SSDP.</p>
    """,
)


SCROBBLING = _wrap(
    "Scrobbling (Last.fm and ListenBrainz)",
    """
    <p>Both services log what you listen to. Open
    <b>Settings → Scrobbling</b>.</p>

    <h2>Last.fm</h2>
    <p>Sea Lyon ships with its own Last.fm application key, so you don't need
    to create one or paste any API credentials.</p>
    <ol>
      <li>Tick <b>Enable Last.fm scrobbling</b>.</li>
      <li>Click <b>Connect Last.fm…</b>. The app gets a token, opens your
      browser, and waits for you to click <i>"Allow"</i> on the Last.fm
      authorisation page.</li>
      <li>Once authorised, the status label updates to your Last.fm
      username.</li>
      <li><b>Disconnect</b> revokes the local session (you should also
      revoke the app on the Last.fm site if you want a full sign-out).</li>
    </ol>

    <h2>ListenBrainz</h2>
    <ol>
      <li>Tick <b>Enable ListenBrainz scrobbling</b>.</li>
      <li>Click <b>Get token ↗</b> to open the ListenBrainz user
      settings.</li>
      <li>Copy your user token into the field below.</li>
    </ol>

    <h2>When a scrobble is sent</h2>
    <p>A play is scrobbled once playback has crossed the standard
    threshold — the higher of 30 seconds and 50% of the track. This matches
    the upstream rules so the numbers line up with your service profile.</p>
    """,
)


DLNA = _wrap(
    "DLNA server (share your library)",
    """
    <p>Open <b>Settings → DLNA</b> and tick <b>Share library over DLNA /
    UPnP</b>. The app starts a MediaServer that exposes your library to
    other devices on the same LAN:</p>
    <ul>
      <li>Smart TVs (Samsung, LG, Sony) with DLNA browsing</li>
      <li>Network-aware AV receivers</li>
      <li>UPnP control points (BubbleUPnP, Kodi, VLC)</li>
    </ul>

    <h2>Settings</h2>
    <ul>
      <li><b>Server name</b> — the friendly name shown to other devices
      (defaults to "Sea Lyon Media Manager").</li>
      <li><b>Port</b> — leave on <i>Auto</i> (0) to let the operating system
      pick a free port, or pin a specific port.</li>
      <li><b>Bind address</b> — <code>0.0.0.0</code> to serve the whole LAN,
      or <code>127.0.0.1</code> to restrict sharing to this computer.</li>
    </ul>

    <h2>Behaviour</h2>
    <ul>
      <li>The browse tree mirrors Artists / Albums / Genres / Playlists from
      your library.</li>
      <li>Cover art is served alongside each item.</li>
      <li>Paging is optimised so very large libraries open quickly on the
      remote device.</li>
      <li>Streams are HTTP range-aware so seeking works on the remote
      device.</li>
    </ul>

    <p class="warn">DLNA shares your music to anything on your LAN with no
    authentication, by design. Keep it disabled on untrusted networks
    (public Wi-Fi, shared offices).</p>
    """,
)


SETTINGS_LIBRARY = _wrap(
    "Settings → Library",
    """
    <ul>
      <li><b>Music folder</b> — default destination for rips and YouTube
      downloads. Browse to a folder.</li>
      <li><b>Library folders</b> — the list of indexed roots. Use Add… and
      Remove to manage them.</li>
      <li><b>Watch library folders for changes</b> — enables the recursive
      filesystem watcher so new files are picked up
      automatically.</li>
    </ul>
    """,
)


SETTINGS_PLAYBACK = _wrap(
    "Settings → Playback",
    """
    <ul>
      <li><b>Output module</b> — pick a libVLC audio output (e.g. WASAPI on
      Windows, CoreAudio on macOS). Changes take effect on the next track.</li>
      <li><b>Output device</b> — once an output is chosen, you can pick a
      specific endpoint (e.g. a particular DAC).</li>
      <li><b>ReplayGain</b> — a <b>Normalization mode</b> of Off / Track Gain /
      Album Gain, a <b>Pre-amp</b> offset (−6 to +6 dB; use a negative value to
      add headroom), and <b>Prevent clipping</b> (never boost above the
      original volume).</li>
      <li><b>Crossfade</b> — 0 to 60 seconds (0 = off).</li>
      <li><b>Gapless playback</b> — requires crossfade = 0.</li>
    </ul>
    """,
)


SETTINGS_RIPPING = _wrap(
    "Settings → CD Ripping",
    """
    <ul>
      <li><b>CD drive</b> — the drive to rip from (e.g. <code>D:</code>);
      leave blank to auto-detect.</li>
      <li><b>Output format</b> — FLAC, MP3, AAC/M4A, Opus, OGG, ALAC, WAV,
      AIFF, WMA.</li>
      <li><b>FLAC compression</b> — 0–8, default 4. Higher is smaller and
      slower; output is bit-identical at every level. (Shown only for
      FLAC.)</li>
      <li><b>Bitrate (kbps)</b> — for lossy formats: 128, 192, 256, 320 or
      512. (Shown only for lossy formats.)</li>
      <li><b>Eject disc after rip</b> — opens the tray on completion.</li>
      <li><b>Verify rip accuracy against CUETools DB</b> — FLAC only.</li>
    </ul>
    """,
)


SETTINGS_METADATA = _wrap(
    "Settings → Metadata",
    """
    <ul>
      <li><b>Look up metadata online automatically</b> — master switch.</li>
      <li><b>Use CUETools DB plugin for metadata</b> — disable to skip CTDB
      lookups for faster local-only operation.</li>
      <li><b>Download cover art</b> — fetches the front cover from CTDB,
      Cover Art Archive, or TheAudioDB.</li>
      <li><b>Log detailed metadata diagnostics</b> — writes
      <code>metadata-diagnostics.log</code> for troubleshooting provider
      issues.</li>
      <li><b>Fetch lyrics online (LRCLIB)</b> — used by
      <a href="kb:now-playing">Now Playing</a>.</li>
      <li><b>MusicBrainz Contact</b> — required by MusicBrainz access
      policy. Use your real email/website; replace the
      <code>example.invalid</code> placeholder before distributing
      builds.</li>
      <li><b>TheAudioDB API key</b> — used for TheAudioDB lookups. The free
      tier works with the default key; clear the field to disable TheAudioDB
      or replace it with your own key.</li>
    </ul>
    """,
)


SETTINGS_YOUTUBE = _wrap(
    "Settings → YouTube",
    """
    <ul>
      <li><b>Audio-only format</b> — FLAC or MP3.</li>
      <li><b>Video format (video + audio)</b> — MP4, MKV or WebM.</li>
      <li><b>Video quality</b> — Best available, 1080p, 2K (1440p) or
      4K (2160p). Requires ffmpeg to merge separate video/audio streams.</li>
      <li><b>Save folder</b> — output folder; defaults to
      <code>&lt;music root&gt;/YouTube</code>.</li>
      <li><b>Automatically add downloads to library</b> — index completed
      files immediately.</li>
    </ul>
    """,
)


SETTINGS_UPDATES = _wrap(
    "Settings → Updates",
    """
    <ul>
      <li><b>Check for updates automatically (once a day)</b> — master
      toggle. When enabled the app queries a GitHub-hosted Appcast feed in
      the background.</li>
      <li><b>Update feed URL</b> — the Appcast XML endpoint. Defaults to
      the official GitHub Pages feed; only change it if you run your own
      mirror.</li>
      <li><b>Last checked / Check now</b> — shows when the last check
      ran and lets you trigger one manually.</li>
      <li><b>Skipped version</b> — if you previously dismissed an update,
      the skipped version appears here with a <i>Stop skipping</i> button
      so future checks will surface it again.</li>
    </ul>

    <p>You can also run a check any time from <b>Help → Check for
    Updates…</b>.</p>

    <p class="tip">Update checks run off the UI thread and do not transmit
    any of your data — see PRIVACY.md for details.</p>
    """,
)


SETTINGS_ABOUT = _wrap(
    "Settings → About",
    """
    <p>The <b>About</b> tab shows:</p>
    <ul>
      <li>The app icon, name and current version number.</li>
      <li>A short product description.</li>
      <li>The copyright notice and license (MIT).</li>
      <li><b>Third-Party Acknowledgements</b> — a list of bundled or
      linked components (Python, Qt / PySide6, libVLC, ffmpeg, libdiscid,
      Chromaprint, etc.) with their respective licence identifiers.</li>
    </ul>
    """,
)


DIAGNOSTICS = _wrap(
    "Runtime Diagnostics",
    """
    <p>Open <b>Help → Runtime Diagnostics</b>. The dialog runs a series of
    dependency checks and shows each result in a table.</p>

    <table>
      <tr><th>Component</th><th>What it checks</th></tr>
      <tr><td>Python packages</td><td>PySide6, mutagen, requests,
      python-vlc, discid, yt-dlp, watchdog and friends.</td></tr>
      <tr><td>VLC / libVLC</td><td>Whether <code>libvlc.dll</code> (or the
      platform equivalent) can be loaded. Required for audio and video
      playback.</td></tr>
      <tr><td>ffmpeg</td><td>Whether <code>ffmpeg.exe</code> is reachable on
      PATH or under <code>bin/</code>. Required for ripping, YouTube
      transcoding and snapshot encoding.</td></tr>
      <tr><td>libdiscid</td><td>Required for MusicBrainz disc IDs (Windows
      CD ripping).</td></tr>
    </table>

    <h2>Status meanings</h2>
    <ul>
      <li><b>OK</b> (green) — feature is fully available.</li>
      <li><b>WARNING</b> (yellow) — feature works but a non-critical
      enhancement is missing (for example, optional libcdio support inside
      ffmpeg).</li>
      <li><b>MISSING</b> (red) — feature is unavailable. The <i>How to
      fix</i> column tells you which file to provide.</li>
    </ul>

    <h2>Common fixes (Windows / source checkouts)</h2>
    <ul>
      <li>Place <code>ffmpeg.exe</code> in <code>bin/</code> at the repo
      root, or install ffmpeg system-wide.</li>
      <li>Place <code>discid.dll</code> in <code>bin/</code>.</li>
      <li>Place a 64-bit VLC runtime under <code>bin/vlc/</code> including
      <code>libvlc.dll</code>, <code>libvlccore.dll</code> and the
      <code>plugins/</code> folder.</li>
    </ul>
    <p class="tip">The installed macOS app bundles ffmpeg, libVLC and
    libdiscid inside the <code>.app</code>, so these rarely show as missing
    there. From a macOS source checkout, put the macOS equivalents (ffmpeg,
    fpcalc, libdiscid) in <code>bin/</code>.</p>

    <h2>More Help-menu tools</h2>
    <ul>
      <li><b>Help → Open Log Folder</b> — opens the folder holding the
      rotating application logs.</li>
      <li><b>Help → Copy Diagnostics to Clipboard</b> — copies a full
      environment and dependency report you can paste into a bug report.</li>
    </ul>
    """,
)


SHORTCUTS = _wrap(
    "Keyboard shortcuts",
    """
    <h2>Tabs</h2>
    <table>
      <tr><th>Shortcut</th><th>Tab</th></tr>
      <tr><td><kbd>Ctrl+1</kbd></td><td>Library</td></tr>
      <tr><td><kbd>Ctrl+2</kbd></td><td>Now Playing</td></tr>
      <tr><td><kbd>Ctrl+3</kbd></td><td>Radio</td></tr>
      <tr><td><kbd>Ctrl+4</kbd></td><td>Video</td></tr>
      <tr><td><kbd>Ctrl+5</kbd></td><td>Disc</td></tr>
      <tr><td><kbd>Ctrl+6</kbd></td><td>Rip</td></tr>
      <tr><td><kbd>Ctrl+7</kbd></td><td>YouTube</td></tr>
      <tr><td><kbd>Ctrl+8</kbd></td><td>Podcasts</td></tr>
    </table>

    <h2>Playback</h2>
    <table>
      <tr><th>Shortcut</th><th>Action</th></tr>
      <tr><td><kbd>Ctrl+Space</kbd></td><td>Play / Pause</td></tr>
      <tr><td><kbd>Ctrl+Left</kbd></td><td>Previous track</td></tr>
      <tr><td><kbd>Ctrl+Right</kbd></td><td>Next track</td></tr>
      <tr><td><kbd>Ctrl+Q</kbd></td><td>Show Queue</td></tr>
      <tr><td><kbd>Ctrl+L</kbd></td><td>Jump to Now Playing</td></tr>
      <tr><td><kbd>Ctrl+F</kbd></td><td>Focus Library search</td></tr>
    </table>

    <h2>Video tab</h2>
    <table>
      <tr><th>Shortcut</th><th>Action</th></tr>
      <tr><td><kbd>F11</kbd></td><td>Toggle fullscreen</td></tr>
      <tr><td><kbd>Space</kbd></td><td>Play / Pause</td></tr>
      <tr><td><kbd>Esc</kbd></td><td>Exit fullscreen</td></tr>
    </table>

    <h2>Help</h2>
    <table>
      <tr><th>Shortcut</th><th>Action</th></tr>
      <tr><td><kbd>F1</kbd></td><td>Open the Knowledge Base</td></tr>
    </table>
    """,
)


DATA_LOCATIONS = _wrap(
    "Where your data lives",
    """
    <p>User data is stored outside the application folder so updates and
    reinstalls don't lose it.</p>

    <table>
      <tr><th>Platform</th><th>Folder</th></tr>
      <tr><td>Windows</td><td><code>%APPDATA%\\LyonMusicManager\\</code></td></tr>
      <tr><td>macOS</td>
          <td><code>~/Library/Application Support/LyonMusicManager/</code></td></tr>
      <tr><td>Linux</td>
          <td><code>$XDG_CONFIG_HOME/LyonMusicManager/</code> or
          <code>~/.config/LyonMusicManager/</code></td></tr>
    </table>

    <h2>Files inside it</h2>
    <ul>
      <li><b>settings.json</b> — every preference you set in the Settings
      dialog.</li>
      <li><b>library.db</b> — SQLite media index. Includes tracks, ratings,
      play counts, playlists and smart-playlist rules.</li>
      <li><b>metadata-diagnostics.log</b> — created only when
      <i>Log detailed metadata diagnostics</i> is enabled.</li>
    </ul>

    <h2>Default output folders</h2>
    <ul>
      <li><b>Ripped CDs</b> →
      <code>&lt;music root&gt;/&lt;Artist&gt;/&lt;Year&gt; -
      &lt;Album&gt;/&lt;Track&gt; - &lt;Title&gt;.&lt;ext&gt;</code></li>
      <li><b>YouTube</b> → <code>&lt;music root&gt;/YouTube/</code></li>
    </ul>

    <p>Back up <code>library.db</code> and <code>settings.json</code> if you
    want to preserve playlists and ratings across reinstalls.</p>
    """,
)


TROUBLESHOOT = _wrap(
    "Troubleshooting",
    """
    <h2>Audio playback is unavailable</h2>
    <p>Open <a href="kb:diagnostics">Runtime Diagnostics</a>. Check
    <code>python-vlc</code> is installed and that a 64-bit VLC runtime is
    discoverable or present under <code>bin/vlc/</code>.</p>

    <h2>Video player shows "Video playback unavailable"</h2>
    <p>Same root cause as audio. Fix VLC/libVLC and both come back.</p>

    <h2>Equalizer sliders move but sound doesn't change</h2>
    <p>The audible EQ requires libVLC. Run diagnostics.</p>

    <h2>"ffmpeg not found" while ripping or downloading audio</h2>
    <p>Place <code>bin/ffmpeg.exe</code> in the repo root, or install
    ffmpeg on PATH.</p>

    <h2>No CD drive appears</h2>
    <p>CD ripping works on Windows and macOS with an attached optical drive.
    On Windows, confirm the drive shows in File Explorer; on macOS the
    <b>Disc</b> and <b>Rip</b> tabs only appear once an optical drive is
    connected. Either way an audio CD must be inserted — data discs don't
    show up.</p>

    <h2>Disc metadata doesn't resolve</h2>
    <p>Keep CUETools DB metadata lookup enabled, confirm internet access,
    and set a real <b>MusicBrainz Contact</b> value before heavy lookup
    use.</p>

    <h2>YouTube search or download fails</h2>
    <p>Confirm <code>yt-dlp</code> is installed in the active environment.
    ffmpeg is also needed for high-quality video merging and audio
    conversion.</p>

    <h2>Built ZIP fails on another machine</h2>
    <p>Distribute the complete generated folder or zip, not just
    <code>LyonMusicManager.exe</code>.</p>
    """,
)


# Tree: (slug, title, children)
TREE = [
    ("welcome", "Welcome", WELCOME, []),
    ("flow-rip-cd", "Walkthrough — Open app → Rip a CD", FLOW_RIP_CD, []),
    ("library", "Library Management", LIBRARY_OVERVIEW, [
        ("library-add", "Add music", LIBRARY_ADD, []),
        ("library-browse", "Browse and search", LIBRARY_BROWSE, []),
        ("library-play", "Play tracks", LIBRARY_PLAY, []),
        ("library-playlists", "Manual playlists", LIBRARY_PLAYLISTS, []),
        ("library-smart", "Smart playlists", LIBRARY_SMART, []),
        ("library-rate", "Ratings & collections", LIBRARY_RATE, []),
        ("library-edit", "Edit metadata", LIBRARY_EDIT, []),
        ("library-fetch", "Fetch from MusicBrainz", LIBRARY_FETCH, []),
        ("library-dupes", "Find duplicates", LIBRARY_DUPES, []),
        ("library-maintain", "Maintenance", LIBRARY_MAINTAIN, []),
    ]),
    ("playback", "Music Playback", PLAYBACK, [
        ("now-playing", "Now Playing", NOW_PLAYING, []),
        ("eq", "Equalizer", EQ, []),
        ("cast", "Cast to DLNA", CAST, []),
        ("scrobbling", "Scrobbling", SCROBBLING, []),
    ]),
    ("podcasts", "Podcasts", PODCASTS, []),
    ("radio", "Internet Radio", RADIO, []),
    ("video", "Video", VIDEO, []),
    ("disc", "Disc tab", DISC, []),
    ("rip", "Rip tab reference", RIP, [
        ("cd-metadata", "Disc metadata providers", CD_METADATA, []),
    ]),
    ("youtube", "YouTube", YOUTUBE, []),
    ("dlna", "DLNA server", DLNA, []),
    ("settings", "Settings reference", _wrap(
        "Settings reference",
        "<p>The <b>Settings</b> dialog is organised into tabs. Each tab is "
        "described in its own page:</p>"
        "<ul>"
        "<li><a href='kb:settings-library'>Library</a></li>"
        "<li><a href='kb:settings-playback'>Playback</a></li>"
        "<li><a href='kb:settings-ripping'>CD Ripping</a></li>"
        "<li><a href='kb:settings-metadata'>Metadata</a></li>"
        "<li><a href='kb:settings-youtube'>YouTube</a></li>"
        "<li><a href='kb:scrobbling'>Scrobbling</a></li>"
        "<li><a href='kb:dlna'>DLNA</a></li>"
        "<li><a href='kb:settings-updates'>Updates</a></li>"
        "<li><a href='kb:settings-about'>About</a></li>"
        "</ul>"), [
        ("settings-library", "Library tab", SETTINGS_LIBRARY, []),
        ("settings-playback", "Playback tab", SETTINGS_PLAYBACK, []),
        ("settings-ripping", "CD Ripping tab", SETTINGS_RIPPING, []),
        ("settings-metadata", "Metadata tab", SETTINGS_METADATA, []),
        ("settings-youtube", "YouTube tab", SETTINGS_YOUTUBE, []),
        ("settings-updates", "Updates tab", SETTINGS_UPDATES, []),
        ("settings-about", "About tab", SETTINGS_ABOUT, []),
    ]),
    ("shortcuts", "Keyboard shortcuts", SHORTCUTS, []),
    ("diagnostics", "Runtime Diagnostics", DIAGNOSTICS, []),
    ("data", "Where your data lives", DATA_LOCATIONS, []),
    ("troubleshoot", "Troubleshooting", TROUBLESHOOT, []),
]


class KnowledgeBaseDialog(QDialog):
    """A two-pane help browser: navigation tree on the left, content on the right."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{__app_name__} — Knowledge Base")
        self.resize(1100, 720)

        self._pages: dict[str, str] = {}
        self._items: dict[str, QTreeWidgetItem] = {}

        # ---- left pane: search + tree
        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search topics…")
        self.search.textChanged.connect(self._filter_tree)
        left_layout.addWidget(self.search)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        font = self.tree.font()
        if isinstance(font, QFont):
            font.setPointSize(max(font.pointSize(), 10))
            self.tree.setFont(font)
        self.tree.currentItemChanged.connect(self._on_tree_changed)
        left_layout.addWidget(self.tree, 1)

        # ---- right pane: content browser
        self.browser = QTextBrowser(self)
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.anchorClicked.connect(self._on_anchor)
        self.browser.document().setDocumentMargin(18)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(left)
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 800])

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addWidget(buttons)

        self._populate_tree()
        first = self.tree.topLevelItem(0)
        if first is not None:
            self.tree.setCurrentItem(first)

    # ------------------------------------------------------------------ tree

    def _populate_tree(self) -> None:
        for slug, title, body, children in TREE:
            item = self._make_item(slug, title, body)
            self.tree.addTopLevelItem(item)
            for cslug, ctitle, cbody, _ in children:
                citem = self._make_item(cslug, ctitle, cbody)
                item.addChild(citem)
            item.setExpanded(True)

    def _make_item(self, slug: str, title: str, body: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([title])
        item.setData(0, Qt.UserRole, slug)
        self._pages[slug] = body
        self._items[slug] = item
        return item

    def _on_tree_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is None:
            return
        slug = current.data(0, Qt.UserRole)
        body = self._pages.get(slug)
        if body is not None:
            self.browser.setHtml(body)
            self.browser.verticalScrollBar().setValue(0)

    # ------------------------------------------------------------------ search

    def _filter_tree(self, text: str) -> None:
        needle = text.strip().lower()

        def walk(item: QTreeWidgetItem) -> bool:
            label = item.text(0).lower()
            slug = item.data(0, Qt.UserRole)
            body = self._pages.get(slug, "").lower()
            self_match = (not needle) or (needle in label) or (needle in body)
            child_match = False
            for i in range(item.childCount()):
                if walk(item.child(i)):
                    child_match = True
            visible = self_match or child_match
            item.setHidden(not visible)
            if needle and child_match:
                item.setExpanded(True)
            return visible

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    # ------------------------------------------------------------------ links

    def _on_anchor(self, url) -> None:
        scheme = url.scheme()
        if scheme == "kb":
            self._navigate(url.path() or url.toString().split(":", 1)[1])
            return
        # external link — open in browser
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(url)

    def _navigate(self, slug: str) -> None:
        item = self._items.get(slug)
        if item is not None:
            self.tree.setCurrentItem(item)
