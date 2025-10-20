# advanced_audio_player.py — Developer Documentation

This document describes the Advanced Audio Player implementation located at:
https://github.com/EcoG-One/Web-Media-Server-and-Player/blob/03766993ce22c27e39a6986ce0ba49c1478e2ba9/advanced_audio_player.py

Contents
- Overview
- How to run
- High-level architecture & threading model
- Main classes and important methods
- Database layout
- Expected remote API endpoints
- Settings, configuration and environment
- Dependencies
- Notable behaviors and UX details
- Known issues / bugs / risky patterns (actionable)
- Suggested improvements / TODOs
- Testing notes

---

## Overview

advanced_audio_player.py is a PySide6-based desktop audio player and client for a web media server. It supports:
- Local and remote playback (local files or streamed from an API server)
- Library scanning and storage into an SQLite DB
- Playlists (m3u, cue, json)
- Crossfade / mixing modes
- Gap killer / silence detection (experimental)
- Metadata extraction (mutagen) and lyrics loading
- Asynchronous interactions with a remote server using a Worker (QThread + asyncio + aiohttp)
- UI: search, playlists pane, metadata pane, album art and lyrics display

The main GUI class is AudioPlayer. A lightweight Worker class runs async HTTP interactions off the UI thread. Lyrics support is provided by SynchronizedLyrics and LyricsDisplay.

---

## How to run

Requires Python 3.8+ (PySide6 uses 3.8+), run as a normal Qt app:

1. Install dependencies (see Dependencies section).
2. Ensure `static/images/favicon.ico` and other static images exist (or adapt UI code).
3. Run:
   python advanced_audio_player.py

The app persists settings to `~/Web-Media-Server-and-Player/settings.json` and stores the local DB at `~/Web-Media-Server-and-Player/music.db`.

---

## High-level architecture & threading model

- UI runs on the main Qt thread (AudioPlayer instance).
- Long-running or network tasks run in Worker (subclass of QThread). Worker uses asyncio with an event loop created inside run().
- Worker communicates back via Qt Signals:
  - work_completed (dict)
  - work_error (str)
- UI uses QProgressBar in the status bar to indicate indeterminate operations.
- QMediaPlayer instances are used for playback. For crossfading the code creates a second QMediaPlayer (`next_player`) and QAudioOutput (`next_output`) and adjusts volumes.

---

## Main classes

### AudioPlayer (QWidget)
Primary GUI + player logic. Important attributes:
- player: QMediaPlayer (currently active)
- audio_output: QAudioOutput (for player)
- next_player / next_output: used for crossfade
- playlist: list of ListItem objects
- current_index: int
- meta_data: dict for current track metadata
- server, api_url, remote_base: server string and URL for remote interactions
- songs_worker, search_worker, playlists_worker, meta_worker, scan_worker, purge_worker, pl_worker, server_worker: Worker instances used for background tasks
- progress: QProgressBar shown when background tasks are running
- lyrics_timer: QTimer to periodically update lyrics render

Important methods (non-exhaustive):
- init_database() — creates Songs and Playlists tables in SQLite DB
- scan_for_audio_files(directory) — recursive walk for audio & playlists
- add_songs_to_database(audio_files)
- add_playlists_to_database(playlist_files)
- scan_library(), purge_library() — UI flows that call Worker or local functions
- search_tracks(column, query) — local (DB) or remote search
- get_audio_metadata(file_path) — extracts metadata (mutagen) and computes transition duration via librosa
- detect_low_intensity_segments(audio_path, threshold_db, frame_duration) — uses librosa to inspect last 10s for low-intensity and determines transition_duration
- load_track(idx) — setSource on player and play
- start_fade_to_next(mode) — sets up second player and QTimer for fade steps
- add_files(files), add_albums(albums), add_album(data) — add items to playlist and UI
- parse_playlist_file, load_m3u_playlist, load_cue_playlist, load_json_playlist — playlist parsing
- get_local, get_list, get_playlists, receive_list, receive_playlists — list and playlist retrieval logic
- reveal_path, reveal_current — reveal in file manager (local) or trigger remote 'start' endpoint
- many UI helper functions (update_slider, update_metadata, set_album_art, get_info, get_wiki_summary etc.)

Signals defined on class:
- request_search: Signal(str, str)
- request_reveal: Signal(ListItem)

