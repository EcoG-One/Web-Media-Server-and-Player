"""
This module implements a media player application with a graphical user
interface (GUI) using PySide6. It supports local and remote media playback,
playlist management, lyrics synchronization, and various audio mixing options.
The application also includes a welcome wizard for first-time setup and
a variety of user-configurable settings.

Dependencies:
- PySide6: For GUI components and multimedia handling.
- sqlite3: For local database management.
- qdarkstyle: For dark and light themes.
- librosa, numpy: For audio processing.
- aiohttp, requests: For asynchronous and synchronous HTTP requests.
- wikipedia: For fetching song/artist information.
- dotenv: For environment variable management.
- fuzzywuzzy: For string matching.
- vlc: Optional dependency for VLC fallback playback.

Classes:
- `WelcomeWizard`: Implements a multi-step setup wizard for the application.
- `AudioPlayer`: The main application class, handling the GUI and media playback.
- `LocalMetaWorker`: A worker thread for extracting metadata from local audio files.
- `Worker`: A generic worker thread for asynchronous operations.
- `SynchronizedLyrics`: Handles synchronized lyrics parsing and display.
- `LyricsDisplay`: A custom QTextEdit widget for displaying lyrics.
- `TextEdit`: A placeholder class for additional text editing functionality.

Functions:
- `qt_message_handler`: Custom handler for Qt messages.
- `log_player_action`, `log_worker_action`: Logging utilities for debugging.
- `load_json`, `save_json`: Utilities for reading and writing JSON files.
- `get_settings`: Loads application settings from a JSON file.

Constants:
- `APP_DIR`: The application directory for storing settings and databases.
- `SETTINGS_FILE`: Path to the settings JSON file.
- `DB_PATH`, `COVERS_DB_PATH`: Paths to the music and covers databases.
- `audio_extensions`: Supported audio file extensions.
- `problematic_exts`: Extensions requiring VLC fallback.
- `playlist_extensions`: Supported playlist file extensions.

Entry Point:
- The `main` block initializes the application, loads settings, and starts
the `AudioPlayer` GUI.
"""

import asyncio
import base64
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from enum import Enum
from pathlib import Path
from random import shuffle
import aiohttp
import librosa
import numpy as np
import qdarkstyle
import requests
import wikipedia
from dotenv import load_dotenv
from fuzzywuzzy import fuzz
from mediafile import MediaFile
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from PySide6.QtCore import (QEvent, QMutex, QRect, QSize, Qt, QThread, QTimer,
                            QUrl, Signal, Slot, qInstallMessageHandler)
from PySide6.QtGui import (QAction, QIcon, QImage, QKeyEvent, QKeySequence,
                           QPixmap, QTextCursor)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QFileDialog, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QMenuBar,
                               QMessageBox, QProgressBar, QPushButton,
                               QSizePolicy, QSlider, QSpinBox, QStatusBar,
                               QStyle, QTextEdit, QToolBar, QVBoxLayout,
                               QWidget, QWidgetAction)
from qdarkstyle import DarkPalette, LightPalette
import platform
from get_lyrics import LyricsPlugin
from scanworker import ScanWorker
from text import text_1, text_2, text_3, text_4, text_5, text_6, text_7, text_8

# Attempt to import VLC as an optional dependency for fallback playback
try:
    import vlc  # python-vlc wrapper

    HAVE_VLC = True
except Exception:
    vlc = None
    HAVE_VLC = False

# Import the VLC fallback wrapper
from vlc_fallback import VlcFallbackPlayer, HAVE_VLC as VLC_AVAILABLE

# Load environment variables from a .env file
load_dotenv()
SHUTDOWN_SECRET = os.getenv("SHUTDOWN_SECRET")

# Define application directories and file paths
APP_DIR = Path.home() / "Web-Media-Server-and-Player"
APP_DIR.mkdir(exist_ok=True)
SETTINGS_FILE = APP_DIR / "settings.json"
DB_PATH = APP_DIR / "music.db"
COVERS_DB_PATH = APP_DIR / "covers.db"

# Supported audio file extensions
audio_extensions = {
    ".mp3",
    ".flac",
    ".wav",
    ".ape",
    ".ogg",
    ".m4a",
    ".aac",
    ".wma",
    ".wv",
    ".tta",
    ".tak",
    ".ofr",
    ".ofs",
    ".shn",
    ".mpp",
    ".mpc",
}

# Extensions known to cause backend issues (use VLC fallback)
problematic_exts = {
    ".ape",
    ".wv",
    ".tta",
    ".tak",
    ".ofr",
    ".ofs",
    ".shn",
    ".mpp",
    ".mpc",
}

# Supported playlist file extensions
playlist_extensions = {".m3u", ".m3u8", ".cue", ".json"}

# Additional utility functions and classes are defined below.

def qt_message_handler(msg_type, context, message):
    # Print Qt message text & context
    print("=== Qt message ===")
    print("type:", msg_type)
    try:
        print("message:", message)
    except Exception:
        print("message: <unprintable>")
    # Python-level thread info
    print("Python threading.current_thread():", threading.current_thread().name)
    try:
        print("QThread.currentThread():", QThread.currentThread())
    except Exception:
        pass
    # Print Python stack for wherever we are in Python - useful to see what Python code
    # was running when Qt emitted its message.
    print("--- Python traceback (most recent call last) ---")
    traceback.print_stack(file=sys.stdout)
    print("=== end Qt message ===\n", flush=True)


def qt_message_filter(msg_type, context, message):
    if "Could not update timestamps for skipped samples." in str(message):
        return
    try:
        print(message)
    except Exception:
        pass


def log_player_action(action, player=None):
    print(f"[PLAYER] action={action}")
    print("  Python thread:", threading.current_thread().name)
    if player is not None:
        try:
            print("  player.thread():", player.thread())
        except Exception:
            pass


def log_worker_action(action, worker=None):
    print(f"[WORKER] action={action}")
    print("  Python thread:", threading.current_thread().name)
    try:
        print("  QThread.currentThread():", QThread.currentThread())
    except Exception:
        pass
    if worker is not None:
        try:
            print("  worker.thread():", worker.thread())
        except Exception:
            pass

def default_theme():
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            value = winreg.QueryValueEx(key, "AppsUseLightTheme")[0]
            # value == 0 -> dark, 1 -> light
            if value == 0:
                return "dark"
            else:
                return "light"
        except Exception:
            return "default"
    else:
        return "default"


def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        QMessageBox.warning(w, "Error!", str(e))
    return default


def save_json(path: Path, obj):
    try:
        path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    except Exception as e:
        QMessageBox.warning(w, "Error!", str(e))


def get_settings():
    # json_data = load_json(PLAYLISTS_FILE, default={"server": "http://localhost:5000", "playlists": []})
    default = {
        "server": "localhost",
        "mix_method": "Auto",
        "transition_duration": 4,
        "silence_threshold_db": -46,
        "silence_min_duration": 0.1,
        "scan_for_lyrics": True,
        "show_welcome": True,
        "style": "default",
    }
    json_settings = load_json(SETTINGS_FILE, default=default)
    # Ensure keys exist
    for k, v in default.items():
        if k not in json_settings:
            json_settings[k] = v
    return json_settings


class ItemType(Enum):
    PLAYLIST = "playlist"
    SONG = "song"
    ARTIST = "artist"
    ALBUM = "album"
    COVER = "cover"
    DIRECTORY = "directory"

    def set_item_type(self, item_type):
        if not isinstance(item_type, ItemType):
            raise ValueError("Invalid status value")
        w.status_bar.showMessage(f"Status set to: {item_type.value}")


class ListItem:
    def __init__(self):
        super().__init__()
        self.is_remote = False
        self.item_type = ItemType
        self.display_text = "Unknown"
        self.route = ""
        self.path = ""
        self.server = w.server

    #   self.id = int

    def absolute_path(self):
        if self.is_remote:
            abs_url = QUrl()
            abs_url.setScheme("http")
            abs_url.setHost(self.server)
            abs_url.setPort(5000)
            file_path = rf"/{self.route}/{self.path}"
            abs_url.setPath(file_path)
            return abs_url
        else:
            return QUrl.fromLocalFile(os.path.abspath(self.path))


class CheckBoxAction(QWidgetAction):
    def __init__(self, parent, text):
        super(CheckBoxAction, self).__init__(parent)
        layout = QHBoxLayout()
        self.widget = QWidget()
        label = QLabel(text)
        label.setAlignment(Qt.AlignLeft)
        layout.addWidget(QCheckBox())
        layout.addWidget(label)
        self.widget.setLayout(layout)
        self.setDefaultWidget(self.widget)


# --- Welcome Wizard Implementation ---
class WelcomeWizard(QDialog):
    """
    Simple multi-step welcome wizard.

    Steps:
      1. "Welcome" - Cancel / Next
      2. "Scanning" - Cancel / Scan / Next
      3. "Ready" - Cancel / Next
      4. "Connect to Another Computer" - Cancel / Connect to Remote / End Wizard
      5. "Placeholder for Text 5" - End (and a 'Don't show again' checkbox)

    The wizard will call AudioPlayer.scan_library and AudioPlayer.enter_server as requested.
    """

    def __init__(self, audio_player: "AudioPlayer"):
        super().__init__(audio_player)
        self.setWindowTitle("Welcome")
        self.setModal(True)
        self.audio = audio_player
        self.step = 1
        self.resize(500, 220)

        self.layout = QVBoxLayout(self)

        self.label = QLabel("", self)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            "font-size: 12px; border-width: 2px; border-color: #7A7EA8; border-style: inset;"
        )
        # In dark mode, if you want a highlight:
        if w.dark_style == "dark":
            self.label.setStyleSheet(
                "font-size: 12px; color: white; background: #19232D; border-width: 2px; border-color: #7A7EA8; border-style: inset;"
            )
        self.layout.addWidget(self.label)

        # Buttons container
        self.button_box = QHBoxLayout()
        self.layout.addLayout(self.button_box)

        # For final step option
        self.dont_show_checkbox = QCheckBox("Don't show this again", self)

        self._build_step_ui()
        self.update_step()

    def _clear_buttons(self):
        # Remove widgets from button box
        while self.button_box.count():
            item = self.button_box.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

    def _add_button(self, text, callback, default=False):
        btn = QPushButton(text, self)
        if default:
            btn.setDefault(True)
        btn.clicked.connect(callback)
        self.button_box.addWidget(btn)
        return btn

    def _build_step_ui(self):
        # Buttons are created dynamically per step in update_step
        pass

    def update_step(self):
        self._clear_buttons()
        # Remove checkbox if previously added
        try:
            self.layout.removeWidget(self.dont_show_checkbox)
            self.dont_show_checkbox.setParent(None)
        except Exception:
            pass

        if self.step == 1:
            self.label.setText(text_1)
            self._add_button("Cancel", self.reject)
            self._add_button("Next", self.next_step, default=True)

        elif self.step == 2:
            self.label.setText(text_2)
            self._add_button("Cancel", self.reject)
            self._add_button("Back", self.back_step)
            self._add_button("Scan", self._scan_async)
            self._add_button("Next", self.next_step, default=True)

        elif self.step == 3:
            self.label.setText(text_3)
            self._add_button("Cancel", self.reject)
            self._add_button("Back", self.back_step)
            self._add_button("Next", self.next_step, default=True)

        elif self.step == 4:
            self.label.setText(text_4)
            self._add_button("Cancel", self.reject)
            self._add_button("Back", self.back_step)
            self._add_button("Connect", self._connect_remote)
            self._add_button("Next", self.next_step, default=True)

        elif self.step == 5:
            self.label.setText(text_5)
            self._add_button("Cancel", self.reject)
            self._add_button("Back", self.back_step)
            self._add_button("Scan", self._scan_remote)
            self._add_button("Next", self.next_step, default=True)

        elif self.step == 6:
            self.label.setText(text_6)
            self._add_button("Cancel", self.reject)
            self._add_button("Back", self.back_step)
            self._add_button("Next", self.next_step, default=True)

        elif self.step == 7:
            self.label.setText(text_7)
            # Add the "Don't show again" checkbox
            self.layout.addWidget(self.dont_show_checkbox)
            self._add_button("Back", self.back_step)
            self._add_button("End", self.finish_wizard, default=True)

    def next_step(self):
        if self.step < 7:
            self.step += 1
            self.update_step()
        else:
            self.finish_wizard()

    def back_step(self):
        if self.step > 1:
            self.step -= 1
            self.update_step()

    def _scan_async(self):
        """
        Schedule scan_library to be called soon on the main event loop.
        scan_library uses GUI dialogs, so it must run on the main thread.
        We schedule it and continue (wizard remains open).
        """
        try:
            QTimer.singleShot(0, lambda: self.audio.scan_library())
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to start library scan: {e}")

    def _connect_remote(self):
        """
        Trigger connect to remote server flow.
        This will open the server dialog on the main event loop.
        """
        try:
            QTimer.singleShot(0, lambda: self.audio.enter_server())
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open Connect to Remote: {e}")

    def _scan_remote(self):
        """
        Schedule scan_remote_library to be called soon on the main event loop.
        scan_library uses GUI dialogs, so it must run on the main thread.
        We schedule it and continue (wizard remains open).
        """
        try:
            QTimer.singleShot(0, lambda: self.audio.scan_remote_library())
        except Exception as e:
            QMessageBox.warning(
                self, "Error", f"Failed to start remote library scan: {e}"
            )

    def finish_wizard(self):
        # Persist "don't show again" option if checked
        try:
            settings = load_json(SETTINGS_FILE, default={})
            if not isinstance(settings, dict):
                settings = {}
            settings["show_welcome"] = not self.dont_show_checkbox.isChecked()
            # Ensure other known settings remain (merge defaults)
            defaults = get_settings()
            for k, v in defaults.items():
                if k not in settings:
                    settings[k] = v
            save_json(SETTINGS_FILE, settings)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not save settings: {e}")
        self.accept()


# --- End of Welcome Wizard Implementation ---


class CheckBoxAction(QWidgetAction):
    def __init__(self, parent, text):
        super(CheckBoxAction, self).__init__(parent)
        layout = QHBoxLayout()
        self.widget = QWidget()
        label = QLabel(text)
        label.setAlignment(Qt.AlignLeft)
        layout.addWidget(QCheckBox())
        layout.addWidget(label)
        self.widget.setLayout(layout)
        self.setDefaultWidget(self.widget)