### Worker (QThread)
A generic worker that runs an asyncio event loop in the thread and performs one of many async tasks depending on `folder_path` and `api_url`.

Constructor:
- Worker(folder_path, api_url)

run() checks parameters and calls appropriate async coroutine:
- scan_library_async()
- purge_library_async()
- search_async()
- get_playlists_async()
- get_songs_async()
- get_pl_async()
- get_metadata_async()
- check_server_async()
- reveal_remote_song_async()

Each coroutine uses aiohttp to call remote endpoints.

Worker uses a QMutex (`self.mutex`) that the AudioPlayer locks after starting threads and expects Worker to unlock on completion.

Signals:
- work_completed (dict)
- work_error (str)

### ListItem
Lightweight container used to represent songs, playlists, albums, or covers in the playlist array. Attributes:
- is_remote: bool
- item_type: string (or Enum usage in some places; see known issues)
- display_text: label text used in QListWidget
- route, path, server: used to construct remote URL

Method:
- absolute_path() → QUrl (returns http URL for remote items, local file URL otherwise)

### ItemType (Enum)
Enum for item categories: PLAYLIST, SONG, ARTIST, ALBUM, COVER, DIRECTORY. There is a method defined named set_item_type which is not a proper instance/class method (see Known Issues).

### SynchronizedLyrics
Reads lyrics text (from w.meta_data) and parses LRC-style time tags into (times, lines). Provides:
- parse_lyrics(lyrics_text)
- get_current_line(pos_ms)
- is_synchronized()

### LyricsDisplay (QTextEdit)
Displays lyrics and highlights a line if lyrics are synchronized.

### TextEdit (simple QWidget)
Used to show the "Instructions" window with large static text.

---

## Database layout

SQLite DB at: ~/Web-Media-Server-and-Player/music.db

Tables:

Songs
- id INTEGER PRIMARY KEY AUTOINCREMENT
- path CHAR(255) NOT NULL
- file_name CHAR(120) NOT NULL
- artist CHAR(120) NOT NULL
- song_title CHAR(120) NOT NULL
- duration INT NOT NULL
- album CHAR(120)
- year SMALLINT

Playlists
- id INTEGER PRIMARY KEY AUTOINCREMENT
- path CHAR(255) NOT NULL
- PL_name CHAR(120) NOT NULL

Note: Some columns are defined as CHAR(255) — OK for SQLite (maps to TEXT), but consider using TEXT for clarity.

---

## Expected remote server API endpoints

Worker expects these endpoints on the remote server (api_url is usually "http://<host>:5000"):

- GET /get_playlists
  - Returns JSON list of playlists (used in get_playlists)
- GET /get_all?query={song_title|artist|album}
  - Returns JSON array for requested list
- GET /search_songs?column={column}&query={q}
  - Search endpoint returning search results (used in search_tracks)
- POST /scan_library
  - Accepts JSON {"folder_path": "<path>"} and returns status JSON
- POST /purge_library
  - Accepts JSON {"folder_path": "<path>"}
- GET /load_playlist/{playlist_id} or similar
  - Returns playlist data
- GET /get_song_metadata/{path}
  - Return metadata JSON for a remote path
- POST /start
  - Accepts JSON telling the server to reveal a file (reveal_remote_song_async sends folder_path as JSON)
- POST /web_ui, POST /desk_ui — used to launch the server UI or desktop UI remotely
- POST /shutdown — requires header X-API-Key with SHUTDOWN_SECRET value

Note: Worker uses the `api_url` attribute differently across calls — some methods pass `self.api_url` as a full URL, other code constructs URLs by formatting paths onto `self.api_url`. See Known Issues.

---

## Settings and environment

- Settings file: ~/Web-Media-Server-and-Player/settings.json
  - keys used: server, mix_method, transition_duration, gap_enabled, silence_threshold_db, silence_min_duration
- Environment variable: SHUTDOWN_SECRET (read via python-dotenv)
  - Used when calling server shutdown endpoints to authorize the request

---

## Dependencies

Key Python dependencies imported in file:
- PySide6 (Qt for Python)
- mutagen (audio metadata)
- librosa, numpy (audio analysis for silence/transition detection)
- fuzzywuzzy (string fuzzy matching)
- aiohttp (async HTTP client)
- requests (sync HTTP for some calls)
- wikipedia (fetch summaries)
- get_lyrics.LyricsPlugin (custom plugin)
- python-dotenv (load SHUTDOWN_SECRET)
- charset_normalizer (optional fallback for playlist encoding guesses)