class AudioPlayer(QWidget):
    request_search = Signal(str, str)
    request_reveal = Signal(ListItem)

    def __init__(self, settings):
        super().__init__()

        # VLC fallback helper
        self.song_index = None
        self.vlc_helper = None
        self.vlc_active = False
        if VLC_AVAILABLE:
            self.vlc_helper = VlcFallbackPlayer(self)
            self.vlc_helper.positionChanged.connect(
                lambda pos: self._on_vlc_position_changed(pos)
            )
            self.vlc_helper.durationChanged.connect(
                lambda dur: self._on_vlc_duration_changed(dur)
            )
            self.vlc_helper.playbackStateChanged.connect(
                lambda state: self._on_vlc_playback_state(state)
            )
            self.vlc_helper.ended.connect(self._on_vlc_ended)

        # store full settings dict for use with wizard persistence
        self.scan_thread = None
        self.settings = settings
        self.scan_worker = None
        self.purge_worker = None
        self.is_local = None
        self.server_worker = None
        self.songs = None
        self.songs_worker = None
        self.album_meta_data = None
        self.meta_worker = None
        self.playlists_worker = None
        self.pl_worker = None
        self.search_worker = None
        self.server = settings["server"]
        self.api_url = self.remote_base = rf"http://{self.server}:5000"
        self.playlists = []
        self.dark_style = settings.get("style", "default")

        # Mixing/transition config
        self.mix_method = settings.get("mix_method", "Auto")
        self.transition_duration = settings.get("transition_duration", 4)
        self.scan_for_lyrics = settings.get("scan_for_lyrics", True)
        self.silence_threshold_db = settings.get("silence_threshold_db", -40)  # in dB
        self.silence_min_duration = settings.get(
            "silence_min_duration", 0.1
        )  # in seconds
        self._silence_ms = 0
        self._fade_step = None
        self.fade_timer = None
        self.progress = None
        self.setWindowTitle(f"Ultimate Media Player. Current Server: {self.api_url}")
        self.resize(1200, 800)
        self.playlist = []
        self.empty = QUrl()
        self.current_index = -1
        self.show_remaining = False
        self.sort_albums = True
        self.lyrics = None
        self.lyrics_timer = QTimer(self)
        self.lyrics_timer.setInterval(200)
        self.lyrics_timer.timeout.connect(self.update_lyrics_display)
        self.meta_data = {
            "album": "",
            "artist": "",
            "codec": "",
            "duration": 0,
            "lyrics": "",
            "picture": None,
            "title": "",
            "year": "",
        }  # Current track metadata

        # Layout
        layout = QVBoxLayout(self)

        # ----- Menu bar -----
        menubar = QMenuBar(self)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(True)

        # Create a thin horizontal line (separator)
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(2)  # Adjust thickness if desired

        # File menu
        local_menu = QMenu("&Local", self)
        menubar.addMenu(local_menu)

        self.open_action = QAction(
            QIcon("icons/open.png"), "&Open Playlist | Add Songs", self
        )
        self.open_action.setShortcut(QKeySequence.Open)
        self.open_action.setToolTip(
            "Add Songs/folders and/or Playlists to playing queue"
        )
        self.open_action.triggered.connect(self.show_playlist_menu)
        local_menu.addAction(self.open_action)

        self.load_action = QAction(QIcon("icons/playlist.png"), "Load &Playlists", self)
        self.load_action.setShortcut(QKeySequence.Print)
        self.load_action.triggered.connect(self.get_local_playlists)
        local_menu.addAction(self.load_action)

        self.list_songs_action = QAction(
            QIcon("icons/music-beam.png"), "List all &Songs", self
        )
        self.list_songs_action.setShortcut(QKeySequence("Ctrl+S"))
        self.list_songs_action.triggered.connect(self.get_local_songs)
        local_menu.addAction(self.list_songs_action)

        self.list_artists_action = QAction(
            QIcon("icons/violoncello.png"), "List all &Artists", self
        )
        self.list_artists_action.setShortcut(QKeySequence("Ctrl+A"))
        self.list_artists_action.triggered.connect(self.get_local_artists)
        local_menu.addAction(self.list_artists_action)

        self.list_albums_action = QAction(
            QIcon("icons/vinil.png"), "List all Al&bums", self
        )
        self.list_albums_action.setShortcut(QKeySequence("Ctrl+B"))
        self.list_albums_action.triggered.connect(self.get_local_albums)
        local_menu.addAction(self.list_albums_action)

        self.scan_action = QAction(
            QIcon("icons/database-insert.png"), "Scan &Library", self
        )
        self.scan_action.setShortcut(QKeySequence("Ctrl+L"))
        self.scan_action.triggered.connect(self.scan_library)
        local_menu.addAction(self.scan_action)

        self.purge_action = QAction(
            QIcon("icons/database-delete.png"), "P&urge Library", self
        )
        self.purge_action.setShortcut(QKeySequence("Ctrl+U"))
        self.purge_action.triggered.connect(self.purge_library)
        local_menu.addAction(self.purge_action)

        self.save_action = QAction(QIcon("icons/save.png"), "&Save Current Queue", self)
        self.save_action.setShortcut(QKeySequence.Save)
        self.save_action.triggered.connect(self.save_current_playlist)
        local_menu.addAction(self.save_action)

        self.clear_action = QAction(QIcon("icons/eraser.png"), "&Clear Playlist", self)
        self.clear_action.setShortcut(QKeySequence.Delete)
        self.clear_action.triggered.connect(self.clear_playlist)
        local_menu.addAction(self.clear_action)

        self.local_web_action = QAction(
            QIcon("icons/internet.png"), "Launch &Web UI", self
        )
        self.local_web_action.setShortcut(QKeySequence("Ctrl+W"))
        self.local_web_action.triggered.connect(self.local_web_ui)
        local_menu.addAction(self.local_web_action)

        self.local_shutdown_action = QAction(
            QIcon("icons/power.png"), "Shutdown Lo&cal Server", self
        )
        self.local_shutdown_action.setShortcut(QKeySequence.Close)
        self.local_shutdown_action.triggered.connect(self.shutdown_local_server)
        local_menu.addAction(self.local_shutdown_action)

        local_menu.addSeparator()

        self.exit_action = QAction("E&xit", self)
        self.exit_action.setShortcut(QKeySequence.Quit)
        self.exit_action.triggered.connect(self.quit)
        local_menu.addAction(self.exit_action)

        # Remote menu
        remote_menu = QMenu("&Remote", self)
        menubar.addMenu(remote_menu)

        self.server_action = QAction(
            QIcon("icons/database-share.png"), "Connect to R&emote", self
        )
        self.server_action.setShortcut(QKeySequence("Ctrl+E"))
        self.server_action.triggered.connect(self.enter_server)
        remote_menu.addAction(self.server_action)

        self.load_remote_action = QAction(
            QIcon("icons/playlistR.png"), "Load &Playlists", self
        )
        self.load_remote_action.setShortcut(QKeySequence.Print)
        self.load_remote_action.triggered.connect(self.get_playlists)
        remote_menu.addAction(self.load_remote_action)

        self.list_remote_songs_action = QAction(
            QIcon("icons/music-beamR.png"), "List all &Songs", self
        )
        self.list_remote_songs_action.setShortcut(QKeySequence("Ctrl+S"))
        self.list_remote_songs_action.triggered.connect(self.get_songs)
        remote_menu.addAction(self.list_remote_songs_action)

        self.list_remote_artists_action = QAction(
            QIcon("icons/violoncelloR.png"), "List all &Artists", self
        )
        self.list_remote_artists_action.setShortcut(QKeySequence("Ctrl+A"))
        self.list_remote_artists_action.triggered.connect(self.get_artists)
        remote_menu.addAction(self.list_remote_artists_action)

        self.list_remote_albums_action = QAction(
            QIcon("icons/vinilR.png"), "List all Al&bums", self
        )
        self.list_remote_albums_action.setShortcut(QKeySequence("Ctrl+B"))
        self.list_remote_albums_action.triggered.connect(self.get_albums)
        remote_menu.addAction(self.list_remote_albums_action)

        self.scan_remote_action = QAction(
            QIcon("icons/database-insertR.png"), "Scan &Library", self
        )
        self.scan_remote_action.setShortcut(QKeySequence("Ctrl+R"))
        self.scan_remote_action.triggered.connect(self.scan_remote_library)
        remote_menu.addAction(self.scan_remote_action)

        self.purge_remote_action = QAction(
            QIcon("icons/database-deleteR.png"), "P&urge Library", self
        )
        self.purge_remote_action.setShortcut(QKeySequence("Ctrl+U"))
        self.purge_remote_action.triggered.connect(self.purge_remote_library)
        remote_menu.addAction(self.purge_remote_action)

        self.remote_web_action = QAction(
            QIcon("icons/internetR.png"), "Launch &Web UI", self
        )
        self.remote_web_action.setShortcut(QKeySequence("Ctrl+I"))
        self.remote_web_action.triggered.connect(self.remote_web_ui)
        remote_menu.addAction(self.remote_web_action)

        self.remote_desktop_action = QAction(
            QIcon("icons/favicon.ico"), "Launch &Desktop UI", self
        )
        self.remote_desktop_action.setShortcut(QKeySequence("Ctrl+D"))
        self.remote_desktop_action.triggered.connect(self.remote_desk_ui)
        remote_menu.addAction(self.remote_desktop_action)

        self.remote_shutdown_action = QAction(
            QIcon("icons/powerR.png"), "S&hutdown Server", self
        )
        self.remote_shutdown_action.setShortcut(QKeySequence("Ctrl+C"))
        self.remote_shutdown_action.triggered.connect(self.shutdown_server)
        remote_menu.addAction(self.remote_shutdown_action)

        remote_menu.addSeparator()

        self.exit_action = QAction("E&xit", self)
        self.exit_action.setShortcut(QKeySequence.Quit)
        self.exit_action.triggered.connect(self.quit)
        remote_menu.addAction(self.exit_action)

        # Settings menu
        settings_menu = QMenu("&Settings", self)
        menubar.addMenu(settings_menu)

        # Style menu
        style_menu = QMenu("&Style", self)
        settings_menu.addMenu(style_menu)

        self.dark_action = QAction(QIcon("icons/moon.png"), "&Dark Mode", self)
        self.dark_action.triggered.connect(self.set_dark_style)
        style_menu.addAction(self.dark_action)

        self.light_action = QAction(QIcon("icons/dark-mode.png"), "&Light Mode", self)
        self.light_action.triggered.connect(self.set_light_style)
        style_menu.addAction(self.light_action)

        self.normal_action = QAction(
            QIcon("icons/normal-mode.png"), "&Default Mode", self
        )
        self.normal_action.triggered.connect(self.set_no_style)
        style_menu.addAction(self.normal_action)

        # Lyrics Menu
        lyrics_menu = QMenu("&Lyrics", self)
        settings_menu.addMenu(lyrics_menu)
        self.lyrics_action = CheckBoxAction(self, "Auto download Lyrics")
        #  self.lyrics_action.triggered.connect(self.toggle_lyrics_scan)
        lyrics_menu.addAction(self.lyrics_action)
        self.lyrics_checkbox = self.lyrics_action.widget.findChild(QCheckBox)
        self.lyrics_checkbox.setChecked(self.scan_for_lyrics)
        self.lyrics_checkbox.stateChanged.connect(self.toggle_lyrics_scan)

        # Help menu
        help_menu = QMenu("&Help", self)
        menubar.addMenu(help_menu)

        self.wizard_action = QAction(QIcon("icons/wizard.png"), "Set Up &Wizard", self)
        self.wizard_action.triggered.connect(self.wizard)
        help_menu.addAction(self.wizard_action)

        self.instructions_action = QAction(
            QIcon("icons/user-guide.png"), "&Instructions", self
        )
        self.instructions_action.triggered.connect(self.show_instructions)
        help_menu.addAction(self.instructions_action)

        self.about_action = QAction(QIcon("icons/user.png"), "&About", self)
        self.about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(self.about_action)

        # Add action to toolbar
        toolbar.addSeparator()
        toolbar.addAction(self.open_action)
        toolbar.addAction(self.load_action)
        toolbar.addAction(self.list_songs_action)
        toolbar.addAction(self.list_artists_action)
        toolbar.addAction(self.list_albums_action)
        toolbar.addAction(self.scan_action)
        toolbar.addAction(self.purge_action)
        toolbar.addAction(self.save_action)
        toolbar.addAction(self.clear_action)
        toolbar.addAction(self.local_web_action)
        toolbar.addAction(self.local_shutdown_action)
        toolbar.addSeparator()
        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addSeparator()
        toolbar.addAction(self.dark_action)
        toolbar.addAction(self.light_action)
        toolbar.addAction(self.normal_action)
        #  toolbar.addAction(self.lyrics_action)
        toolbar.addSeparator()
        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addSeparator()
        toolbar.addAction(self.server_action)
        toolbar.addAction(self.load_remote_action)
        toolbar.addAction(self.list_remote_songs_action)
        toolbar.addAction(self.list_remote_artists_action)
        toolbar.addAction(self.list_remote_albums_action)
        toolbar.addAction(self.scan_remote_action)
        toolbar.addAction(self.purge_remote_action)
        toolbar.addAction(self.remote_web_action)
        toolbar.addAction(self.remote_desktop_action)
        toolbar.addAction(self.remote_shutdown_action)
        toolbar.addSeparator()
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addSeparator()
        toolbar.addAction(self.wizard_action)
        toolbar.addAction(self.instructions_action)
        toolbar.addAction(self.about_action)
        toolbar.addSeparator()

        # Audio/Player
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.audio_output.setVolume(
            1.0
        )  # or any value between 0.0 (mute) to 1.0 (full volume)
        self.player.setAudioOutput(self.audio_output)
        #   self.buffer = QAudioBufferOutput(self)
        #   self.player.setAudioBufferOutput(self.buffer)
        #  self.buffer.bufferAvailable.connect(self.on_buffer)
        self.next_player = None  # For mixing with next track
        self.next_output = None

        # Silence elimination config
        self.skip_silence = True  # Optionally configurable

        top = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.addItems(["artist", "song_title", "album"])
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search for Artist, Song, or Album…")
        self.btn_local = QPushButton("Search Local")
        self.btn_go = QPushButton("Search Server")
        top.addWidget(self.combo)
        top.addWidget(self.search, 2)
        top.addWidget(self.btn_local)
        top.addWidget(self.btn_go)

        # Playlist browser with context menu support
        shuffle_box = QHBoxLayout()
        self.playlist_widget = QListWidget()
        self.playlist_widget.setStyleSheet(
            "QListView::item:selected{ color: black; background-color: lightblue; }; "
            "font-size: 12px; "
            "background-color: lightyellow; "
            "opacity: 0.6; "
            "border-color: #D4D378; "
            "border-width: 2px; "
            "border-style: inset;"
        )
        self.playlist_label = QLabel("Queue:")
        self.btn_shuffle = QPushButton("Shuffle")
        self.btn_shuffle.setFixedSize(QSize(60, 26))
        self.sort = QPushButton("Sort")
        self.sort.setFixedSize(QSize(60, 26))
        self.playlist_widget.setDragDropMode(QListWidget.InternalMove)
        self.playlist_widget.itemClicked.connect(self.play_selected_item)
        # self.playlist_widget.itemDoubleClicked.connect(
        # self.play_selected_track)
        self.playlist_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.playlist_widget.customContextMenuRequested.connect(
            self.show_playlist_context_menu
        )

        # Drag-and-drop support
        self.setAcceptDrops(True)
        self.playlist_widget.viewport().setAcceptDrops(True)
        self.playlist_widget.viewport().installEventFilter(self)

        # Controls/UI
        self.album_art = QLabel()
        self.album_art.setFixedSize(256, 256)
        self.album_art.setScaledContents(True)
        self.album_art.setPixmap(
            QPixmap("static/images/default_album_art.png")
            if os.path.exists("static/images/default_album_art.png")
            else QPixmap()
        )
        self.title_label = QLabel("Title --")
        self.title_label.setWordWrap(True)
        self.title_label.setFixedWidth(256)
        self.artist_label = QLabel("Artist --")
        self.artist_label.setWordWrap(True)
        self.artist_label.setFixedWidth(256)
        self.album_label = QLabel("Album --")
        self.album_label.setWordWrap(True)
        self.album_label.setFixedWidth(256)
        self.year_label = QLabel("Year --")
        self.duration_label = QLabel("Duration --")
        self.codec_label = QLabel("Codec --")

        self.text = QTextEdit(readOnly=True)
        # self.text_label = QLabel("Artist and Song Info:")
        self.btn_info = QPushButton("Push for Artist and Song Info.")
        self.btn_info.setFixedSize(QSize(256, 26))

        self.time_label = QPushButton("--:--")
        self.time_label.setFlat(True)
        self.time_label.setCursor(Qt.PointingHandCursor)
        self.time_label.clicked.connect(self.toggle_time_display)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        #  self.slider.sliderMoved.connect(self.seek_position) replaced by slider released
        self.slider.sliderMoved.connect(self.on_slider_moved)
        self.slider.sliderReleased.connect(self.on_slider_released)
        self._slider_moving = False

        # StatusBar
        self.status_bar = QStatusBar()
        self.status_bar.showMessage(
            "Welcome!☺️ Drag-and-drop Playlists or/and Songs to Playlist queue to start the music 🎵."
        )
        # self.wc_label = QLabel("To start the music, Drag-and-drop Playlists or/and Songs to Queue pane.")
        # self.status_bar.addPermanentWidget(self.wc_label)

        image_path = "static/images/buttons.png"
        tile_width = 1650
        tile_height = 1650
        self.sub_images = self.split_image(image_path, tile_width, tile_height)

        self.prev_button = QPushButton()
        if self.sub_images:
            pixmap = QPixmap.fromImage(self.sub_images[2])
            self.prev_button.setIcon(QIcon(pixmap))
            self.prev_button.setIconSize(QSize(50, 50))
        else:
            # self.prev_button.setEnabled(False)
            self.prev_button.setIcon(
                self.style().standardIcon(QStyle.SP_MediaSkipBackward)
            )
        self.prev_button.setFixedSize(QSize(50, 50))
        self.play_button = QPushButton()
        if self.sub_images:
            pixmap = QPixmap.fromImage(self.sub_images[0])
            self.play_button.setIcon(QIcon(pixmap))
            self.play_button.setIconSize(QSize(50, 50))
        else:
            # self.play_button.setEnabled(False)
            self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_button.setFixedSize(QSize(50, 50))
        self.next_button = QPushButton()
        if self.sub_images:
            pixmap = QPixmap.fromImage(self.sub_images[3])
            self.next_button.setIcon(QIcon(pixmap))
            self.next_button.setIconSize(QSize(50, 50))
        else:
            #   self.next_button.setEnabled(False)
            self.next_button.setIcon(
                self.style().standardIcon(QStyle.SP_MediaSkipForward)
            )
        self.next_button.setFixedSize(QSize(50, 50))
        self.prev_button.clicked.connect(self.prev_track)
        self.play_button.clicked.connect(self.toggle_play_pause)
        self.next_button.clicked.connect(self.next_track)

        # Lyrics
        self.lyrics_display = LyricsDisplay()
        self.lyrics_display.setReadOnly(True)

        # Mixing Controls UI
        self.crossfade_modes = ["Auto", "Fade", "Smooth", "Full", "Scratch", "Cue"]
        self.mix_method_combo = QComboBox()
        self.mix_method_combo.addItems(self.crossfade_modes)
        self.mix_method_combo.setCurrentText(self.mix_method)
        self.mix_method_combo.currentTextChanged.connect(self.set_mix_method)

        self.transition_spin = QSpinBox()
        self.transition_spin.setRange(1, 10)
        self.transition_spin.setValue(self.transition_duration)
        self.transition_spin.setSuffix(" s")
        self.transition_spin.valueChanged.connect(self.set_transition_duration)
        mix_form = QFormLayout()
        mix_form.addRow("Mix Method:", self.mix_method_combo)
        mix_form.addRow("Transition:", self.transition_spin)
        #   mix_form.addRow(self.silence_check)
        mix_group = QGroupBox("Mixing Options")
        mix_group.setFixedSize(QSize(180, 80))
        mix_group.setLayout(mix_form)

        gap_killer_group = QGroupBox("Auto Mix")
        #   gap_killer_group.setFixedSize(QSize(180, 80))
        gap_box = QHBoxLayout()
        #  self.chk_gap = QCheckBox("ON")
        # self.chk_gap.setChecked(True)
        self.silence_db = QSlider(Qt.Horizontal)
        self.silence_db.setRange(-60, -20)
        self.silence_db.setValue(-46)
        self.silence_dur = QSlider(Qt.Horizontal)
        self.silence_dur.setRange(1, 50)
        self.silence_dur.setValue(5)
        self.gap_status = QLabel("Monitoring")
        # gap_box.addWidget(self.chk_gap)
        gap_box.addWidget(QLabel("Threshold (dB):"))
        gap_box.addWidget(self.silence_db, 1)
        gap_box.addWidget(QLabel("Min Silence (x100ms):"))
        gap_box.addWidget(self.silence_dur, 1)
        gap_box.addWidget(self.gap_status)
        gap_killer_group.setLayout(gap_box)

        reveal = QVBoxLayout()
        self.reveal_label = QLabel("Reveal Song\n   in Folder")
        self.reveal_btn = QPushButton("Reveal")
        self.reveal_btn.setFixedSize(QSize(50, 30))
        reveal.addWidget(self.reveal_label)
        reveal.addWidget(self.reveal_btn)

        # Layout
        info_layout = QHBoxLayout()
        info_layout.addWidget(self.album_art)
        meta_layout = QVBoxLayout()
        meta_layout.addWidget(self.title_label)
        meta_layout.addWidget(self.artist_label)
        meta_layout.addWidget(self.album_label)
        meta_layout.addWidget(self.year_label)
        meta_layout.addWidget(self.duration_label)
        meta_layout.addWidget(self.codec_label)

        metadata_layout = QVBoxLayout()
        metadata_layout.addWidget(self.btn_info)
        metadata_layout.addWidget(self.text)

        info_layout.addLayout(meta_layout)
        info_layout.addLayout(metadata_layout)

        progress_layout = QHBoxLayout()
        progress_layout.addWidget(self.time_label)
        progress_layout.addWidget(self.slider)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self.prev_button)
        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.next_button)

        left_layout = QVBoxLayout()
        left_layout.addLayout(top)
        left_layout.addLayout(info_layout)
        left_layout.addLayout(progress_layout)
        left_layout.addLayout(controls_layout)
        left_layout.addWidget(self.lyrics_display)

        mixer_layout = QHBoxLayout()
        mixer_layout.addWidget(mix_group)
        mixer_layout.addWidget(gap_killer_group)
        mixer_layout.addLayout(reveal)
        left_layout.addLayout(mixer_layout)

        playlist_layout = QVBoxLayout()
        shuffle_box.addWidget(
            self.playlist_label,
        )
        shuffle_box.addWidget(
            self.btn_shuffle,
        )
        shuffle_box.addWidget(
            self.sort,
        )
        playlist_layout.addLayout(shuffle_box)
        playlist_layout.addWidget(self.playlist_widget)

        main_layout = QHBoxLayout()
        main_layout.addLayout(playlist_layout, 1)
        main_layout.addLayout(left_layout, 2)
        layout.addWidget(menubar)
        layout.addWidget(separator)
        layout.addWidget(toolbar)
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)
        layout.addLayout(main_layout, 1)
        layout.addWidget(self.status_bar)

        self.setLayout(layout)

        # Connections
        self.btn_local.clicked.connect(self.on_local)
        self.btn_go.clicked.connect(self.on_go)
        self.search.returnPressed.connect(self.on_local)
        self.btn_shuffle.clicked.connect(self.do_shuffle)
        self.sort.clicked.connect(self.do_sort)
        self.btn_info.clicked.connect(self.get_info)
        self.request_search.connect(self.search_tracks)
        self.request_reveal.connect(self.reveal_path)
        self.player.positionChanged.connect(self.update_slider)
        self.player.durationChanged.connect(self.update_duration)
        self.player.mediaStatusChanged.connect(self.media_status_changed)
        self.player.playbackStateChanged.connect(self.update_play_button)
        self.slider.sliderPressed.connect(lambda: self.player.pause())
        self.slider.sliderReleased.connect(lambda: self.player.play())
        self.silence_db.valueChanged.connect(
            lambda v: setattr(self, "silence_threshold_db", v)
        )
        self.silence_dur.valueChanged.connect(
            lambda v: setattr(self, "silence_min_duration", v / 10.0)
        )
        self.reveal_btn.clicked.connect(self.reveal_current)
        self.player.errorOccurred.connect(self.handle_error)

        # For mixing (transition to next track)
        self.player.positionChanged.connect(self.check_for_mix_transition)

        # Init
        self.init_database()
        self.update_play_button()
        self.show()
        if self.dark_style == "dark" or default_theme() == "dark":
            self.set_dark_style()
        elif self.dark_style == "light" or default_theme() == "light":
            self.set_light_style()
        else:
            self.set_no_style()

        for item in self.playlists:
            self.playlist_widget.addItem(item["name"])

        # Launch welcome wizard automatically if enabled in settings
        try:
            if self.settings.get("show_welcome", True) and len(sys.argv) == 1:
                wizard = WelcomeWizard(self)
                if self.dark_style == "dark":
                    wizard.label.setStyleSheet(
                        "font-size: 12px; color: white; background: 19232D; border-width: 2px; border-color: #7A7EA8; border-style: inset;"
                    )
                else:
                    wizard.label.setStyleSheet(
                        "font-size: 12px; background: lightyellow; border-width: 2px; border-color: #7A7EA8; border-style: inset;"
                    )
                wizard.exec()
        except Exception:
            pass

    def split_image(self, image_path, tile_width, tile_height):
        image = QImage(image_path)
        if image.isNull():
            self.status_bar.showMessage("Failed to load image: " + image_path)
            return []

        img_width = image.width()
        img_height = image.height()
        sub_images = []

        for top in range(0, img_height, tile_height):
            for left in range(0, img_width, tile_width):
                rect = QRect(
                    left,
                    top,
                    min(tile_width, img_width - left),
                    min(tile_height, img_height - top),
                )
                sub_img = image.copy(rect)
                sub_images.append(sub_img)
        return sub_images

    def set_dark_style(self):
        self.dark_style = "dark"
        app.setStyleSheet(qdarkstyle.load_stylesheet(palette=DarkPalette))
        # Remove explicit color: black, background: light for dark mode
        self.lyrics_display.setStyleSheet(
            "font-size: 18px; background: #21314a; color: white; border-width: 2px; border-color: #7A7EA8; border-style: inset;"
        )
        self.playlist_widget.setStyleSheet(
            "QListView::item:selected{ background-color: #324C64; };")
        dark_image_path = "static/images/buttons_dark.jpg"
        #  self.sub_images.load(dark_image_path)
        #   self.lbl.setPixmap(self.sub_images)
        tile_width = 1650
        tile_height = 1650
        self.sub_images = self.split_image(dark_image_path, tile_width, tile_height)

        if self.sub_images:
            pixmap = QPixmap.fromImage(self.sub_images[2])
            self.prev_button.setIcon(QIcon(pixmap))
            self.prev_button.setIconSize(QSize(50, 50))
        else:
            self.prev_button.setIcon(
                self.style().standardIcon(QStyle.SP_MediaSkipBackward)
            )
        self.prev_button.setFixedSize(QSize(50, 50))
        if self.sub_images:
            pixmap = QPixmap.fromImage(self.sub_images[0])
            self.play_button.setIcon(QIcon(pixmap))
            self.play_button.setIconSize(QSize(50, 50))
        else:
            self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_button.setFixedSize(QSize(50, 50))
        if self.sub_images:
            pixmap = QPixmap.fromImage(self.sub_images[3])
            self.next_button.setIcon(QIcon(pixmap))
            self.next_button.setIconSize(QSize(50, 50))
        else:
            #   self.next_button.setEnabled(False)
            self.next_button.setIcon(
                self.style().standardIcon(QStyle.SP_MediaSkipForward)
            )
        self.next_button.setFixedSize(QSize(50, 50))

    def set_light_style(self):
        self.dark_style = "light"
        # setup stylesheet
        app.setStyleSheet(qdarkstyle.load_stylesheet(palette=LightPalette))
        self.playlist_widget.setStyleSheet(
            "QListView::item:selected{ background-color: lightblue;}; "
        )
        image_path = "static/images/buttons_light.jpg"
        tile_width = 1650
        tile_height = 1650
        self.sub_images = self.split_image(image_path, tile_width, tile_height)
        if self.sub_images:
            pixmap = QPixmap.fromImage(self.sub_images[2])
            self.prev_button.setIcon(QIcon(pixmap))
            self.prev_button.setIconSize(QSize(50, 50))
        else:
            self.prev_button.setIcon(
                self.style().standardIcon(QStyle.SP_MediaSkipBackward)
            )
        self.prev_button.setFixedSize(QSize(50, 50))
        if self.sub_images:
            pixmap = QPixmap.fromImage(self.sub_images[0])
            self.play_button.setIcon(QIcon(pixmap))
            self.play_button.setIconSize(QSize(50, 50))
        else:
            self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_button.setFixedSize(QSize(50, 50))
        if self.sub_images:
            pixmap = QPixmap.fromImage(self.sub_images[3])
            self.next_button.setIcon(QIcon(pixmap))
            self.next_button.setIconSize(QSize(50, 50))
        else:
            #   self.next_button.setEnabled(False)
            self.next_button.setIcon(
                self.style().standardIcon(QStyle.SP_MediaSkipForward)
            )
        self.next_button.setFixedSize(QSize(50, 50))

    def set_no_style(self):
        if default_theme() == "dark":
            return
        self.dark_style = "default"
        # setup stylesheet
        app.setStyleSheet("")
        self.playlist_widget.setStyleSheet(
            "QListView::item:selected{ color: black; background-color: lightblue; }; "
            "font-size: 12px; "
            "background-color: lightyellow; "
            "opacity: 0.6; "
            "border-color: #D4D378; "
            "border-width: 2px; "
            "border-style: inset;"
        )
        image_path = "static/images/buttons.jpg"
        tile_width = 1650
        tile_height = 1650
        self.sub_images = self.split_image(image_path, tile_width, tile_height)
        if self.sub_images:
            pixmap = QPixmap.fromImage(self.sub_images[2])
            self.prev_button.setIcon(QIcon(pixmap))
            self.prev_button.setIconSize(QSize(50, 50))
        else:
            self.prev_button.setIcon(
                self.style().standardIcon(QStyle.SP_MediaSkipBackward)
            )
        self.prev_button.setFixedSize(QSize(50, 50))
        if self.sub_images:
            pixmap = QPixmap.fromImage(self.sub_images[0])
            self.play_button.setIcon(QIcon(pixmap))
            self.play_button.setIconSize(QSize(50, 50))
        else:
            self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_button.setFixedSize(QSize(50, 50))
        if self.sub_images:
            pixmap = QPixmap.fromImage(self.sub_images[3])
            self.next_button.setIcon(QIcon(pixmap))
            self.next_button.setIconSize(QSize(50, 50))
        else:
            #   self.next_button.setEnabled(False)
            self.next_button.setIcon(
                self.style().standardIcon(QStyle.SP_MediaSkipForward)
            )
        self.next_button.setFixedSize(QSize(50, 50))

    def toggle_lyrics_scan(self):
        """Toggle lyrics scanning option"""
        if self.lyrics_checkbox.isChecked():
            self.scan_for_lyrics = True
        else:
            self.scan_for_lyrics = False
        state = "enabled" if self.scan_for_lyrics else "disabled"
        self.status_bar.showMessage(f"Lyrics scanning {state}")

    def wizard(self):
        """Launch the welcome/setup wizard"""
        try:
            wizard = WelcomeWizard(self)
            if self.dark_style == "dark":
                wizard.label.setStyleSheet(
                    "font-size: 12px; color: white; background: 19232D; border-width: 2px; border-color: #7A7EA8; border-style: inset;"
                )
            else:
                wizard.label.setStyleSheet(
                    "font-size: 12px; background: lightyellow; border-width: 2px; border-color: #7A7EA8; border-style: inset;"
                )
            wizard.exec()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to launch wizard: {e}")

    # Database initialization
    def init_database(self):
        """Initialize the database with proper error handling"""
        try:
            # self.status_bar.showMessage("Initializing database...")
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()

            # Create Songs table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS Songs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path CHAR(255) NOT NULL,
                    file_name CHAR(120) NOT NULL,
                    artist CHAR(120) NOT NULL,
                    album_artist CHAR(120),
                    song_title CHAR(120) NOT NULL,
                    duration INT NOT NULL,
                    album CHAR(120),
                    year SMALLINT
                )
            """
            )

            # Create Playlists table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS Playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path CHAR(255) NOT NULL,
                    PL_name CHAR(120) NOT NULL
                )
            """
            )

            conn.commit()
            conn.close()
            conn = sqlite3.connect(COVERS_DB_PATH)
            cursor = conn.cursor()

            # Create Album Art table
            cursor.execute(
                """
                        CREATE TABLE IF NOT EXISTS Covers (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            album CHAR(120) NOT NULL,
                            album_artist CHAR(120) NOT NULL,
                            cover TEXT
                        )
                    """
            )

            conn.commit()
            conn.close()
        #   self.status_bar.showMessage("Databases initialized successfully", 4000)

        except sqlite3.Error as e:
            QMessageBox.critical(
                self, "Database Error", f"Database initialization failed: {str(e)}"
            )
            raise
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Unexpected error during database initialization: {e}"
            )
            raise

    def on_finished(self, added_songs, added_playlists, scan_errors):
        """UI cleanup and a short status message."""
        if self.progress:
            self.status_bar.removeWidget(self.progress)
            self.progress = None

        # Ensure any worker-side flag is cleared (worker already finished)
        try:
            if self.scan_worker:
                # worker.stop() not needed here because run() has completed and emitted finished
                pass
        except Exception:
            pass

        # Give higher-level cleanup to the connected deleteLater handlers.
        # Update the status message:
        self.status_bar.showMessage(
            f"Scan complete. Found {added_songs} audio files, {added_playlists} "
            f"playlists and encountered {scan_errors} errors.",
            8000,
        )

        # Clear references so GC can collect after deleteLater runs
        self.scan_worker = None
        self.scan_thread = None

    def start_scan(self, directory):
        # ...
        self.scan_thread = QThread(parent=None)
        self.scan_worker = ScanWorker(directory)  # IMPORTANT: no parent
        self.scan_worker.moveToThread(self.scan_thread)

        # Lifecycle wiring
        self.scan_worker.finished.connect(
            self.scan_thread.quit, type=Qt.QueuedConnection
        )
        self.scan_worker.finished.connect(
            self.scan_worker.deleteLater, type=Qt.QueuedConnection
        )
        self.scan_thread.finished.connect(
            self.scan_thread.deleteLater, type=Qt.QueuedConnection
        )

        self.scan_thread.started.connect(self.scan_worker.run, type=Qt.QueuedConnection)

        # Connect worker signals -> main-thread slots (explicit slots below)
        self.scan_worker.started.connect(self.on_scan_started, type=Qt.QueuedConnection)
        self.scan_worker.folder_scanned.connect(
            self.on_folder_scanned, type=Qt.QueuedConnection
        )
        self.scan_worker.warning.connect(
            self.on_worker_warning, type=Qt.QueuedConnection
        )
        self.scan_worker.status.connect(self.on_worker_status, type=Qt.QueuedConnection)
        self.scan_worker.error.connect(self.on_worker_error, type=Qt.QueuedConnection)

        # Keep the UI-handling finished slot
        self.scan_worker.finished.connect(self.on_finished, type=Qt.QueuedConnection)

        self.scan_thread.start()

    # New slot methods (add these to your main window/controller class)
    @Slot(str)
    def on_scan_started(self, directory):
        # Always runs in main thread (QueuedConnection)
        self.status_bar.showMessage(f"Scanning directory: {directory}")

    @Slot(str)
    def on_folder_scanned(self, folder):
        # Always runs in main thread (QueuedConnection)
        self.status_bar.showMessage(f"Scanning folder: {folder}")

    @Slot(str)
    def on_worker_warning(self, msg):
        # Always runs in main thread (QueuedConnection)
        self.status_bar.showMessage(msg)

    @Slot(str)
    def on_worker_status(self, msg):
        # Always runs in main thread (QueuedConnection)
        self.status_bar.showMessage(msg)

    @Slot(str)
    def on_worker_error(self, msg):
        # Always runs in main thread (QueuedConnection)
        QMessageBox.critical(self, "Error", msg)

    def stop_scan(self):
        """Stop the ongoing scan operation"""
        if self.scan_worker is None or self.scan_thread is None:
            return
        # Ask the worker to stop
        try:
            self.scan_worker.stop()  # sets internal _stopped flag
        # log_worker_action("stop")
        except Exception:
            pass

        # Tell the thread to quit and wait for it to finish to avoid races.
        try:
            self.scan_thread.quit()
        except Exception:
            pass
        try:
            self.scan_thread.wait(
                timeout=5000
            )  # wait up to 5s (or call without timeout)
        except Exception:
            try:
                self.scan_thread.wait()
            except Exception:
                pass

        self.status_bar.showMessage("Scan operation stopped by user", 4000)

    @Slot(dict)
    def on_server_reply(self, data: dict):
        """Handle successful playlist retrieval completion"""
        if "error" in data:
            QMessageBox.warning(self, "Scan Error", data["error"])
        self.status_bar.repaint()

        #   status_code = data['status']
        if data["status"] == 200:
            self.server = data["API_URL"]
            self.playlist_widget.clear()
            self.api_url = self.remote_base = f"http://{self.server}:5000"
            save_json(
                SETTINGS_FILE,
                {
                    "server": self.server,
                    "mix_method": self.mix_method,
                    "transition_duration": self.transition_duration,
                    "silence_threshold_db": self.silence_threshold_db,
                    "silence_min_duration": self.silence_min_duration,
                    "scan_for_lyrics": self.scan_for_lyrics,
                },
            )
            self.setWindowTitle(
                f"Ultimate Media Player. Current Server: {self.api_url}"
            )
            self.status_bar.showMessage(f"Remote Server is now: {self.api_url}", 8000)
            QMessageBox.information(
                self, "Success!", f"Remote Server is now: {self.api_url}"
            )
        else:
            QMessageBox.warning(self, "Error", data["status"])

    def on_server_error(self, error_message):
        """Handle server check error"""
        if error_message == "":
            error_message = f"Remote Server not responding.\nMake sure the Server is Up and Connected"
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()

    def cleanup_server(self):
        """Clean up after scan completion"""
        # Remove progress bar and clear status
        if self.progress:
            self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()

        # Clean up worker reference
        self.server_worker.deleteLater()
        self.server_worker = None

    def enter_server(self):
        server, ok_pressed = QInputDialog.getText(
            self, "Input", "Enter Remote Server name or IP:", QLineEdit.Normal, ""
        )
        if ok_pressed and server != "":
            self.status_bar.showMessage(
                f"Please Wait, testing connection with server: {server}"
            )
            #   self.status_bar.clearMessage()
            self.progress = QProgressBar()
            self.progress.setStyleSheet(
                "::chunk {background-color: magenta; width: 8px; margin: 0.5px;}"
            )
            self.progress.setRange(0, 0)  # Indeterminate progress
            self.status_bar.addPermanentWidget(self.progress)
            self.status_bar.update()

            self.server_worker = Worker("server", server)
            self.server_worker.work_completed.connect(self.on_server_reply)
            self.server_worker.work_error.connect(self.on_server_error)
            self.server_worker.finished.connect(self.cleanup_server)

            try:
                # Start the async operation
                self.server_worker.start()
            except Exception as e:
                self.status_bar.clearMessage()
                QMessageBox.warning(
                    self,
                    "Error",
                    f"Server {server} not responding.\nMake sure the Server is Up and Connected",
                )

    def scan_remote_library(self):
        """async scan_remote_library"""

        # Get folder path from user input
        folder_path, ok = QInputDialog.getText(
            self,
            "Input",
            "Enter the Remote Absolute Path of Folder to Scan:",
            QLineEdit.Normal,
            "",
        )

        if not (ok and folder_path):
            return

        # Update status bar and show progress
        self.status_bar.showMessage(
            "Scanning your Music Library. Please Wait, it might take some time depending on the library size"
        )

        # Create and configure progress bar
        self.progress = QProgressBar()
        self.progress.setStyleSheet(
            "::chunk {background-color: magenta; width: 8px; margin: 0.5px;}"
        )
        self.progress.setRange(0, 0)  # Indeterminate progress
        self.status_bar.addPermanentWidget(self.progress)
        self.status_bar.update()

        # Create and configure worker thread
        self.scan_worker = Worker(folder_path, f"{self.api_url}/scan_library")
        self.scan_worker.work_completed.connect(self.on_scan_completed)
        self.scan_worker.work_error.connect(self.on_scan_error)
        self.scan_worker.finished.connect(self.cleanup_scan)

        # Start the async operation
        self.scan_worker.start()
        self.scan_worker.mutex.lock()

    def on_scan_completed(self, data):
        """Handle successful scan completion"""
        if self.scan_worker:
            self.scan_worker.mutex.unlock()
        if "error" in data:
            QMessageBox.warning(self, "Scan Error", data["error"])
        elif "answer" in data:
            QMessageBox.warning(self, "Scan Error", data["answer"]["error"])
        else:
            QMessageBox.information(self, "Success", data["message"])
        self.status_bar.repaint()

    def on_scan_error(self, error_message):
        """Handle scan error"""
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()

    def cleanup_scan(self):
        """Clean up after scan completion"""
        # Remove progress bar and clear status
        if self.progress:
            self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()

        # Clean up worker reference
        if self.scan_worker:
            self.scan_worker.deleteLater()
            self.scan_worker = None

    def purge_remote_library(self):
        """async purge remote library"""

        # Get folder path from user input
        folder_path, ok = QInputDialog.getText(
            self,
            "Input",
            "Enter the Remote Absolute Path of Folder to Purge:",
            QLineEdit.Normal,
            "",
        )

        if not (ok and folder_path):
            return

        # Update status bar and show progress
        self.status_bar.showMessage(
            "Scanning your Music Library for deleted files. Please Wait, it might take some time depending on the library size"
        )

        # Create and configure progress bar
        self.progress = QProgressBar()
        self.progress.setStyleSheet(
            "::chunk {background-color: magenta; width: 8px; margin: 0.5px;}"
        )
        self.progress.setRange(0, 0)  # Indeterminate progress
        self.status_bar.addPermanentWidget(self.progress)
        self.status_bar.update()

        # Create and configure worker thread
        self.purge_worker = Worker(("purge", folder_path), self.api_url)
        self.purge_worker.work_completed.connect(self.on_purge_completed)
        self.purge_worker.work_error.connect(self.on_purge_error)
        self.purge_worker.finished.connect(self.cleanup_purge)

        # Start the async operation
        self.purge_worker.start()
        self.purge_worker.mutex.lock()

    def on_purge_completed(self, data):
        """Handle successful Purge completion"""
        if self.purge_worker:
            self.purge_worker.mutex.unlock()
        if "error" in data:
            QMessageBox.warning(self, "Purge Error", data["error"])
        elif "answer" in data:
            QMessageBox.warning(self, "Purge Error", data["answer"]["error"])
        else:
            QMessageBox.information(self, "Success", data["message"])
        self.status_bar.repaint()

    def on_purge_error(self, error_message):
        """Handle Purge error"""
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()

    def cleanup_purge(self):
        """Clean up after Purge completion"""
        # Remove progress bar and clear status
        if self.progress:
            self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()

        # Clean up worker reference
        if self.purge_worker:
            self.purge_worker.deleteLater()
            self.purge_worker = None

    def shutdown_local_server(self):
        try:
            resp = requests.post(
                "http://localhost:5000/shutdown",
                headers={"X-API-Key": SHUTDOWN_SECRET},
                json={},
            )
            self.status_bar.showMessage(resp.text)
            self.status_bar.repaint()
        except Exception as e:
            QMessageBox.warning(
                self,
                "Error",
                "Failed to shutdown Local Server." "\nMake Sure the Server is Up",
            )

    def shutdown_server(self):
        try:
            resp = requests.post(
                f"{self.api_url}/shutdown",
                headers={"X-API-Key": SHUTDOWN_SECRET},
                json={},
            )
            message = resp.text.replace("\n", "")
            message = message.replace("{", "")
            message = message.replace("}", "").lstrip()
            self.status_bar.showMessage(message)
            self.status_bar.repaint()
        except Exception as e:
            if "An existing connection was forcibly closed by the remote host" in str(
                e
            ):
                self.status_bar.showMessage("Remote server successfully Shut Down!")
            else:
                QMessageBox.warning(
                    self,
                    "Error",
                    f"Failed to shutdown Remote Server @ "
                    f"{self.api_url}:\nMake Sure the Server is Up",
                )

    def save_current_playlist(self):
        if not self.playlist:
            QMessageBox.information(self, "Playlists", "No current queue to save.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Current Playlist",
            "",
            "Jason Files (*.json);;Playlist Files (*.m3u8);;All Files (*)",
        )
        if path.endswith("json"):
            pl = []
            for song in self.playlist:
                jsong = {
                    "is_remote": song.is_remote,
                    "item_type": song.item_type,
                    "display_text": song.display_text,
                    "route": song.route,
                    "path": song.path,
                    "server": song.server,
                }
                pl.append(jsong)
            with open(path, "w") as f:
                json.dump(pl, f, indent=4)
        else:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    for item in self.playlist:
                        f.write(item.path + "\n")
                    f.write("# Playlist created with EcoG's Ultimate Audio Player")
                self.status_bar.showMessage(f"Saved: {path}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not save file:\n{str(e)}")

    def show_instructions(self):
        self.instructions = TextEdit()
        if self.dark_style == "dark":
            self.instructions.setStyleSheet(
                "font-size: 12px; color: white; background: #19232D; color: white; border-width: 2px; border-color: #7A7EA8; border-style: inset;"
            )
        else:
            self.instructions.setStyleSheet(
                "font-size: 12px; background: lightyellow; border-width: 2px; border-color: #7A7EA8; border-style: inset;"
            )
        self.instructions.show()

    def show_about_dialog(self):
        QMessageBox.about(
            self,
            "About...",
            "<h3>Ultimate Audio Player</h3>"
            "<p>HiRes Audio Player / API Client</p>"
            "<p>Created with ❤️ by EcoG</p>"
            "<br><br>"
            "<font size=1>Icons by <a href='https://www.flaticon.com/authors/freepik' "
            "style='text-decoration: none; color: #0000FF;'>Freepik</a> "
            "from <a href='https://www.flaticon.com/' "
            "style='text-decoration: none; color: #0000FF;'>www.flaticon.com</a></font>",
        )

    def on_go(self):
        col = self.combo.currentText()
        q = self.search.text().strip()
        if q:
            self.is_local = False
            self.status_bar.showMessage(f"Searching for {col} {q}. Please Wait...")
            self.progress = QProgressBar()
            self.progress.setStyleSheet(
                "::chunk {background-color: magenta; width: 8px; margin: 0.5px;}"
            )
            self.progress.setRange(0, 0)  # Indeterminate progress
            self.status_bar.addPermanentWidget(self.progress)
            self.status_bar.update()
            self.search_tracks(col, q)

    def on_local(self):
        col = self.combo.currentText()
        q = self.search.text().strip()
        if q:
            self.is_local = True
            self.status_bar.showMessage(f"Searching for {col} {q}. Please Wait...")
            self.progress = QProgressBar()
            self.progress.setStyleSheet(
                "::chunk {background-color: magenta; width: 8px; margin: 0.5px;}"
            )
            self.progress.setRange(0, 0)  # Indeterminate progress
            self.status_bar.addPermanentWidget(self.progress)
            self.status_bar.update()
            self.search_tracks(col, q)

    def get_album_art(self, path):
        img_data = None
        try:
            audio = MediaFile(path)
            if audio is not None and hasattr(audio, "tags"):
                tags = audio.tags
                if "APIC:" in tags:
                    img_data = tags["APIC:"].data
                elif hasattr(tags, "get") and tags.get("covr"):
                    img_data = tags["covr"][0]
                elif hasattr(audio, "pictures") and audio.pictures:
                    img_data = audio.pictures[0].data
            if img_data:
                try:
                    album_art = base64.b64encode(img_data).decode("utf-8")
                except Exception as e:
                    QMessageBox.warning(
                        self, "Error", f"Error encoding album art: {str(e)}"
                    )
                    album_art = None
                return album_art
        except Exception as e:
            self.status_bar.showMessage("Artwork extraction error:" + str(e))

    def search_tracks(self, column: str, query: str):
        if not column or not query:
            QMessageBox.warning(self, "Error", "Missing search parameters")
            return
        query = query.lower().replace('"', '""')
        if self.is_local:
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                # First try exact match
                if column == "song_title":
                    # If searching by song, include album_artist in the query
                    if " - " in query and len(query) > 3:
                        self.status_bar.showMessage(
                            "Searching by song artist and title..."
                        )
                        cursor.execute(
                            f"SELECT id, artist, song_title, album, path, file_name, album_artist FROM Songs WHERE artist LIKE ? AND song_title LIKE ?",
                            (
                                f'%{query.split(" - ")[0]}%',
                                f'%{query.split(" - ")[1]}%',
                            ),
                        )
                    else:
                        cursor.execute(
                            f"SELECT id, artist, song_title, album, path, file_name, album_artist FROM Songs WHERE song_title LIKE ?",
                            (f"%{query}%",),
                        )
                elif column == "album":
                    # If searching by album, include album_artist in the query
                    if " - " in query and len(query) > 3:
                        self.status_bar.showMessage(
                            "Searching by album artist and album title..."
                        )
                        cursor.execute(
                            f"SELECT id, artist, song_title, album, path, file_name, album_artist FROM Songs WHERE album_artist LIKE ? AND album LIKE ?",
                            (
                                f'%{query.split(" - ")[0]}%',
                                f'%{query.split(" - ")[1]}%',
                            ),
                        )
                    else:
                        cursor.execute(
                            f"SELECT id, artist, song_title, album, path, file_name, album_artist FROM Songs WHERE album LIKE ?",
                            (f"%{query}%",),
                        )
                else:
                    # column = artist
                    cursor.execute(
                        f"SELECT id, artist, song_title, album, path, file_name, album_artist FROM Songs WHERE artist LIKE ?",
                        (f"%{query}%",),
                    )
                results = cursor.fetchall()

                # If no results, try fuzzy matching
                if not results:
                    self.status_bar.showMessage("No exact matches, trying fuzzy search")
                    cursor.execute(
                        f"SELECT id, artist, song_title, album, path, file_name, album_artist, {column} FROM Songs"
                    )
                    all_songs = cursor.fetchall()

                    fuzzy_matches = []
                    for song in all_songs:
                        try:
                            ratio = fuzz.ratio(query.lower(), song[7].lower())
                            if ratio > 60:  # Threshold for fuzzy matching
                                fuzzy_matches.append((song[:7], ratio))
                        except Exception as e:
                            self.status_bar.showMessage(
                                f"Error in fuzzy matching for song {song[0]}: {e}"
                            )

                    # Sort by similarity
                    fuzzy_matches.sort(key=lambda x: x[1], reverse=True)
                    results = [
                        match[0] for match in fuzzy_matches[:10]
                    ]  # Top 10 matches

                conn.close()
                self.status_bar.showMessage(f"Search returned {len(results)} results")
            except sqlite3.Error as e:
                QMessageBox.critical(
                    self, "Error", f"Database error searching songs: {str(e)}"
                )
                return
            try:
                search_results = []
                for r in results:
                    search_result = {
                        "id": r[0],
                        "artist": r[1],
                        "title": r[2],
                        "album": r[3],
                        "path": r[4],
                        "filename": r[5],
                        "album_artist": r[6],
                    }
                    if search_result:
                        search_results.append(search_result)
                albums = []
                songs = {}
                for s in search_results:
                    album = s["album"]
                    album_artist = s["album_artist"]
                    if album not in albums:
                        albums.append(album)
                        songs[album] = []
                    songs[album].append(s)
                covers = {}
                conn = sqlite3.connect(COVERS_DB_PATH)
                cursor = conn.cursor()
                for album in enumerate(albums):
                    album_artist = songs[album[1]][0]["album_artist"]
                    path = songs[album[1]][0]["path"]
                    if album[1].find('"') != -1:
                        album_art = self.get_album_art(path)
                    else:
                        cursor.execute(
                            f'SELECT cover FROM Covers WHERE album = "{album[1]}" AND album_artist = "{album_artist}"'
                        )
                        album_art = cursor.fetchone()
                        if album_art is None:
                            album_art = self.get_album_art(path)
                        elif isinstance(album_art, tuple):
                            album_art = album_art[0]
                        else:
                            print(album_art, r[4])
                    covers[album[1]] = album_art
                conn.close()
                self.on_search_completed({"search_result": (covers, songs)})
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Search Error: {str(e)}")
                # Remove progress bar and clear status
            if self.progress:
                self.status_bar.removeWidget(self.progress)
            self.status_bar.clearMessage()
        else:  # Remote search
            params = {"column": column, "query": query}
            url = f"{self.api_url}/search_songs"

            # Create and configure worker thread
            self.search_worker = Worker(params, url)
            self.search_worker.work_completed.connect(self.on_search_completed)
            self.search_worker.work_error.connect(self.on_search_error)
            self.search_worker.finished.connect(self.cleanup_search)

            # Start the async operation
            self.search_worker.start()
            self.search_worker.mutex.lock()

    def on_search_completed(self, result):
        if self.search_worker:
            is_remote = True
            self.search_worker.mutex.unlock()
        else:
            is_remote = False
        self.status_bar.clearMessage()
        data = result["search_result"]
        if "error" in data:
            QMessageBox.critical(self, "Error", data["error"])
            return
        if data:
            self.clear_playlist()
            if is_remote:
                albums = []
                songs = {}
                for s in data:
                    album = s["album"]
                    if album not in albums:
                        albums.append(album)
                        songs[album] = []
                    songs[album].append(s)
            else:
                covers = data[0]
                songs = data[1]

            for album in songs.keys():
                if is_remote:
                    album_art = songs[album][0]["album_art"]
                else:
                    album_art = covers[album]
                album_songs = songs[album]
                album_artist = album_songs[0]["album_artist"]
                if self.sort_albums:
                    self.add_album(album_art, album_artist, album)
                for track in album_songs:
                    song = ListItem()
                    song.is_remote = is_remote
                    song.item_type = "song_title"  # or self.combo.currentText()
                    song.path = track["path"]
                    song.display_text = (
                        f"{track['artist']} - {track['title']} ({track['album']})"
                    )
                    if not song.is_remote and song.path:
                        if not self._validate_mp3_for_load(song.path):
                            continue
                    self.playlist.append(song)
                    item = QListWidgetItem(song.display_text)
                    self.playlist_widget.addItem(item)
        else:
            col = self.combo.currentText()
            q = self.search.text().strip()
            self.status_bar.showMessage(f"{col} {q} was not found on Server")
            QMessageBox.information(
                self, "Sorry 😞", f"{col} {q} was not found on Server"
            )

    def on_search_error(self, error_message):
        """Handle search error"""
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()

    def cleanup_search(self):
        """Clean up after search completion"""
        # Remove progress bar and clear status
        if self.progress:
            self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()

        # Clean up worker reference
        if self.search_worker:
            self.search_worker.deleteLater()
            self.search_worker = None

    def do_shuffle(self):
        if self.playlist and len(self.playlist) > 1:
            self.playlist = [
                song
                for song in self.playlist
                if not isinstance(song, QListWidgetItem) and song.item_type != "cover"
            ]
            shuffle(self.playlist)
            self.playlist_widget.clear()
            self.current_index = -1
            for song in self.playlist:
                item = QListWidgetItem(song.display_text)
                self.playlist_widget.addItem(item)

    def do_sort(self):
        if self.playlist and len(self.playlist) > 1:
            self.playlist = [
                song
                for song in self.playlist
                if not isinstance(song, QListWidgetItem) and song.item_type != "cover"
            ]
            self.playlist.sort(key=lambda x: x.display_text)

            self.playlist_widget.clear()
            self.current_index = -1
            for song in self.playlist:
                item = QListWidgetItem(song.display_text)
                self.playlist_widget.addItem(item)

    # --- Mixing/transition config slots ---

    def detect_low_intensity_segments(
        self, audio_path, threshold_db=-46, frame_duration=0.1
    ):
        # Load audio file
        y, sr = librosa.load(audio_path, sr=None)
        duration = librosa.get_duration(y=y, sr=sr)
        time_in_audio = 0

        # Focus on the last 10 seconds
        if duration < 10:
            self.status_bar.showMessage("Audio is shorter than 10 seconds.")
            start_sample = 0
        else:
            start_sample = int((duration - 10) * sr)
        y_last10 = y[start_sample:]

        # Frame analysis
        frame_length = int(frame_duration * sr)
        hop_length = frame_length
        num_frames = int(len(y_last10) / hop_length)

        for i in range(num_frames):
            start = i * hop_length
            end = start + frame_length
            frame = y_last10[start:end]

            # Avoid empty frames
            if len(frame) == 0:
                continue

            rms = np.sqrt(np.mean(frame**2))
            db = 20 * np.log10(rms + 1e-10)  # Avoid log(0)

            if db < threshold_db:
                time_in_audio = (start_sample + start) / sr
                break
        transition_duration = duration - time_in_audio
        if time_in_audio <= 0:
            transition_duration = 0.1  # Minimum transition duration

        return transition_duration

    def set_mix_method(self, method):
        self.mix_method = method

    def set_transition_duration(self, val):
        self.transition_duration = val
        self.transition_spin.setValue(int(self.transition_duration))

    def set_skip_silence(self, val):
        self.skip_silence = val

    # --- Mixing logic ---
    def check_for_mix_transition(self, position):
        """Trigger mix/cue if current track is close to ending."""
        duration = self.player.duration()
        if duration <= 0 or self.current_index >= len(self.playlist) - 1:
            return

        if duration - position <= self.transition_duration * 1000:
            if not hasattr(self, "_mixing_next") or not self._mixing_next:
                self._mixing_next = True
                # Dispatch to correct crossfade mode
                if self.mix_method == "Auto":
                    self.start_fade_to_next(mode="auto")
                elif self.mix_method == "Fade":
                    self.start_fade_to_next(mode="fade")
                elif self.mix_method == "Smooth":
                    self.start_fade_to_next(mode="smooth")
                elif self.mix_method == "Full":
                    self.start_fade_to_next(mode="full")
                elif self.mix_method == "Scratch":
                    self.start_fade_to_next(mode="scratch")
                else:
                    self.cue_next_track()
        else:
            self._mixing_next = False

    def start_fade_to_next(self, mode="auto"):
        """Perform the selected crossfade mode when transitioning."""
        next_idx = self.current_index + 1
        next_path = self.playlist[next_idx]
        if self._uses_vlc_for_path(next_path.path):
            # disable complex crossfade for VLC; schedule cue instead
            self.cue_next_track()
            return
        if not (0 <= next_idx < len(self.playlist)):
            return
        next_song = self.playlist[next_idx]
        while next_song.item_type != "song_title":
            next_idx += 1
            if not (0 <= next_idx < len(self.playlist)):
                return
            next_song = self.playlist[next_idx]
        if next_song.is_remote:
            next_song.route = "serve_audio"

        self.next_player = QMediaPlayer()
        self.next_output = QAudioOutput()
        self.next_player.setAudioOutput(self.next_output)
        self.next_player.setSource(next_song.absolute_path())
        #        self.next_player.setSource(QUrl.fromLocalFile(next_path))
        self.next_output.setVolume(0)
        self.slider.setValue(0)
        #   log_player_action("play", self.player)
        self.next_player.play()
        # self.load_lyrics(next_path)
        self.lyrics_timer.start()
        self.playlist_widget.setCurrentRow(next_idx)
        self.fade_timer = QTimer()
        self.fade_timer.setInterval(100)
        fade_steps = max(1, int(self.transition_duration * 1000 / 100))
        self._fade_step = 0

        def fade():
            global old_player
            self._fade_step += 1
            #   print(self._fade_step, fade_steps)
            frac = self._fade_step / fade_steps

            if mode == "auto":
                # Next track starts at full volume, old does not fade out
                self.audio_output.setVolume(1.0)
                self.next_output.setVolume(1.0)
            elif mode == "fade":
                # Linear fade out/in
                self.audio_output.setVolume(max(0, 1.0 - frac))
                self.next_output.setVolume(min(1.0, frac))
            elif mode == "smooth":
                # S-curve fade for less abrupt transitions
                import math

                curve = (1 - math.cos(frac * math.pi)) / 2  # S-curve 0...1
                self.audio_output.setVolume(max(0, 1.0 - curve))
                self.next_output.setVolume(min(1.0, curve))
            elif mode == "full":
                # Next track starts at full volume, old fades out
                self.audio_output.setVolume(max(0, 1.0 - frac))
                self.next_output.setVolume(1.0)
            elif mode == "scratch":
                # Simulate a DJ "scratch" by jumping next track to a cue point and hard-cutting
                # (For demo: jump to 1s in, quick fade, then cut)
                if self._fade_step == 1:
                    self.next_player.setPosition(1000)  # start 1s in
                if frac < 0.5:
                    self.audio_output.setVolume(max(0, 1.0 - 2 * frac))
                    self.next_output.setVolume(0.0)
                else:
                    self.audio_output.setVolume(0.0)
                    self.next_output.setVolume(1.0)
            else:
                # Default to auto
                self.audio_output.setVolume(1.0)
                self.next_output.setVolume(1.0)

            if self._fade_step >= fade_steps:
                #  Fade complete, switching tracks
                self.fade_timer.stop()
                #  Ensure old player is stopped and safely deleted
                old_player = getattr(self, "player", None)
                old_output = getattr(self, "audio_output", None)

                # Stop the old player from main thread (safe)
                if old_player is not None:
                    try:
                        old_player.stop()
                    #   log_player_action("stop", self.player)
                    except Exception:
                        pass
                # self.audio_output.setVolume(1.0)
                # self.player.stop()
                if old_player is not None:
                    try:
                        old_player.positionChanged.disconnect(self.update_slider)
                    except Exception:
                        pass
                    try:
                        old_player.durationChanged.disconnect(self.update_duration)
                    except Exception:
                        pass
                    try:
                        old_player.mediaStatusChanged.disconnect(
                            self.media_status_changed
                        )
                    except Exception:
                        pass
                    try:
                        old_player.playbackStateChanged.disconnect(
                            self.update_play_button
                        )
                    except Exception:
                        pass
                    try:
                        old_player.errorOccurred.disconnect(self.handle_error)
                    except Exception:
                        pass
                    try:
                        old_player.positionChanged.disconnect(
                            self.check_for_mix_transition
                        )
                    except Exception:
                        pass
                    # Switch to next player
                    self.player = self.next_player
                    self.audio_output = self.next_output

                self.player.positionChanged.connect(
                    self.update_slider, type=Qt.AutoConnection
                )
                self.player.durationChanged.connect(
                    self.update_duration, type=Qt.AutoConnection
                )
                self.player.mediaStatusChanged.connect(
                    self.media_status_changed, type=Qt.AutoConnection
                )
                self.player.playbackStateChanged.connect(
                    self.update_play_button, type=Qt.AutoConnection
                )
                self.player.errorOccurred.connect(
                    self.handle_error, type=Qt.AutoConnection
                )
                self.player.positionChanged.connect(
                    self.check_for_mix_transition, type=Qt.AutoConnection
                )

                if old_player is not None:
                    # make sure deletion runs in the object's thread (main thread) using deleteLater()
                    try:
                        old_player.deleteLater()
                    except Exception:
                        pass
                if old_output is not None:
                    try:
                        old_output.deleteLater()
                    except Exception:
                        pass

                # Clear the temporary next references
                self.next_player = None
                self.next_output = None
                self._mixing_next = False
                if not self.meta_worker:
                    self.update_metadata(next_idx)
                else:
                    self.song_index = next_idx
                self.current_index = next_idx
                self.update_play_button()
                self.playlist_widget.setCurrentRow(self.current_index)

        # connect and start the timer in main thread
        self.fade_timer.timeout.connect(fade, type=Qt.AutoConnection)
        self.fade_timer.start()

    def cue_next_track(self):
        """
        Schedule the next track to play after the current one finishes,
        without interrupting current playback.
        """
        next_idx = self.current_index + 1
        next_path = self.playlist[next_idx]
        while next_path == "None":
            next_idx += 1
            if not (0 <= next_idx < len(self.playlist)):
                return
            next_path = self.playlist[next_idx]
        if not (0 <= next_idx < len(self.playlist)):
            return
        # Set a flag to cue the next track at end of media
        self._cue_next = next_idx

    def is_local_file(self, path):
        # Returns True if the file is a local file, False if it's a remote URL
        return os.path.isfile(path)

    def get_media_source(self, path):
        # Returns a QUrl for the media source (local or remote)
        if self.is_local_file(path):
            return QUrl.fromLocalFile(path)
        elif self.remote_base:
            # Assume path is a filename, construct full URL
            filename = os.path.basename(path)
            return QUrl(f"{self.remote_base}/{filename}")
        else:
            # Already a URL
            return QUrl(path)

    def load_track(self, idx, auto_play=True):
        if 0 <= idx < len(self.playlist):
            file = self.playlist[idx]
            if file.item_type != "song_title":
                idx += 1
                if 0 <= idx < len(self.playlist):
                    file = self.playlist[idx]
                    self.playlist_widget.setCurrentRow(idx)
                else:
                    return
            if not file.is_remote and file.path:
                if not self._validate_mp3_for_load(file.path):
                    return
            # path = file.path
            self.current_index = idx
            if file.is_remote:
                file.route = "serve_audio"
            media_url = file.absolute_path()

            if self.vlc_helper and self.vlc_helper.is_playing():
                self.vlc_helper.stop()
            # Determine fallback
            if self._uses_vlc_for_path(file.path):
                # use VLC fallback
                self._start_vlc_play(file, idx)
            else:
                # codec_context.pkt_timebase = media.time_base
                self.player.setSource(media_url)
                self.player.play()
                self.playlist_widget.setCurrentRow(idx)
                self.update_play_button()
            self.slider.setValue(0)
            self.lyrics_timer.start()
            if not self.meta_worker:
                self.update_metadata(idx)
            else:
                self.song_index = idx
        else:
            self.title_label.setText("No Track Loaded")
            self.artist_label.setText("--")
            self.album_label.setText("--")
            self.year_label.setText("--")
            self.codec_label.setText("--")
            self.album_art.setPixmap(QPixmap())
            self.lyrics_display.clear()
            self.lyrics_timer.stop()

    # Drag-and-drop support
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        songs = []

        for track in files:
            if os.path.isdir(track):
                self.load_dir(track)
            else:
                song = ListItem()
                ext = Path(track).suffix.lower()
                if ext in audio_extensions:
                    song.item_type = "song_title"
                    song.display_text = self.get_basic_metadata(track)
                elif ext in playlist_extensions:
                    song.item_type = "playlist"
                    song.display_text = os.path.basename(track)
                else:
                    continue
                song.path = track
                song.is_remote = False
                songs.append(song)
        self.add_files(songs)

    def eventFilter(self, source, event):
        if source == self.playlist_widget.viewport() and event.type() == QEvent.Drop:
            files = [u.toLocalFile() for u in event.mimeData().urls()]
            self.add_files(files)
            return True
        return super().eventFilter(source, event)

    def get_basic_metadata(self, file_path):
        song_title = os.path.basename(file_path)
        artist = "Unknown Artist"
        album = "Unknown Album"
        try:
            file = MediaFile(file_path)
            if file is None:
                self.status_bar.showMessage(
                    f"Could not read audio file: {file_path}. Make sure the file exists."
                )
                return None

            # Get basic metadata
            song_title = file.title
            artist = file.artist
            album = file.album

        except Exception as e:
            print(f"Error extracting metadata from {file_path}: {str(e)}")

        return f"{artist} - {song_title} ({album})"

    def _parse_itunsmpb(self, value):
        parts = str(value).split()
        if len(parts) < 3:
            return None
        try:
            header_skipped = int(parts[1], 16)
            tail_skipped = int(parts[2], 16)
        except ValueError:
            return None
        return header_skipped, tail_skipped

    def _ffmpeg_has_skipped_samples(self, file_path):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return False

        def _run_segment(args):
            try:
                result = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
            except Exception:
                return False
            stderr = result.stderr or ""
            return "skipped samples" in stderr.lower()

        header_args = [
            ffmpeg,
            "-hide_banner",
            "-v",
            "warning",
            "-ss",
            "0",
            "-t",
            "1",
            "-i",
            file_path,
            "-f",
            "null",
            "-",
        ]
        tail_args = [
            ffmpeg,
            "-hide_banner",
            "-v",
            "warning",
            "-sseof",
            "-1",
            "-t",
            "1",
            "-i",
            file_path,
            "-f",
            "null",
            "-",
        ]
        return _run_segment(header_args) or _run_segment(tail_args)

    def _get_mp3_skipped_samples(self, file_path):
        try:
            audio = MP3(file_path)
            info = audio.info
        except Exception as e:
            self.status_bar.showMessage(
                f"MP3 validation failed for {os.path.basename(file_path)}: {e}"
            )
            return None
        header_skipped = int(getattr(info, "encoder_delay", 0) or 0)
        tail_skipped = int(getattr(info, "encoder_padding", 0) or 0)
        if header_skipped > 0 or tail_skipped > 0:
            return header_skipped, tail_skipped

        try:
            tags = ID3(file_path)
        except Exception:
            return header_skipped, tail_skipped

        if "TXXX:ENC_DELAY" in tags:
            try:
                header_skipped = int(str(tags["TXXX:ENC_DELAY"].text[0]))
            except Exception:
                pass
        if "TXXX:ENC_PADDING" in tags:
            try:
                tail_skipped = int(str(tags["TXXX:ENC_PADDING"].text[0]))
            except Exception:
                pass
        if header_skipped > 0 or tail_skipped > 0:
            return header_skipped, tail_skipped

        if "TXXX:iTunSMPB" in tags:
            parsed = self._parse_itunsmpb(tags["TXXX:iTunSMPB"].text[0])
            if parsed:
                return parsed

        return header_skipped, tail_skipped

    def _validate_mp3_for_load(self, file_path):
        if Path(file_path).suffix.lower() != ".mp3":
            return True
        skipped = self._get_mp3_skipped_samples(file_path)
        if skipped is None:
            return True
        header_skipped, tail_skipped = skipped
        if header_skipped > 0 or tail_skipped > 0:
            self.status_bar.showMessage(
                "Skipping MP3 with skipped samples "
                f"(header={header_skipped}, tail={tail_skipped}): "
                f"{os.path.basename(file_path)}"
            )
            return False
        if self._ffmpeg_has_skipped_samples(file_path):
            self.status_bar.showMessage(
                "Skipping MP3 with skipped samples detected by ffmpeg: "
                f"{os.path.basename(file_path)}"
            )
            return False
        return True

    def show_playlist_menu(self, pos=None):
        menu = QFileDialog(self)
        menu.setFileMode(QFileDialog.ExistingFiles)
        menu.setNameFilters(
            [
                "Audio files (*.mp3 *.flac *.ogg *.wav *.m4a *.aac *.wma *.opus)",
                "Playlists (*.m3u *.m3u8 *.cue *.json)",
                "All files (*)",
            ]
        )
        if menu.exec():
            songs = []
            for track in menu.selectedFiles():
                if os.path.isdir(track):
                    self.load_dir(track)
                else:
                    song = ListItem()
                    ext = Path(track).suffix.lower()
                    if ext in audio_extensions:
                        song.item_type = "song_title"
                        song.display_text = self.get_basic_metadata(track)
                    elif ext in playlist_extensions:
                        song.item_type = "playlist"
                        song.display_text = os.path.basename(track)
                    else:
                        continue
                    song.path = track
                    song.is_remote = False
                    songs.append(song)
            self.add_files(songs)

    def add_files(self, files):
        if self.progress:
            self.status_bar.removeWidget(self.progress)
        self.progress = QProgressBar()
        self.progress.setStyleSheet(
            "::chunk {background-color: green; width: 8px; margin: 0.5px;}"
        )
        self.progress.setRange(0, 0)  # Indeterminate progress
        self.status_bar.addPermanentWidget(self.progress)
        self.status_bar.showMessage("adding files")
        self.status_bar.update()
        self.status_bar.showMessage("Now adding the files. Please Wait...")
        for f in files:
            if f.item_type == "playlist":  # if os.path.isfile(f):
                ext = Path(f.path).suffix.lower()
                if ext in [".m3u", ".m3u8"]:
                    pl = self.load_m3u_playlist(f.path)
                    self.playlist += pl
                    for i in pl:
                        item = QListWidgetItem(
                            i.display_text
                        )  # QListWidgetItem(os.path.basename(i))
                        self.playlist_widget.addItem(item)
                    self.playlist_label.setText(f"Playlist: {f.display_text}")
                elif ext == ".cue":
                    pl = self.load_cue_playlist(f.path)
                    self.playlist += pl
                    for i in pl:
                        item = QListWidgetItem(os.path.basename(i.display_text))
                        self.playlist_widget.addItem(item)
                    self.playlist_label.setText(
                        f"Playlist: {os.path.basename(f.display_text)}"
                    )
                elif ext == ".json":
                    pl = self.load_json_playlist(f.path)
                    self.playlist += pl
                    for i in pl:
                        item = QListWidgetItem(
                            i.display_text
                        )  # QListWidgetItem(os.path.basename(i))
                        self.playlist_widget.addItem(item)
                    self.playlist_label.setText(f"Playlist: {f.display_text}")
                else:
                    QMessageBox.warning(
                        self, "Error!", f"Unsupported playlist format: {ext}"
                    )
                    continue
            elif (
                f.item_type == "song_title"
                or f.item_type == "artist"
                or f.item_type == "album"
            ):  # if ext in audio_extensions:
                if f.item_type == "song_title" and f.path:
                    if not self._validate_mp3_for_load(f.path):
                        continue
                self.playlist.append(f)
                item = QListWidgetItem(
                    f.display_text
                )  # item = QListWidgetItem(os.path.basename(f))
                self.playlist_widget.addItem(item)
            elif f.item_type == "directory":  # os.path.isdir(f):
                self.load_dir(f)
            self.status_bar.update()
        if self.progress:
            self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()
        self.status_bar.update()
        if self.playlist:
            if self.current_index == -1 and self.playlist[-1].item_type == "song_title":
                self.load_track(0)
        else:
            QMessageBox.warning(
                self, "Error!", "No valid audio files found in selection."
            )

    def load_m3u_playlist(self, path):
        songs = []
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            # Try with ANSI encoding if UTF-8 fails
            try:
                with open(path, "r", encoding="ANSI") as f:
                    lines = f.readlines()
            except UnicodeDecodeError:
                try:
                    # Try to guess the encoding if UTF-8 and ANSI fail
                    from charset_normalizer import from_path

                    result = from_path(path).best()
                    with open(path, "r", encoding=result.encoding) as f:
                        lines = f.readlines()
                except Exception as e:
                    QMessageBox.critical(self, "Error!", str(e))
                    return songs
        if lines:
            for line in lines:
                line = line.strip()
                if not os.path.isabs(line):
                    line = os.path.abspath(os.path.join(os.path.dirname(path), line))
                if os.path.isfile(line):
                    if not self._validate_mp3_for_load(line):
                        continue
                    audio = MediaFile(line)
                else:
                    audio = None
                if not line or not audio:
                    continue
                song = ListItem()
                song.item_type = "song_title"
                song.display_text = self.get_basic_metadata(line)
                song.path = line
                song.is_remote = False
                songs.append(song)
        return songs

    def load_cue_playlist(self, path):
        songs = []
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            # Try with ANSI encoding if UTF-8 fails
            try:
                with open(path, "r", encoding="ANSI") as f:
                    lines = f.readlines()
            except UnicodeDecodeError:
                try:
                    # Try to guess the encoding if UTF-8 and ANSI fail
                    from charset_normalizer import from_path

                    result = from_path(path).best()
                    with open(path, "r", encoding=result.encoding) as f:
                        lines = f.readlines()
                except Exception as e:
                    QMessageBox.critical(self, "Error!", str(e))
                    return songs
        if lines:
            for line in lines:
                if re.match("^FILE .(.*). (.*)$", line):
                    file_path = line[6:-7]
                    if not os.path.isabs(file_path):
                        file_path = os.path.abspath(
                            os.path.join(os.path.dirname(path), file_path)
                        )
                    if not self._validate_mp3_for_load(file_path):
                        continue
                    song = ListItem()
                    song.item_type = "song_title"
                    song.path = file_path
                    song.is_remote = False
                    song.display_text = os.path.basename(file_path)
                    songs.append(song)
        return songs

    def load_json_playlist(self, path):
        songs = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for entry in data:
                song = ListItem()
                song.is_remote = entry.get("is_remote", False)
                song.item_type = entry.get("item_type", "song_title")
                song.display_text = entry.get(
                    "display_text", os.path.basename(entry.get("path", "Unknown"))
                )
                song.route = entry.get("route", "")
                song.path = entry.get("path", "")
                song.server = entry.get("server", "")
                if (
                    song.item_type == "song_title"
                    and not song.is_remote
                    and song.path
                    and not self._validate_mp3_for_load(song.path)
                ):
                    continue
                songs.append(song)
        except Exception as e:
            QMessageBox.critical(
                self, "Error!", f"Error loading JSON playlist: {str(e)}"
            )
        return songs

    def load_dir(self, directory):
        scan_errors = 0
        songs = []
        for root, dirs, files in os.walk(directory):
            for file in files:
                try:
                    file_path = os.path.join(root, file)
                    ext = Path(file).suffix.lower()
                    song = ListItem()
                    if ext in audio_extensions:
                        if not self._validate_mp3_for_load(file_path):
                            continue
                        song.item_type = "song_title"
                        song.display_text = self.get_basic_metadata(file_path)
                    elif ext in playlist_extensions:
                        song.item_type = "playlist"
                        song.display_text = os.path.basename(file)
                    else:
                        continue
                    song.path = file_path
                    song.is_remote = False
                    songs.append(song)
                except Exception as e:
                    QMessageBox.critical(
                        self, "Error!", f"Error processing file {file}: {e}"
                    )
                    scan_errors += 1
        self.status_bar.showMessage(f"Scan complete. Found {len(songs)} files ")
        if scan_errors > 0:
            QMessageBox.critical(
                self,
                "Error!",
                f"Encountered {scan_errors} errors during directory scanning",
            )

        self.add_files(songs)

    def add_albums(self, albums):
        if self.progress:
            self.status_bar.removeWidget(self.progress)
        self.progress = QProgressBar()
        self.progress.setStyleSheet(
            "::chunk {background-color: green; width: 8px; margin: 0.5px;}"
        )
        self.progress.setRange(0, 0)  # Indeterminate progress
        self.status_bar.addPermanentWidget(self.progress)
        self.status_bar.showMessage("adding albums")
        self.status_bar.update()
        self.status_bar.showMessage(
            "Songs found, now shorting them in Albums. Please Wait..."
        )
        for album in albums:
            self.add_album(album)
            for song in albums[album]:
                self.playlist.append(song)
                item = QListWidgetItem(song.display_text)
                self.playlist_widget.addItem(item)
            self.status_bar.update()
        if self.progress:
            self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()
        self.status_bar.update()

        if self.current_index == -1 and self.playlist:
            self.load_track(0)

    def add_album(self, data, album_artist=None, album=None):
        #  if 0 > self.current_index >= len(self.playlist) - 1:
        #   return
        if not data:
            self.status_bar.showMessage("Metadata fetch error:")
            return
        #    self.album_meta_data = data[0]
        item = QListWidgetItem()
        item.setSizeHint(QSize(256, 256))
        self.playlist_widget.addItem(item)
        self.album_only_art = QLabel()
        self.album_only_art.setFixedSize(256, 256)
        self.album_only_art.setScaledContents(True)
        self.playlist_widget.setItemWidget(item, self.album_only_art)
        cover = ListItem()
        cover.item_type = "cover"
        cover.display_text = f"{album_artist} - {album}"
        self.playlist.append(cover)
        try:
            if data != "":
                img_bytes = base64.b64decode(data)
                img = QImage.fromData(img_bytes)
                pix = QPixmap.fromImage(img)
                self.album_only_art.setPixmap(
                    pix.scaled(
                        self.album_art.size(),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
            else:
                self.album_only_art.setPixmap(
                    QPixmap("static/images/default_album_art.png")
                    if os.path.exists("static/images/default_album_art.png")
                    else QPixmap()
                )
            return
        except Exception as e:
            self.album_only_art.setPixmap(
                QPixmap("static/images/default_album_art.png")
                if os.path.exists("static/images/default_album_art.png")
                else QPixmap()
            )
            self.status_bar.showMessage("Base64 album art decode error:" + str(e))

    def play_selected_track(self, item):
        idx = self.playlist_widget.row(item)
        self.load_track(idx)

    def show_playlist_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self.playlist_widget)
        menu.setStyleSheet(
            "background-color: lightGrey; border-color: darkGray; "
            "border-width: 2px; border-style: outset;"
        )
        scan_action = menu.addAction("Scan Library")
        get_action = menu.addAction("Load Playlists")
        add_action = menu.addAction("Add Files")
        remove_action = menu.addAction("Remove Selected")
        clear_action = menu.addAction("Clear Playlist")
        action = menu.exec(self.playlist_widget.mapToGlobal(pos))
        if action == scan_action:
            self.scan_library()
        if action == get_action:
            self.get_playlists()
        if action == add_action:
            self.show_playlist_menu(pos)
        elif action == remove_action:
            self.remove_selected_item()
        elif action == clear_action:
            self.clear_playlist()

    def remove_selected_item(self):
        row = self.playlist_widget.currentRow()
        if row >= 0:
            self.playlist_widget.takeItem(row)
            del self.playlist[row]
            # Adjust current_index if necessary
            if row == self.current_index:
                self.player.stop()  # ("stop", self.player)
                self.player.setSource(self.empty)
                self.current_index = -1
                self.lyrics_display.clear()
                self.update_play_button()
            elif row < self.current_index:
                self.current_index -= 1

    def clear_playlist(self):
        self.playlist_widget.clear()
        self.playlist.clear()
        self.playlist_label.setText("Queue:")
        self.player.stop()
        self.player.setSource(self.empty)
        self.current_index = -1
        self.album_art.setPixmap(
            QPixmap("static/images/default_album_art.png")
            if os.path.exists("static/images/default_album_art.png")
            else QPixmap()
        )
        self.title_label.setText("Title --")
        self.artist_label.setText("Artist --")
        self.album_label.setText("Album --")
        self.year_label.setText("Year --")
        self.duration_label.setText("Duration --")
        self.codec_label.setText("Codec --")
        self.text.clear()
        self.lyrics_display.clear()
        self.update_play_button()

    def is_remote_file(self, path):
        return path.is_remote

    def set_album_art(self, file):
        """
        Sets album art using metadata JSON if provided (remote), otherwise falls back to local extraction.
        """
        if self.meta_data and "picture" in self.meta_data and self.meta_data["picture"]:
            if self.is_remote_file(file):
                img_bytes = base64.b64decode(self.meta_data["picture"])
            else:
                img_bytes = self.meta_data["picture"]
            try:
                img = QImage.fromData(img_bytes)
                pix = QPixmap.fromImage(img)
                self.album_art.setPixmap(
                    pix.scaled(
                        self.album_art.size(),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
                return
            except Exception as e:
                self.album_art.setPixmap(
                    QPixmap("static/images/default_album_art.png")
                    if os.path.exists("static/images/default_album_art.png")
                    else QPixmap()
                )
                self.status_bar.showMessage("Base64 album art decode error:" + str(e))
        else:
            # Fallback image
            self.album_art.setPixmap(
                QPixmap("static/images/default_album_art.png")
                if os.path.exists("static/images/default_album_art.png")
                else QPixmap()
            )
        return

    def load_lyrics(self, file):
        self.lyrics = SynchronizedLyrics(file)
        self.lyrics_display.set_lyrics(self.lyrics.lines, self.lyrics.is_synchronized())
        self.update_lyrics_display()

    def update_lyrics_display(self):
        if self.lyrics and self.lyrics.lines:
            idx = (
                self.lyrics.get_current_line(self.player.position())
                if self.lyrics.is_synchronized()
                else -1
            )
            self.lyrics_display.highlight_line(idx)
        else:
            self.lyrics_display.setText("No lyrics found.")

    def prev_track(self):
        if self.current_index > 0:
            prev_idx = self.current_index - 1
            prev_path = self.playlist[prev_idx]
            while prev_path == "None":
                prev_idx -= 1
                if not (0 <= prev_idx < len(self.playlist)):
                    return
                prev_path = self.playlist[prev_idx]
            if not (0 <= prev_idx < len(self.playlist)):
                return
            self.load_track(prev_idx)

    def next_track(self):
        if self.current_index < len(self.playlist) - 1:
            next_idx = self.current_index + 1
            next_path = self.playlist[next_idx].path
            while next_path == "":
                next_idx += 1
                if not (0 <= next_idx < len(self.playlist)):
                    return
                next_path = self.playlist[next_idx]
            if not (0 <= next_idx < len(self.playlist)):
                return
            # self.playlist_widget.setCurrentRow(next_idx)
            self.load_track(next_idx)

    def toggle_play_pause(self):
        if self.vlc_active:
            # Use VLC player's state
            if self.vlc_helper.is_playing():
                self.vlc_helper.pause()
            else:
                self.vlc_helper.resume()
        else:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
            else:
                self.player.play()

    def update_play_button(self):
        if self.sub_images:
            if self.vlc_active:
                playing = self.vlc_helper.is_playing() if self.vlc_helper else False
                pixmap = (
                    QPixmap.fromImage(self.sub_images[1])
                    if playing
                    else QPixmap.fromImage(self.sub_images[0])
                )
                self.play_button.setIcon(QIcon(pixmap))
                return
            # else QMediaPlayer path: existing code (unchanged)
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                pixmap = QPixmap.fromImage(self.sub_images[1])
            else:
                pixmap = QPixmap.fromImage(self.sub_images[0])
            self.play_button.setIcon(QIcon(pixmap))
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.play_button.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause)
            )
        else:
            self.play_button.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
            )

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key in (Qt.Key_MediaTogglePlayPause, 16777350):
            self.toggle_play_pause()
        elif key in (Qt.Key_MediaPrevious, 16777346):
            self.prev_track()
        elif key in (Qt.Key_MediaNext, 16777347):
            self.next_track()
        else:
            super().keyPressEvent(event)

    def update_slider(self, position):
        duration = self.player.duration()
        if duration > 0:
            value = int((position / duration) * 100)
            self.slider.blockSignals(True)
            self.slider.setValue(value)
            self.slider.blockSignals(False)
            # Call on_buffer if within last 10 seconds
        #      if duration - position <= 10000:
        #         self.on_buffer(self.buffer)
        self.update_time_label(position, duration)

    def on_slider_moved(self, value):
        self._slider_moving = True  # Mark that user is dragging

    def on_slider_released(self):
        if self._slider_moving:
            duration = self.player.duration()
            value = self.slider.value()
            if duration > 0:
                new_position = int((value / 100) * duration)
                self.player.setPosition(new_position)
        self._slider_moving = False

    def update_duration(self, duration):
        self.slider.setEnabled(duration > 0)
        self.update_time_label(self.player.position(), duration)

    def seek_position(self, value):
        duration = self.player.duration()
        if duration > 0:
            new_position = int((value / 100) * duration)
            self.player.setPosition(new_position)

    def update_time_label(self, position, duration):
        if self.show_remaining:
            remaining = max(0, duration - position)
            self.time_label.setText("-" + self.format_time(remaining))
        else:
            self.time_label.setText(self.format_time(position))

    def toggle_time_display(self):
        self.show_remaining = not self.show_remaining
        self.update_time_label(self.player.position(), self.player.duration())

    def media_status_changed(self, status):
        if status == QMediaPlayer.EndOfMedia:
            # If a cue_next was scheduled, play that track
            if hasattr(self, "_cue_next") and self._cue_next is not None:
                next_idx = self._cue_next
                self._cue_next = None
                self.load_track(next_idx)
        #    else:
        #       self.next_track()

    def handle_error(self, error, error_string):
        self.player.errorOccurred.disconnect(self.handle_error)
        if error != QMediaPlayer.NoError:
            if (
                QMessageBox.question(
                    self,
                    "Error!",
                    "Playback Error: " + error_string + " Continue to next track?",
                )
                == QMessageBox.Yes
            ):
                self.next_track()
            else:
                self.clear_playlist()
        self.player.errorOccurred.connect(self.handle_error)

        # self.update_play_button()

    def _uses_vlc_for_path(self, path: str) -> bool:
        # determine if path should use VLC fallback
        if not VLC_AVAILABLE:
            return False
        ext = Path(path).suffix.lower()
        return ext in problematic_exts

    def _stop_vlc(self):
        if self.vlc_helper and self.vlc_active:
            try:
                self.vlc_helper.stop()
            except Exception:
                pass
            self.vlc_active = False

    def _start_vlc_play(self, file: ListItem, idx: int):
        # stop QMediaPlayer if it's active
        try:
            self.player.stop()
            self.player.setSource(self.empty)
            self.cleanup_metadata()
        except Exception as e:
            print(str(e))
            pass
        # path = file.path
        # if remote, use absolute URL
        media_url = file.absolute_path().toString()
        self.vlc_active = True
        self.vlc_helper.play(media_url)
        # set volume mapping from existing QAudioOutput volume (0..1)
        try:
            self.vlc_helper.set_volume(self.audio_output.volume())
        except Exception:
            pass
        self.current_index = idx
        self.playlist_widget.setCurrentRow(idx)
        self.update_play_button()

    def _on_vlc_position_changed(self, pos_ms):
        # called from VlcFallbackPlayer; update slider and time label
        duration = self.vlc_helper.duration() if self.vlc_helper else 0
        if duration > 0:
            value = int((pos_ms / duration) * 100) if duration > 0 else 0
            self.slider.blockSignals(True)
            self.slider.setValue(value)
            self.slider.blockSignals(False)
        self.update_time_label(pos_ms, duration)

    def _on_vlc_duration_changed(self, duration):
        # enable slider if duration > 0
        self.slider.setEnabled(duration > 0)

    def _on_vlc_playback_state(self, state_str):
        # Map VLC state to QMediaPlayer state concept for UI
        # state_str expected: 'playing', 'paused', 'stopped'
        self.update_play_button()

    def _on_vlc_ended(self):
        # when VLC playback ends, behave like EndOfMedia
        # schedule next track immediate
        self._mixing_next = False
        # call next_track logic (same as QMediaPlayer EndOfMedia)
        if hasattr(self, "_cue_next") and self._cue_next is not None:
            next_idx = self._cue_next
            self._cue_next = None
            self.load_track(next_idx)
        else:
            self.next_track()

    def move_to_top(self):
        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.text.setTextCursor(cursor)

    @Slot(dict)
    def on_receive_metadata(self, data):
        file = self.playlist[self.current_index]
        if not data:
            self.status_bar.showMessage("Remote metadata fetch error:")
        else:
            if "error" in data["retrieved_metadata"]:
                self.status_bar.showMessage(
                    f'Error retrieving metadata: {data["retrieved_metadata"]["error"]}'
                )
            else:
                self.meta_data = data["retrieved_metadata"].copy()
                title = self.meta_data.get("title", file.display_text)
                artist = self.meta_data.get("artist", "--")
                album = self.meta_data.get("album", "--")
                year = self.meta_data.get("year", "--")
                codec = self.meta_data.get("codec", "--").replace("audio/", "")
                if self.mix_method == "Auto":
                    self.transition_duration = self.meta_data.get(
                        "transition_duration", 5
                    )
                    self.set_transition_duration(self.transition_duration)
                #  self.set_album_art(path)

                self.set_metadata_label()
                #   self.year_label.setText('Year: ' + str(self.meta_data['year']))
                #   self.codec_label.setText(codec)
                self.load_lyrics(file)
                self.set_album_art(file)
                # update metadata text label
                if self.meta_data:
                    for key in self.meta_data:
                        if key != "picture" and key != "lyrics":
                            if self.meta_data[key]:
                                self.text.append(f"{key}: {self.meta_data[key]}")
                self.move_to_top()

    def on_metadata_error(self, error_message):
        """Handle metadata error"""
        self.status_bar.showMessage(f"Error: {error_message}")
        self.status_bar.repaint()

    def cleanup_metadata(self):
        """Clean up after meta completion"""
        # Remove progress bar and clear status

        if self.progress:
            self.status_bar.removeWidget(self.progress)

        # Clean up worker reference
        if self.meta_worker:
            self.meta_worker.mutex.unlock()
            self.meta_worker.deleteLater()
            self.meta_worker = None
            time.sleep(0.1)
        self.status_bar.clearMessage()
        if self.song_index:
            self.update_metadata(self.song_index)
            self.song_index = None

    def get_audio_metadata(self, file_path):
        """Extract metadata from audio file with comprehensive error handling
        file = MediaFile(file_path)
        title = file.title
        artist = file.artist
        album = file.album
        albumartist = file.albumartist
        art = file.art
        bitdepth = file.bitdepth
        bitrate = file.bitrate
        channels = file.channels
        composer = file.composer
        date = datetime.date(file.date)
        encoder_info = file.encoder_info
        encoder_settings = file.encoder_settings
        codec = file.format
        genre = file.genre
        length = file.length
        lyrics = file.lyrics
        original_date = file.original_date
        original_year = file.original_year
        r128_album_gain = file.r128_album_gain
        r128_track_gain = file.r128_track_gain
        samplerate = file.samplerate
        track = file.track
        year = file.year"""
        try:
            if self.mix_method == "Auto":
                self.transition_duration = self.detect_low_intensity_segments(
                    file_path,
                    threshold_db=self.silence_threshold_db,
                    frame_duration=0.1,
                )
                self.set_transition_duration(self.transition_duration)
        except Exception as e:
            self.transition_duration = 5
            self.meta_worker.work_message.emit(
                f"Error extracting transition duration from {file_path}: {str(e)}"
            )
        metadata = {
            "artist": "Unknown Artist",
            "album_artist": "Unknown Album Artist",
            "title": os.path.basename(file_path),
            "album": "Unknown Album",
            "year": "---",
            "duration": "---",
            "lyrics": None,
            "codec": "",
            "picture": None,
            "transition_duration": self.transition_duration,
        }
        try:
            file = MediaFile(file_path)
            title = file.title
            artist = file.artist
            album = file.album
            albumartist = file.albumartist
            if file.samplerate:
                samplerate = str(file.samplerate / 1000) + "kHz"
            else:
                samplerate = ""
            if file.bitrate:
                bitrate = str(round(file.bitrate / 1000))
            else:
                bitrate = ""
            if file.format == "MP3":
                bitdepth = bitrate + "kbps "
            elif file.bitdepth:
                bitdepth = str(file.bitdepth) + "bit "
            else:
                bitdepth = ""
            if file.channels:
                if file.channels == 2:
                    channels = "Stereo "
                else:
                    channels = str(file.channels)
            else:
                channels = None
            composer = file.composer
            if file.date:
                date = file.date.strftime("%d/%m/%Y")
            else:
                date = None
            encoder_info = file.encoder_info
            encoder_settings = file.encoder_settings
            codec = file.format
            genre = file.genre
            if file.length:
                duration = f"{(file.length // 60):.0f}:" + "{:06.3F}".format(
                    file.length % 60
                )
            else:
                duration = "---"
            if file.original_date:
                original_date = file.original_date.strftime("%d/%m/%Y")
            else:
                original_date = None
            if file.year:
                year = str(file.year)
            else:
                year = "---"
            if file.original_year:
                original_year = str(file.original_year)
                year = original_year
            else:
                original_year = None
            if file.r128_album_gain:
                r128_album_gain = str(file.r128_album_gain)
            else:
                r128_album_gain = None
            if file.r128_track_gain:
                r128_track_gain = str(file.r128_track_gain)
            else:
                r128_track_gain = None
            if file.track:
                track = str(file.track)
            else:
                track = None
            lyrics = file.lyrics

            metadata = {
                "artist": artist or "Unknown Artist",
                "album_artist": albumartist or artist or "Unknown Album Artist",
                "title": title or os.path.basename(file_path),
                "album": album or "Unknown Album",
                "year": year or "---",
                "duration": duration,
                "bitdepth": bitdepth,
                "bitrate": bitrate,
                "channels": channels,
                "composer": composer,
                "date": date,
                "encoder_info": encoder_info,
                "encoder_settings": encoder_settings,
                "genre": genre,
                "lyrics": lyrics,
                "original_date": original_date,
                "original_year": original_year,
                "r128_album_gain": r128_album_gain,
                "r128_track_gain": r128_track_gain,
                "samplerate": samplerate,
                "track": track,
                "codec": codec + " " + channels + bitdepth + samplerate,
                "picture": file.art,
                "transition_duration": self.transition_duration or 5,
            }
        except Exception as e:
            self.meta_worker.work_message.emit(
                f"Error extracting metadata from {file_path}: {str(e)}"
            )
            return metadata
        self.meta_worker.work_message.emit(
            f"Successfully extracted metadata from: {file_path}"
        )
        if metadata["lyrics"] is None and self.scan_for_lyrics:
            try:
                lyr = LyricsPlugin()
                metadata["lyrics"] = lyr.get_lyrics(
                    metadata["artist"],
                    metadata["title"],
                    metadata["album"],
                    file.length,
                )
                if metadata["lyrics"] != "":
                    lrc_path = os.path.splitext(file_path)[0] + ".lrc"
                    with open(lrc_path, "w", encoding="utf-8-sig") as f:
                        f.write(metadata["lyrics"])
            except NotImplementedError as e:
                self.meta_worker.work_message.emit(
                    f"Cannot Find lyrics for {file_path}: {str(e)}"
                )
                metadata["lyrics"] = (
                    f"Cannot Find lyrics for '{metadata['title']}' by {metadata['artist']}."
                )
            except Exception as e:
                self.meta_worker.work_message.emit(
                    f"Error reading lyrics from {file_path}: {str(e)}"
                )
                metadata["lyrics"] = "--"
        return metadata

    def update_metadata(self, index):
        self.text.clear()
        file = self.playlist[index]
        if file.item_type != "song_title":
            return

        if file.is_remote:
            url = rf"http://{file.server}:5000/get_song_metadata/{file.path}"
            self.meta_worker = Worker("meta", url)
        else:
            self.meta_worker = LocalMetaWorker(file.path, self.get_audio_metadata)
            self.meta_worker.work_message.connect(self.on_metadata_message)

        self.meta_worker.work_completed.connect(self.on_receive_metadata)
        self.meta_worker.work_error.connect(self.on_metadata_error)
        self.meta_worker.finished.connect(self.cleanup_metadata)
        # mirror behavior of other workers (lock so handler will unlock)
        self.meta_worker.mutex.lock()
        self.meta_worker.start()

    def on_metadata_message(self, message):
        self.status_bar.showMessage(message)
        self.status_bar.repaint()

    def set_metadata_label(self):
        """Sets metadata labels"""
        if not self.meta_data or "error" in self.meta_data:
            #  path = self.playlist[self.current_index].path
            title = self.playlist[
                self.current_index
            ].display_text  #  os.path.basename(path)
            artist = album = year = codec = "--"
            self.title_label.setText("Title: " + title)
            self.artist_label.setText("Artist: " + artist)
            self.album_label.setText("Album: " + album)
            self.year_label.setText("Year: " + year)
            self.codec_label.setText("Codec: " + codec)
            return

        title = self.meta_data["title"]
        artist = self.meta_data["artist"]
        album = self.meta_data["album"]
        year = self.meta_data["year"]
        duration = self.meta_data["duration"]
        codec = self.meta_data["codec"]

        self.codec_label.setText(codec)
        self.title_label.setText("Title: " + title)
        self.artist_label.setText("Artist: " + artist)
        self.album_label.setText("Album: " + album)
        self.year_label.setText("Year: " + year)
        if isinstance(duration, int):
            duration = str(duration)
        self.duration_label.setText("Duration: " + duration)
        self.codec_label.setText("Codec: " + codec)

    def get_info(self):
        if not self.meta_data:
            return
        title = self.meta_data.get("song_title", None)
        artist = self.meta_data.get("artist", None)
        album = self.meta_data.get("album", None)
        summ = self.get_wiki_summary(artist)
        self.text.clear()
        self.text.append(summ)
        summ = self.get_wiki_summary(f"{title} ({artist} song)")
        if (
            summ == f"No results for '{title} ({artist} song)'."
            or summ == f"No suitable article found for '{title} ({artist} song)'"
        ):
            summ = self.get_wiki_summary(f"{title} (record)")
        if (
            summ == f"No results for '{title} (record)'."
            or summ == f"No suitable article found for '{title} (record)'"
        ):
            summ = self.get_wiki_summary(title)
        if (
            summ == f"No results for '{title}'."
            or summ == f"No suitable article found for '{title}'"
        ):
            summ = self.get_wiki_summary(f"{album} ({artist} album)")
        self.text.append(summ)
        self.move_to_top()

    # self.text.append('\nMetadata:')

    def get_wiki_summary(self, entry: str, max_results: int = 3) -> str:
        """
        Search Wikipedia for an article and return the first valid summary.
        Skips disambiguation pages (those with 'may refer to:').
        """
        try:
            # Search for candidate pages
            candidates = wikipedia.search(entry, results=max_results)
            if not candidates:
                return f"No results for '{entry}'."

            for title in candidates:
                try:
                    page = wikipedia.page(title, auto_suggest=False)
                    if "refer to:" in page.summary.lower():
                        continue  # skip disambiguation
                    return f"✅ {title}\n\n{page.summary}"
                except wikipedia.DisambiguationError:
                    continue  # skip disambiguation
            return f"No suitable article found for '{entry}'"
        except Exception as e:
            return f"Error: {e}"

    @staticmethod
    def format_time(ms):
        s = ms // 1000
        m, s = divmod(s, 60)
        return f"{m:02}:{s:02}"

    def extract_audio_info(self):
        path = self.playlist[self.current_index]
        if self.is_remote_file(path):
            try:
                if (
                    self.meta_data
                    and "codec" in self.meta_data
                    and self.meta_data["codec"]
                ):
                    codec = self.meta_data.get("codec")
                    return codec
            except Exception as e:
                self.status_bar.showMessage("Remote metadata fetch error: " + str(e))
        else:
            audio = MediaFile(self.playlist[self.current_index])
            if not audio:
                self.status_bar.showMessage(
                    f"{audio} is not an audio file, or it is unsupported or corrupted."
                )
                return None

            # Codec
            codec = (
                audio.mime[0]
                if hasattr(audio, "mime") and audio.mime
                else audio.__class__.__name__
            )

            # Sample rate and bitrate
            sample_rate = getattr(audio.info, "sample_rate", None)
            bits = getattr(audio.info, "bits_per_sample", None)
            bitrate = getattr(audio.info, "bitrate", None)
            if codec == "audio/mp3":
                return (
                    codec
                    + " "
                    + str(sample_rate / 1000)
                    + "kHz "
                    + str(round(bitrate / 1000))
                    + "kbps"
                )
            else:
                return (
                    codec
                    + " "
                    + str(sample_rate / 1000)
                    + "kHz/"
                    + str(round(bits))
                    + "bits  "
                    + str(round(bitrate / 1000))
                    + "kbps"
                )

    def selectDirectoryDialog(self):
        file_dialog = QFileDialog(self)
        file_dialog.setWindowTitle("Select Directory")
        file_dialog.setFileMode(QFileDialog.FileMode.Directory)
        file_dialog.setViewMode(QFileDialog.ViewMode.List)

        if file_dialog.exec():
            selected_directory = file_dialog.selectedFiles()[0]
            return selected_directory

    def scan_library(self):
        folder_path = self.selectDirectoryDialog()
        if not folder_path:
            return
        # Update status bar and show progress
        self.status_bar.showMessage(
            "Scanning your Music Library. Please Wait, it might take some time depending on the library size"
        )

        self.start_scan(folder_path)

    def delete_missing_songs(self):
        """Delete missing audio files and covers to databases"""
        try:
            self.status_bar.showMessage(f"Deleting missing audio files from database")
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            deleted_songs = 0
            errors = 0

            # Get all paths and IDs from the database
            cursor.execute("SELECT id, path FROM Songs")
            db_songs = cursor.fetchall()

            # Check existence for each song
            songs_to_delete = []
            covers_to_delete = []
            for song_id, path in db_songs:
                if not os.path.exists(path):
                    songs_to_delete.append(song_id)
                    self.status_bar.showMessage(
                        f"File deleted externally, removing from DB: {path}"
                    )
                    deleted_songs += 1

                # Perform the deletion (if any)
            try:
                if songs_to_delete:
                    for song_id in songs_to_delete:
                        cursor.execute(
                            f"SELECT DISTINCT album FROM Songs WHERE id = ?", (song_id,)
                        )
                        covers_to_delete.extend(cursor.fetchall())
                    # The '?' allows safe parameter passing for multiple values
                    while len(songs_to_delete) > 999:
                        placeholders = ", ".join(["?"] * 999)
                        sql = f"DELETE FROM Songs WHERE id IN ({placeholders})"
                        cursor.execute(sql, songs_to_delete[:999])
                        for item in range(999):
                            songs_to_delete.pop(0)

                    placeholders = ", ".join(["?"] * len(songs_to_delete))
                    sql = f"DELETE FROM Songs WHERE id IN ({placeholders})"
                    cursor.execute(sql, songs_to_delete)
                # Delete duplicates
                cursor.execute(
                    """
                    DELETE FROM Songs WHERE ROWID NOT IN (SELECT MIN(ROWID) FROM Songs GROUP BY path);
                """
                )
            except sqlite3.Error as e:
                QMessageBox.critical(
                    self, "Error", f"Database error deleting songs from db: {str(e)}"
                )
                errors += 1
            except Exception as e:
                QMessageBox.critical(
                    self, "Error", f"Unexpected error deleting songs from db: {str(e)}"
                )
                errors += 1

            conn.commit()
            conn.close()
            if covers_to_delete:
                conn = sqlite3.connect(COVERS_DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    f"DELETE FROM Covers WHERE album IN ({covers_to_delete})"
                )
                conn.commit()
                conn.close()
            if deleted_songs > 0:
                self.status_bar.showMessage(
                    f"Successfully deleted {deleted_songs} songs from database"
                )
            if errors > 0:
                QMessageBox.critical(
                    self, "Error", f"Encountered {errors} errors while deleting songs"
                )

            return deleted_songs

        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Error deleting songs from database: {str(e)}"
            )
            return 0

    def delete_missing_playlists(self):
        """Delete missing audio files to database with error handling"""
        try:
            self.status_bar.showMessage(f"Deleting missing playlists from database")
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            deleted_playlists = 0
            errors = 0

            # 1. Get all paths and IDs from the database
            cursor.execute("SELECT id, path FROM Playlists")
            db_playlists = cursor.fetchall()

            # 2. Check existence for each song
            playlists_to_delete = []
            for playlist_id, path in db_playlists:
                if not os.path.exists(path):
                    playlists_to_delete.append(playlist_id)
                    self.status_bar.showMessage(
                        f"Playlist deleted externally, removing from DB: {path}"
                    )
                    deleted_playlists += 1

            # 3. Perform the deletion (if any)
            try:
                if playlists_to_delete:
                    # The '?' allows safe parameter passing for multiple values
                    placeholders = ", ".join(["?"] * len(playlists_to_delete))
                    sql = f"DELETE FROM Playlists WHERE id IN ({placeholders})"
                    cursor.execute(sql, playlists_to_delete)
                # Delete duplicates
                cursor.execute(
                    """
                                DELETE FROM Playlists WHERE ROWID NOT IN (SELECT MIN(ROWID) FROM Playlists GROUP BY path);
                            """
                )
            except sqlite3.Error as e:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Database error deleting playlists from db: {str(e)}",
                )
                errors += 1
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Unexpected error deleting playlists from db: {str(e)}",
                )
                errors += 1

            conn.commit()
            conn.close()
            if deleted_playlists > 0:
                self.status_bar.showMessage(
                    f"Successfully deleted {deleted_playlists} playlists from database",
                    4,
                )
            else:
                self.status_bar.showMessage(
                    f"No playlists were deleted from database", 4
                )
            if errors > 0:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Encountered {errors} errors while deleting playlists",
                )

            return deleted_playlists

        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Error deleting playlists from database: {str(e)}"
            )
            return 0

    def purge_library(self):
        folder_path = self.selectDirectoryDialog()
        if not folder_path:
            return
        # Update status bar and show progress
        self.status_bar.showMessage(
            "Scanning your Music Library for deleted songs and playlists. "
            "Please Wait, it might take some time depending on the library size"
        )
        self.progress = QProgressBar()
        self.progress.setStyleSheet(
            "::chunk {background-color: magenta; width: 8px; margin: 0.5px;}"
        )
        self.progress.setRange(0, 0)  # Indeterminate progress
        self.status_bar.addPermanentWidget(self.progress)
        self.status_bar.update()
        try:
            # Check for deleted audio files and playlists
            self.status_bar.showMessage("Starting library purge")

            # Add to database
            deleted_songs = self.delete_missing_songs()
            deleted_playlists = self.delete_missing_playlists()

            if deleted_songs == 0 and deleted_playlists == 0:
                success_msg = (
                    "No missing/duplicate songs and playlists were found.\n"
                    "No deletions were made"
                )
            else:
                success_msg = f"Successfully deleted {deleted_songs} songs and {deleted_playlists} playlists from the database."
            self.status_bar.removeWidget(self.progress)
            QMessageBox.information(self, "info", success_msg)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error during library purge: {str(e)}")

    def get_local_playlists(self):
        self.playlist_widget.clear()
        self.playlist.clear()
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, PL_name FROM Playlists")
        playlists = cursor.fetchall()
        conn.close()

        # return jsonify([{'id': p[0], 'name': p[1]} for p in playlists])

        try:
            # pls = []
            self.clear_playlist()
            for item in playlists:
                pl = ListItem()
                pl.item_type = "playlist"
                pl.display_text = os.path.basename(item[1])
                pl.path = item[1]
                pl.api_url = ""
                pl.is_remote = False
                pl.id = item[0]
                self.playlist.append(pl)
                self.playlist_widget.addItem(item[1])
            self.playlist_label.setText("Local Playlists: ")
            self.status_bar.clearMessage()
        except Exception as e:
            self.status_bar.clearMessage()
            QMessageBox.critical(self, "Error", str(e))

    def get_playlists(self):
        self.playlist_label.setText("Loading Playlists from Server")
        self.status_bar.showMessage(
            "Loading Playlists from Server. Please Wait, it might take some time..."
        )
        self.progress = QProgressBar()
        self.progress.setStyleSheet(
            "::chunk {background-color: magenta; width: 8px; margin: 0.5px;}"
        )
        self.progress.setRange(0, 0)  # Indeterminate progress
        self.status_bar.addPermanentWidget(self.progress)
        self.status_bar.update()
        self.playlist_widget.clear()
        self.playlist.clear()

        self.playlists_worker = Worker(None, self.api_url)
        self.playlists_worker.work_completed.connect(self.receive_playlists)
        self.playlists_worker.work_error.connect(self.on_playlists_error)
        self.playlists_worker.finished.connect(self.cleanup_playlists)

        # Start the async operation
        self.playlists_worker.start()
        self.playlists_worker.mutex.lock()

    @Slot(dict)
    def receive_playlists(self, data: dict):
        """Handle successful playlist retrieval completion"""
        if self.playlists_worker:
            self.playlists_worker.mutex.unlock()
        if "error" in data:
            QMessageBox.warning(self, "Error", data["error"])
        self.status_bar.repaint()

        try:
            self.clear_playlist()
            playlists = data["retrieved_playlists"]
            for item in playlists:
                pl = ListItem()
                pl.item_type = "playlist"
                pl.display_text = os.path.basename(item["name"])
                pl.path = item["name"]
                pl.api_url = self.api_url
                pl.is_remote = True
                pl.id = item["id"]
                self.playlist.append(pl)
                self.playlist_widget.addItem(pl.display_text)
            self.playlist_label.setText("Playlists from Server: ")
            self.status_bar.clearMessage()
        except Exception as e:
            self.status_bar.clearMessage()
            QMessageBox.critical(
                self,
                "Error",
                "Server Search error: Make sure the Server is Up and Connected",
            )

    def on_playlists_error(self, error_message):
        """Handle error"""
        if error_message == "":
            error_message = f"Remote Server not responding.\nMake sure the Server is Up and Connected"
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()

    def cleanup_playlists(self):
        """Clean up after scan completion"""
        if self.progress:
            self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()
        self.status_bar.update()

        # Clean up worker reference
        if self.playlists_worker:
            self.playlists_worker.deleteLater()
            self.playlists_worker = None

    def get_local_songs(self):
        self.get_local("song_title")

    def get_local_artists(self):
        self.get_local("artist")

    def get_local_albums(self):
        self.get_local("album")

    def get_local(self, query):
        self.is_local = True
        self.playlist_label.setText("Getting local song list")
        self.status_bar.showMessage(
            "Getting local song list. Please Wait, it might take some time..."
        )
        self.progress = QProgressBar()
        self.progress.setStyleSheet(
            "::chunk {background-color: magenta; width: 8px; margin: 0.5px;}"
        )
        self.progress.setRange(0, 0)  # Indeterminate progress
        self.status_bar.addPermanentWidget(self.progress)
        self.status_bar.update()
        self.playlist_widget.clear()
        self.playlist.clear()
        self.clear_playlist()
        files = []
        try:
            if query != "album":
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                if query == "song_title":
                    selection = "SELECT id, artist, song_title, album, path, file_name FROM Songs ORDER BY artist ASC"
                else:  # query == "artist":
                    selection = f"SELECT DISTINCT artist FROM Songs ORDER BY artist ASC"
                # else:
                # selection = f"SELECT DISTINCT album, album_artist FROM Songs ORDER BY album ASC"
                cursor.execute(selection)
                results = cursor.fetchall()
                conn.close()
                self.status_bar.showMessage(
                    f"Retrieved {len(results)} {query}s. Creating {query} list."
                )
            else:
                conn = sqlite3.connect(COVERS_DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT album, album_artist, cover FROM Covers ORDER BY album"
                )
                covers = cursor.fetchall()
                conn.close()
                for c in covers:
                    album_art = QListWidgetItem()
                    if c[2] is not None:
                        img_bytes = base64.b64decode(c[2])
                        img = QImage.fromData(img_bytes)
                        pix = QPixmap.fromImage(img)
                        album_art.setIcon(QIcon(pix))
                    else:
                        album_art.setIcon(
                            QPixmap("static/images/default_album_art.png")
                            if os.path.exists("static/images/default_album_art.png")
                            else QPixmap()
                        )
                    self.playlist_widget.setIconSize(QSize(256, 256))
                    album = ListItem()
                    album.item_type = "album"
                    album.is_remote = False
                    album.display_text = f"{c[1]} - {c[0]}"
                    album_item = QListWidgetItem(album.display_text)
                    self.playlist_widget.addItem(album_art)
                    self.playlist_widget.addItem(album_item)

                    self.playlist.append(album_art)
                    self.playlist.append(album)

                self.status_bar.showMessage(
                    f"Retrieved {len(covers)} {query}s. Creating {query} list."
                )

            if query != "album":
                for r in results:
                    song = ListItem()
                    #   self.get_audio_metadata(r[4])
                    if query == "song_title":
                        song.display_text = f"{r[1]} - {r[2]} ({r[3]})"
                        song.path = r[4]
                    elif query == "artist":
                        song.display_text = r[0]
                    song.is_remote = False
                    song.item_type = query
                    files.append(song)
            self.playlist_label.setText(f"{query} List: ")

        except sqlite3.Error as e:
            QMessageBox.critical(
                self, "Error", f"Database error getting query: {str(e)}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error getting query: {str(e)}")

        # Remove progress bar and clear status
        if self.progress:
            self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()
        self.status_bar.update()
        self.status_bar.showMessage("List loaded. Enjoy!")
        if files:
            self.add_files(files)

    def get_list(self, query):
        self.is_local = False
        self.remote_base = self.api_url
        self.playlist_label.setText(f"Getting {query} list from Server. Please Wait...")
        self.status_bar.showMessage(
            f"Getting {query} list from Server. Please Wait, it might take "
            "some time..."
        )
        self.progress = QProgressBar()
        self.progress.setStyleSheet(
            "::chunk {background-color: magenta; width: 8px; margin: 0.5px;}"
        )
        self.progress.setRange(0, 0)  # Indeterminate progress
        self.status_bar.addPermanentWidget(self.progress)
        self.status_bar.update()
        self.playlist_widget.clear()
        self.playlist.clear()
        self.songs_worker = Worker(query, f"{self.api_url}/get_all")
        self.songs_worker.work_completed.connect(self.receive_list)
        self.songs_worker.work_error.connect(self.on_songs_error)
        self.songs_worker.finished.connect(self.cleanup_songs)

        # Start the async operation
        self.songs_worker.start()
        self.songs_worker.mutex.lock()

    @Slot(dict)
    def receive_list(self, retrieved: dict):
        """Handle successful playlist retrieval completion"""
        self.status_bar.update()
        if self.songs_worker:
            self.is_local = False
            self.songs_worker.mutex.unlock()
        else:
            self.is_local = True
        if "error" in retrieved:
            QMessageBox.warning(self, "Error", retrieved["error"])
        self.status_bar.update()

        try:
            self.clear_playlist()
            files = []
            data = retrieved["retrieved"]
            if "path" in data[0].keys():
                for file in data:
                    song = ListItem()
                    song.is_remote = not self.is_local
                    song.item_type = "song_title"
                    song.path = file["path"]
                    song.display_text = (
                        f"{file['artist']} - {file['title']} ({file['album']})"
                    )
                    files.append(song)
                self.playlist_label.setText("Songs List: ")
            elif "artist" in data[0].keys():
                #  files = list(itertools.repeat("artist", len(self.songs)))
                for file in data:
                    song = ListItem()
                    song.is_remote = not self.is_local
                    song.item_type = "artist"
                    song.path = ""
                    song.display_text = file["artist"]
                    files.append(song)
                self.playlist_label.setText("Artists List: ")
            elif "album" in data[0].keys():
                #  files = list(itertools.repeat("album", len(self.songs)))
                for file in data:
                    song = ListItem()
                    song.is_remote = not self.is_local
                    song.item_type = "album"
                    song.path = ""
                    song.display_text = f"{file['album'][1]} - {file['album'][0]}"
                    files.append(song)
                self.playlist_label.setText("Album List: ")

            #  self.playlist_label.setText('Songs List: ')
            self.status_bar.clearMessage()

            self.add_files(files)
            self.status_bar.showMessage("List loaded. Enjoy!")
        except Exception as e:
            self.status_bar.clearMessage()
            QMessageBox.critical(
                self,
                "Error",
                f"Server error: {str(e)} \nMake sure the Server is Up and Connected",
            )

    def on_songs_error(self, error_message):
        """Handle error"""
        if error_message == "":
            error_message = f"Remote Server not responding.\nMake sure the Server is Up and Connected"
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()

    def cleanup_songs(self):
        """Clean up after scan completion"""
        if self.progress:
            self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()
        self.status_bar.update()

        # Clean up worker reference
        if self.songs_worker:
            self.songs_worker.deleteLater()
            self.songs_worker = None

    def get_songs(self):
        self.get_list("song_title")

    def get_artists(self):
        self.get_list("artist")

    def get_albums(self):
        self.get_list("album")

    def on_pl_completed(self, pl_data):
        if self.pl_worker:
            self.pl_worker.mutex.unlock()
        data = pl_data["pl"]
        if data and data["success"]:
            songs = []
            idx = self.playlist_widget.currentRow()
            playlist_name = data["name"]
            for line in data["playlist"]:
                line = line.strip()
                song = ListItem()
                song.item_type = "song_title"
                song.display_text = os.path.basename(line)
                song.path = line
                song.api_url = self.api_url
                song.is_remote = True
                songs.append(song)
            self.clear_playlist()
            self.add_files(songs)
            self.playlist_label.setText(f"Playlist: {playlist_name}")
            self.status_bar.showMessage(f"Playlist {playlist_name} loaded. Enjoy!")

    def on_pl_error(self, error_message):
        """Handle playlist error"""
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()

    def cleanup_pl(self):
        """Clean up after scan completion"""
        if self.progress:
            self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()
        self.status_bar.update()

        # Clean up worker reference
        if self.pl_worker:
            self.pl_worker.deleteLater()
            self.pl_worker = None

    def parse_playlist_file(self, playlist_path):
        """Parse playlist file and return list of media files with error handling"""
        try:
            self.status_bar.showMessage(f"Parsing playlist: {playlist_path}")

            if not os.path.exists(playlist_path):
                QMessageBox.critical(
                    self, "error", f"Playlist file does not exist: {playlist_path}"
                )
                return []

            playlist = []
            playlist_dir = os.path.dirname(playlist_path)
            line_count = 0
            ext = Path(playlist_path).suffix.lower()
            if ext in [".m3u", ".m3u8"]:
                lines = self.load_m3u_playlist(playlist_path)
            elif ext == ".cue":
                lines = self.load_cue_playlist(playlist_path)
            elif ext == ".json":
                lines = self.load_json_playlist(playlist_path)
            else:
                QMessageBox.warning(
                    self, "Error!", f"Unsupported playlist format: {ext}"
                )
                return

            for line in lines:
                line_count += 1
                try:
                    if os.path.exists(line.path):
                        playlist.append(line)
                        self.status_bar.showMessage(
                            f"Added to playlist: {line.display_text}"
                        )
                    else:
                        QMessageBox.critical(
                            self,
                            "warning",
                            f"File not found in playlist (line {line_count}): {line.display_text}",
                        )

                except Exception as e:
                    QMessageBox.critical(
                        self,
                        "warning",
                        f"Error processing playlist line {line_count}: {e}",
                    )

            self.status_bar.showMessage(
                f"Parsed playlist with {len(playlist)} valid files"
            )
            return playlist

        except Exception as e:
            QMessageBox.critical(
                self, "error", f"Error parsing playlist {playlist_path}: {e}"
            )
            return []

    def play_selected_item(self):
        idx = self.playlist_widget.currentRow()
        item = self.playlist_widget.currentItem()
        file = self.playlist[idx]
        try:
            if file.item_type == "cover":
                self.search_tracks("album", file.display_text)
        except AttributeError:
            idx += 1
            if 0 <= idx < len(self.playlist):
                file = self.playlist[idx]
                self.playlist_widget.setCurrentRow(idx)
                self.play_selected_item()
            else:
                return
        # item_ext = Path(item.text()).suffix
        if file.item_type == "artist":
            self.search_tracks("artist", file.display_text)
        elif file.item_type == "album":
            dash = file.display_text.find(" - ")
            self.search_tracks("album", file.display_text[dash + 3 :])
            return
        elif file.item_type == "song_title":
            self.play_selected_track(item)
        elif file.item_type == "playlist":
            playlist_id = file.id
            if not file.is_remote:
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT path, PL_name FROM Playlists WHERE id = ?",
                        (playlist_id,),
                    )
                    playlist_data = cursor.fetchone()
                    conn.close()

                    if not playlist_data:
                        QMessageBox.critical(
                            self, "error", f"Playlist not found: {playlist_id}"
                        )
                        return

                    playlist_path, playlist_name = playlist_data
                    playlist_files = self.parse_playlist_file(playlist_path)

                    self.status_bar.showMessage(
                        f"Loaded playlist '{playlist_name}' with {len(playlist_files)} files"
                    )
                    data = {
                        "success": True,
                        "playlist": playlist_files,
                        "name": playlist_name,
                    }

                except sqlite3.Error as e:
                    QMessageBox.critical(
                        self,
                        "error",
                        f"Database error loading playlist {playlist_id}: {e}",
                    )
                    return
                except Exception as e:
                    QMessageBox.critical(
                        self, "error", f"Error loading playlist {playlist_id}: {e}"
                    )
                    return

                if data:
                    songs = []
                    idx = self.playlist_widget.currentRow()
                    playlist_name = data["name"]
                    for song in data["playlist"]:
                        songs.append(song)
                    self.clear_playlist()
                    self.add_files(songs)
                    self.playlist_label.setText(f"Playlist: {playlist_name}")
                    self.status_bar.showMessage(
                        f"Playlist {playlist_name} loaded. Enjoy!"
                    )
            else:
                self.status_bar.showMessage(
                    "Loading Playlist from Server. Please Wait, it might take some time..."
                )

                # Create and configure worker thread
                self.pl_worker = Worker(
                    "pl", f"{self.api_url}/load_playlist/{playlist_id}"
                )
                self.pl_worker.work_completed.connect(self.on_pl_completed)
                self.pl_worker.work_error.connect(self.on_pl_error)
                self.pl_worker.finished.connect(self.cleanup_pl)

                try:
                    self.pl_worker.start()
                    self.pl_worker.mutex.lock()
                except Exception as e:
                    QMessageBox.critical(self, "Error", str(e))

        else:
            return

    def local_web_ui(self):
        if os.environ.get(f"WERKZEUG_RUN_MAIN") is None:
            webbrowser.open(self.api_url)

    def remote_web_ui(self):
        try:
            r = requests.post(f"{self.api_url}/web_ui")
            QMessageBox.information(self, "info", r.text)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def remote_desk_ui(self):
        try:
            r = requests.post(f"{self.api_url}/desk_ui")
            QMessageBox.information(self, "info", r.text)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    @Slot()
    def on_start_completed(self, result):
        """Handle successful completion"""
        if not result:
            QMessageBox.warning(self, "Error", "Song was not revealed")
            self.status_bar.update()
            return
        else:
            self.status_bar.showMessage(result["answer"])
            self.status_bar.update()
            QMessageBox.information(self, "Info:", result["answer"])

    def on_start_error(self, error_message):
        """Handle error"""
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()

    def cleanup_start(self):
        """Clean up after completion"""
        if self.progress:
            self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()
        self.status_bar.update()

        # Clean up worker reference
        if self.start_worker:
            self.start_worker.deleteLater()
            self.start_worker = None

    def reveal_current(self):
        if 0 <= self.current_index < len(self.playlist):
            self.request_reveal.emit(self.playlist[self.current_index])

    def reveal_path(self, song):
        if song.is_remote:
            folder_path = song.path
            self.status_bar.showMessage(
                "Trying to reveal Song in remote server. "
                "Please Wait, it might take some time..."
            )

            # Create and configure progress bar
            self.progress = QProgressBar()
            self.progress.setStyleSheet(
                "::chunk {background-color: green; width: 8px; margin: 0.5px;}"
            )
            self.progress.setRange(0, 0)  # Indeterminate progress
            self.status_bar.addPermanentWidget(self.progress)
            self.status_bar.update()

            # Create and configure worker thread
            self.start_worker = Worker(folder_path, f"{self.api_url}/start")
            self.start_worker.work_completed.connect(self.on_start_completed)
            self.start_worker.work_error.connect(self.on_start_error)
            self.start_worker.finished.connect(self.cleanup_start)

            # Start the async operation
            try:
                self.start_worker.start()
            except Exception as e:
                self.status_bar.showMessage("Error: " + str(e))
        else:
            if sys.platform.startswith("win"):
                os.startfile(os.path.dirname(song.path))
            elif sys.platform == "darwin":
                os.system(f'open -R "{song.path}"')
            else:
                os.system(f'xdg-open "{os.path.dirname(song.path)}"')

    def quit(self):
        save_json(
            SETTINGS_FILE,
            {
                "server": self.server,
                "mix_method": self.mix_method,
                "transition_duration": self.transition_duration,
                "silence_threshold_db": self.silence_threshold_db,
                "silence_min_duration": self.silence_min_duration,
                "scan_for_lyrics": self.scan_for_lyrics,
                "style": self.dark_style,
            },
        )
        self.close()