Make sure these are installed in your environment; librosa also brings its own heavy deps.

---

## Notable behaviors / UX details

- When searching locally the DB is queried; if exact LIKE returns no rows a fuzzy attempt is performed with fuzzywuzzy on the column values.
- Crossfading: the AudioPlayer creates a second QMediaPlayer and animates volumes in a QTimer loop, supporting modes: Auto, Fade, Smooth, Full, Scratch.
- Lyrics: lyrics can be embedded in tags or fetched via LyricsPlugin; synchronized LRC files (.lrc) are supported.
- Gap-killer: experimental. The code contains two approaches:
  - A _probe_buffer implementation that expects a QAudioBuffer-like object (unused in current build) — some parts commented out and reliant on buffer callbacks that are disabled.
  - librosa-based detection used to estimate transition_duration by looking at low intensity segments in the last 10s.
- Many background operations display an indeterminate progress bar in the status bar.

---

## Known issues / risky patterns (actionable)

I tested the code statically and identified several problems or risky patterns you should be aware of:

1. ItemType.set_item_type signature / usage
   - Defined as:
     def set_item_type(item_type):
         if not isinstance(item_type, ItemType):
             raise ValueError("Invalid status value")
         w.status_bar.showMessage(f"Status set to: {item_type.value}")
   - This is defined as a plain function in the Enum body (no @staticmethod) and not used consistently. Might be intended as a helper but violates typical Enum patterns.

2. ListItem.item_type default and inconsistent types
   - ListItem.__init__ sets self.item_type = ItemType (the class), not a value like ItemType.SONG or a string.
   - Many parts of the code set item_type to string values ('song_title', 'playlist') and compare to strings, e.g. file.item_type != 'song_title'.
   - Mixing Enum class and strings is error-prone. Choose one representation and standardize (prefer strings or enum members everywhere).

3. is_remote_file and is_local_file misuse / type confusion
   - is_remote_file(self, path): returns path.is_remote — but `path` is often a string (path) or ListItem. This method expects a ListItem but name suggests path string.
   - is_local_file(self, path): calls os.path.isfile(path) but many callers pass ListItem objects or other types.
   - Multiple call sites assume `path` parameter could be a ListItem or string. Standardize signatures and naming to avoid runtime attribute errors.

4. Worker.check_server_async & "api_url" handling
   - In Worker.check_server_async:
     async with session.get(f'http://{self.api_url}:5000', timeout=3) as response:
   - But Worker was often created with api_url = self.api_url (which already has "http://server:5000") or just the base. This can produce malformed URLs like `http://http://host:5000:5000`. This inconsistency across code is risky. The code frequently mixes raw host, fully qualified base urls and endpoint paths. Normalize to a single representation (either keep host only or full base URL).

5. Worker unlocking and exception handling
   - The Worker.run catches exceptions, emits work_error and then `loop.close()` and `self.mutex.unlock()` — but unlock occurs both on success and in exception code paths in the calling code. Some code unlocks mutex in on_xxx callbacks. Ensure mutex is always unlocked exactly once. The current pattern risks leaving the mutex locked on some error paths or unlocking an unlocked mutex.

6. QThread + asyncio mixture
   - Worker.run creates a new event loop and runs synchronous loop.run_until_complete(coroutine). This approach is OK but be careful: if aiohttp session requires closed handling in exceptions, ensure loops and sessions are always closed. Worker sometimes calls loop.close() inside exception branch where loop might not be defined (if exception raised before loop assigned). Current code defines loop before try in run() so likely OK, but still check for robust cleanup.

7. get_audio_metadata uses librosa to load audio files for transition detection
   - librosa.load can be slow and memory-heavy for large libraries. Doing it for every track in a large scan will be very expensive. Currently detect_low_intensity_segments is used per-song when extracting metadata; consider making it optional or asynchronous.

8. UI threading / QObjects moved across threads
   - Worker emits signals which are connected to UI; that's correct. However, some code (e.g., self.server_worker.deleteLater()) is called in UI thread context — ok if cleanup is on main thread. Ensure objects created on main thread are not deleted from other threads.

9. Unsafe file operations and encoding assumptions
   - Playlist parsing tries several encodings; good. But some exceptions use QMessageBox inside background tasks — calling modal dialogs from background thread is unsafe. Many Worker.fetch results are handled correctly on main thread, but some errors in local scanning still use QMessageBox inside scan_for_audio_files which is called from main thread — okay.

10. reveal_remote_song_async and reveal_path
    - Worker sends `self.folder_path` as JSON; ensure the server endpoint knows the structure. reveal_path expects `work_completed` to send dict with `answer`. Check server implementation.

11. Numerous silent except: pass
    - Some exception handlers swallow errors (e.g., _probe_buffer_old's except Exception: pass). This makes debugging difficult. Log errors to status bar or file.

12. Use of global `w`
    - SynchronizedLyrics references `w` (global instance of AudioPlayer) which is created in __main__ as `w = AudioPlayer(settings)`. Relying on a module-global `w` tightly couples code and makes unit testing harder. Better to pass references.

13. Unsafe string formatting of shell commands in reveal_path:
    - On non-Windows platforms the code runs os.system(f'xdg-open "{os.path.dirname(song.path)}"') — safe for normal paths but consider shlex.quote for safety.

14. Inconsistent returns and signal payloads
    - Some Worker coroutines return different dict shapes; UI expects specific keys (e.g., 'retrieved', 'search_result', 'pl', etc.). Keep a clear contract.

15. UI repetition and code duplication
    - There are many repeated snippets that create progress bars, set styling, add to status bar; these could be factored into helper functions to reduce duplication.

---

## Suggested improvements / TODOs

- Standardize item_type: use an Enum (ItemType) consistently or plain strings. Update all comparisons accordingly.
- Normalize remote URL handling:
  - Decide: Worker.api_url should be a base URL (e.g., "http://host:5000") and never include protocol duplication. Update Worker.check_server_async and other URL builders to use urllib.parse.urljoin or pathlib-like join.
- Make Worker behavior more explicit:
  - Replace the cryptic `folder_path` polymorphism with explicit `mode` parameter or different Worker subclasses (e.g., ScanWorker, SearchWorker). This improves readability and reduces branch complexity in run().
- Replace fuzzywuzzy with rapidfuzz (fuzzywuzzy is unmaintained; rapidfuzz is faster and pure-Python).
- Avoid synchronous requests (requests) from main thread — use Worker for HTTP where feasible.
- Improve error logging: add a logger and write to a rotating file rather than putting everything into the status bar.
- Make heavy audio analysis optional (config flag) and/or perform in a separate worker
- Avoid global `w`. Instance references should be passed to classes like SynchronizedLyrics or LyricsPlugin.
- Use pathlib.Path consistently instead of mixing str paths and Path objects.
- Replace os.system with subprocess.run and shlex.quote for security and correctness.
- Add unit tests for:
  - Playlist parsing with various encodings
  - get_audio_metadata on small test files
  - Worker URL building with mocked aiohttp

---

## Example usage flows

- Scan local library:
  - Local → Scan Library → pick folder → scan_for_audio_files + add_songs_to_database + add_playlists_to_database
- Connect to remote:
  - Remote → Connect to Remote → enter host/IP → enter_server() uses Worker('server', server) to validate server (note: server vs api_url handling inconsistency may break)
- Play a local file:
  - Drag-and-drop a file into the playlist widget or File → Open Playlist | Add Songs → select files → add_files([...]) → load_track(0)
- Crossfade:
  - Set Mix Method and Transition time → player will detect transition time and call start_fade_to_next when near end

---

## Testing notes

- Because the code relies on QMediaPlayer and QAudioOutput, many playback behaviors are platform-dependent (backend codecs) and will need integration/manual testing on target systems.
- For unit tests, extract pure logic into separate modules (e.g., playlist parser, metadata extractor) to make them testable without Qt.
- Worker coroutines can be tested by running an asyncio event loop and using aiohttp test server or mocking session.get/post.

---

## Final notes

This file is a functional, feature-rich desktop player with remote-server integration. It combines a variety of libraries (mutagen, librosa, aiohttp) and GUI concepts (threads, signals, QMediaPlayer). It will benefit from refactoring to reduce polymorphism (folder_path used as a multi-purpose parameter), clarifying remote URL handling, and standardizing types for playlist items.

If you want, I can:
- produce a refactor plan (small incremental PRs) to address the top issues above, or
- create a cleaned-up, type-annotated version of Worker with explicit worker subclasses, or
- generate unit-test scaffolding for playlist parsing and metadata extraction.

Which would you prefer next?