class LocalMetaWorker(QThread):
    """
    Runs local audio metadata extraction off the GUI thread.
    Expects an extractor callable that takes a single file_path arg and
    returns the metadata dict (same structure as get_audio_metadata).
    """

    work_completed = Signal(dict)  # Emits {'retrieved_metadata': metadata}
    work_error = Signal(str)
    work_message = Signal(str)

    def __init__(self, file_path: str, extractor_callable):
        super().__init__()
        self.file_path = file_path
        self.extractor_callable = extractor_callable
        self.mutex = QMutex()

    def run(self):
        try:
            # Call the provided extractor (this will perform heavy work)
            metadata = self.extractor_callable(self.file_path)
            # Emit in same structure as your remote meta worker
            self.work_completed.emit({"retrieved_metadata": metadata})
        except Exception as e:
            self.work_error.emit(str(e))


class Worker(QThread):
    """
    Worker thread for handling asynchronous operations such as scanning, purging,
    searching libraries, and interacting with remote servers. This class uses
    PySide6's QThread to perform tasks in a separate thread to avoid blocking
    the main GUI thread.

    Attributes:
        work_completed (Signal): Signal emitted when the work is successfully completed.
        work_error (Signal): Signal emitted when an error occurs during the operation.
        mutex (QMutex): Mutex to ensure thread-safe operations.
        folder_path (str): Path to the folder being processed.
        api_url (str): URL of the API endpoint for the operation.
    """

    # Define signals for communicating with the main thread
    work_completed = Signal(dict)  # Emits scan result data
    work_error = Signal(str)  # Emits error message

    def __init__(self, folder_path, api_url):
        """
        Initialize the Worker thread with the folder path and API URL.

        Args:
            folder_path (str): Path to the folder to be processed.
            api_url (str): URL of the API endpoint for the operation.
        """
        super().__init__()
        self.mutex = QMutex()
        self.folder_path = folder_path
        self.api_url = api_url

    def run(self):
        """
        Run the asynchronous work in a separate thread. This method is executed
        when the thread starts. It handles exceptions and ensures proper cleanup.
        """
        result = None
        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Run the async scan
            if self.api_url.endswith("scan_library"):
                result = loop.run_until_complete(self.scan_library_async())
            elif self.api_url.endswith("start"):
                result = loop.run_until_complete(self.reveal_remote_song_async())
            elif self.folder_path is None:
                result = loop.run_until_complete(self.get_playlists_async())
            elif isinstance(self.folder_path, dict):
                result = loop.run_until_complete(self.search_async())
            elif isinstance(self.folder_path, tuple):
                result = loop.run_until_complete(self.purge_library_async())
            elif self.folder_path == "meta":
                result = loop.run_until_complete(self.get_metadata_async())
            elif self.folder_path in {"song_title", "artist", "album"}:
                result = loop.run_until_complete(self.get_songs_async())
            elif self.folder_path == "pl":
                result = loop.run_until_complete(self.get_pl_async())
            elif self.folder_path == "server":
                result = loop.run_until_complete(self.check_server_async())
            else:
                raise ValueError(f"Unknown folder_path value: {self.folder_path}")

            # Emit success signal
            self.work_completed.emit(result)

        except Exception as e:
            # Emit error signal
            self.work_error.emit(str(e))
            loop.close()
            self.mutex.unlock()

        finally:
            loop.close()

    async def scan_library_async(self):
        """
        Asynchronous function to scan the library. Uses aiohttp to interact
        with the API endpoint for scanning the library.
        """
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.api_url, json={"folder_path": self.folder_path}
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception(f"Scan failed: {response.status}")

    async def purge_library_async(self):
        """
        Asynchronous function to purge the library. Uses aiohttp to interact
        with the API endpoint for purging the library.
        """
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.api_url}/purge_library",
                json={"folder_path": self.folder_path[1]},
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception(f"Purge failed: {response.status}")

    async def search_async(self):
        """
        Asynchronous function to search the library. Uses aiohttp to interact
        with the API endpoint for searching the library.
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(self.api_url, params=self.folder_path) as response:
                if response.status == 200:
                    search_result = await response.json()
                    result = {"search_result": search_result}
                    return result
                else:
                    raise Exception(f"Search failed: {response.status}")

    async def get_playlists_async(self):
        """
        Asynchronous function to retrieve playlists from the server. Uses aiohttp
        to interact with the API endpoint for fetching playlists.
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.api_url}/get_playlists", timeout=5
            ) as response:
                if response.status == 200:
                    retrieved_playlists = await response.json()
                    result = {"retrieved_playlists": retrieved_playlists}
                    return result
                else:
                    raise Exception(f"Failed to fetch playlists: {response.status}")

    async def get_songs_async(self):
        """
        Asynchronous function to retrieve songs from the server. Uses aiohttp
        to interact with the API endpoint for fetching songs.
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(
                self.api_url, params={"query": self.folder_path}
            ) as response:
                if response.status == 200:
                    retrieved = await response.json()
                    result = {"retrieved": retrieved}
                    return result
                else:
                    raise Exception(f"Failed to fetch songs: {response.status}")

    async def get_pl_async(self):
        """
        Asynchronous function to retrieve a specific playlist from the server.
        Uses aiohttp to interact with the API endpoint for fetching the playlist.
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(self.api_url) as response:
                if response.status == 200:
                    retrieved_playlist = await response.json()
                    result = {"pl": retrieved_playlist}
                    return result
                else:
                    raise Exception(f"Failed to fetch playlist: {response.status}")

    async def get_metadata_async(self):
        """
        Asynchronous function to retrieve metadata from the server. Uses aiohttp
        to interact with the API endpoint for fetching metadata.
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(self.api_url) as response:
                if response.status == 200:
                    retrieved_metadata = await response.json()
                    result = {"retrieved_metadata": retrieved_metadata}
                    return result
                elif response.status == 404:
                    retrieved_metadata = {
                        "album": "",
                        "artist": "",
                        "codec": "audio/flac 44.1kHz/16bits  860kbps",
                        "duration": 0,
                        "lyrics": "",
                        "picture": None,
                        "title": "Not Found",
                        "year": "",
                    }
                    result = {"retrieved_metadata": retrieved_metadata}
                    return result
                else:
                    raise Exception(f"Failed to fetch metadata: {response.status}")

    async def check_server_async(self):
        """
        Asynchronous function to check if the server is valid and reachable.
        Uses aiohttp to interact with the API endpoint for server validation.
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://{self.api_url}:5000", timeout=3
            ) as response:
                if response.status == 200:
                    status = response.status
                    return {"status": status, "API_URL": self.api_url}
                else:
                    raise Exception(f"Server check failed: {response.status}")

    async def reveal_remote_song_async(self):
        """
        Asynchronous function to reveal the currently playing song on the remote server.
        Uses aiohttp to interact with the API endpoint for revealing the song.
        """
        async with aiohttp.ClientSession() as session:
            async with session.post(self.api_url, json=self.folder_path) as response:
                if response.status == 200:
                    answer = await response.json()
                    result = {"answer": answer}
                    return result
                else:
                    raise Exception(f"Failed to fetch songs: {response.status}")


class SynchronizedLyrics:
    def __init__(self, audio=None):
        self.times = []
        self.lines = []
        self.raw_lyrics = ""

        try:
            if w.meta_data and "lyrics" in w.meta_data and w.meta_data["lyrics"]:
                #       data = r.json()
                self.raw_lyrics = w.meta_data["lyrics"]
            else:
                self.raw_lyrics = "--"
        except Exception as e:
            w.status_bar.showMessage("Remote lyrics fetch error:" + str(e))

        self.parse_lyrics(self.raw_lyrics)

    def parse_lyrics(self, lyrics_text):
        time_tag = re.compile(r"\[(\d+):(\d+)(?:\.(\d+))?\]")
        self.times = []
        self.lines = []
        for line in lyrics_text.splitlines():
            matches = list(time_tag.finditer(line))
            if matches:
                lyric = time_tag.sub("", line).strip()
                for m in matches:
                    min, sec, ms = m.groups()
                    total_ms = int(min) * 60 * 1000 + int(sec) * 1000 + int(ms or 0)
                    self.times.append(total_ms)
                    self.lines.append(lyric)
            elif line.strip():
                self.times.append(0)
                self.lines.append(line.strip())

    def get_current_line(self, pos_ms):
        for i, t in enumerate(self.times):
            if pos_ms < t:
                return max(0, i - 1)
        return len(self.lines) - 1 if self.lines else -1

    def is_synchronized(self):
        """Return True if lyrics are synchronized (have time tags)."""
        # Synchronized if any time tag is nonzero
        return any(t > 0 for t in self.times)


class LyricsDisplay(QTextEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setReadOnly(True)
        self.setStyleSheet(
            "font-size: 18px; background: #E0F0FF; border-width: 2px; border-color: #7A7EA8; border-style: inset;"
        )
        self.current_line_idx = -1
        self.lines = []
        self.is_synchronized = False

    def set_lyrics(self, lines, is_synchronized):
        self.lines = lines
        self.is_synchronized = is_synchronized
        self.current_line_idx = -1
        self.update_display(-1)

    def update_display(self, highlight_idx):
        html = ""
        for idx, line in enumerate(self.lines):
            if self.is_synchronized and idx == highlight_idx:
                html += f"<div style='color: #3A89FF; font-weight: bold; background: #F5FBFF'>{line}</div>"
            else:
                html += f"<div>{line}</div>"
        self.setHtml(html)
        if self.is_synchronized and 0 <= highlight_idx < len(self.lines):
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.Start)
            for _ in range(highlight_idx):
                cursor.movePosition(QTextCursor.Down)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()

    def highlight_line(self, idx):
        # Only highlight if lyrics are synchronized
        if self.is_synchronized:
            if idx != self.current_line_idx:
                self.current_line_idx = idx
                self.update_display(idx)
        else:
            # For unsynchronized lyrics, never highlight any line
            if self.current_line_idx != -1:
                self.current_line_idx = -1
                self.update_display(-1)


class TextEdit(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Instructions")
        self.resize(1180, 780)
        self.instructions_edit = QTextEdit(readOnly=True)
        layout = QVBoxLayout()
        layout.addWidget(self.instructions_edit)
        self.setLayout(layout)
        self.instructions_edit.setText(text_8)


def _process_startup_args(player: AudioPlayer, args):
    """
    Handle command-line paths passed by Windows Explorer double-click.
    - playlist files (extensions in `playlist_extensions`) are parsed and added.
    - audio files (extensions in `audio_extensions`) are added and played.
    - directories are scanned/added via existing `load_dir`.
    Note: this opens files in the same new instance. For single-instance behavior,
    a separate IPC mechanism is required.
    """
    if not args:
        return

    paths = [Path(a) for a in args if a and a.strip()]
    for p in paths:
        try:
            # Directory: use existing folder scan helper
            if p.exists() and p.is_dir():
                try:
                    player.load_dir(str(p))
                except Exception:
                    # Fallback: add files by walking
                    files = [str(f) for f in p.rglob("*") if f.suffix.lower() in audio_extensions]
                    if files:
                        player.add_files(files)
                        if player.current_index == -1 and player.playlist:
                            player.load_track(0, auto_play=True)
                continue

            # Playlist file: parse and add songs
            if p.suffix.lower() in playlist_extensions:
                try:
                    songs = player.parse_playlist_file(str(p))
                    if songs:
                        player.add_files(songs)
                        # start playing first valid song if player is idle
                        if player.current_index == -1 and player.playlist:
                            player.load_track(0, auto_play=True)
                except Exception:
                    continue
                continue

            # Audio file: add and play
            if p.suffix.lower() in audio_extensions:
                song = ListItem()
                song.item_type = "song_title"
                song.display_text = os.path.basename(str(p))
                song.path = str(p)
                song.is_remote = False
                player.add_files([song])
                # play the last added entry
                if player.current_index == -1 and player.playlist:
                    idx = len(player.playlist) - 1
                    player.load_track(idx, auto_play=True)
                continue

        except Exception as e:
            print(str(e))
            # Keep startup robust: ignore any problematic path
            continue

if __name__ == "__main__":
    qInstallMessageHandler(qt_message_filter)
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("static/images/favicon.ico"))
    settings = get_settings()
    w = AudioPlayer(settings)

    # Process any files passed by double-click from Explorer
    try:
        if len(sys.argv) > 1:
            _process_startup_args(w, sys.argv[1:])
    except Exception:
        pass

    sys.exit(app.exec())

