import sys
import os
import sqlite3
from fuzzywuzzy import fuzz
# from django.contrib.gis.gdal.prototypes.srs import islocal
from PySide6.QtCore import Qt, QDate, QEvent, QUrl, QTimer, QSize, QRect, Signal, QThread, Slot, QMutex
from PySide6.QtGui import QPixmap, QTextCursor, QImage, QAction, QIcon, QKeySequence, QKeyEvent
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSlider, QListWidget, QFileDialog, QTextEdit, QListWidgetItem, QMessageBox,
    QComboBox, QSpinBox, QFormLayout, QGroupBox, QLineEdit, QInputDialog, QMenuBar,
    QMenu, QStatusBar,QProgressBar, QFrame, QCheckBox)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaMetaData
import mutagen
from mutagen import File
from mutagen.flac import FLAC
from pathlib import Path
from random import shuffle
# import itertools
import re
import math
from enum import Enum
import json
import asyncio
import aiohttp
import requests
import base64
import webbrowser
import wikipedia
from dotenv import load_dotenv
#  from sqlalchemy.orm import remote
# from transformers.utils import is_remote_url

# from ecoserver import is_localhost

load_dotenv()
SHUTDOWN_SECRET = os.getenv("SHUTDOWN_SECRET")
APP_DIR = Path.home() / "Web-Media-Server-and-Player"
APP_DIR.mkdir(exist_ok=True)
SETTINGS_FILE = APP_DIR / "settings.json"
# SETTINGS_FILE  = os.path.join(os.path.expanduser('~'), 'Advanced Media Player', 'settings.json')
# PLAYLISTS_FILE = APP_DIR / "playlists.json"
DB_PATH = 'music.db'
MUSIC_DIR = ''
wikipedia.set_lang("en")
audio_extensions = {'.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac', '.wma'}
playlist_extensions = {'.m3u', '.m3u8', '.cue'}


def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def save_json(path: Path, obj):
    try:
        path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    except Exception as e:
        QMessageBox.warning(w, "Error!", str(e))

def get_settings():
    # json_data = load_json(PLAYLISTS_FILE, default={"server": "http://localhost:5000", "playlists": []})
    default = {"server": r"http://localhost:5000",
               "mix_method": "Fade",
               "transition_duration": 4,
               "gap_enabled": True,
               "silence_threshold_db": -46,
               "silence_min_duration": 0.5
               }
    json_settings = load_json(SETTINGS_FILE, default=default)
    return json_settings


class ItemType(Enum):
    PLAYLIST = 'playlist'
    SONG = 'song'
    ARTIST = 'artist'
    ALBUM = 'album'
    COVER = 'cover'
    DIRECTORY = 'directory'

    def set_item_type(item_type):
        if not isinstance(item_type, ItemType):
            raise ValueError("Invalid status value")
        w.status_bar.showMessage(f"Status set to: {item_type.value}")

class ListItem:
    def __init__(self):
        super().__init__()
        self.is_remote = False
        self.item_type = ItemType
        self.display_text ='Unknown'
        self.route = ''
        self.path = ''
        self.server = w.server
        self.id = int

    def absolute_path(self):
        if self.is_remote:
            abs_url = QUrl()
            abs_url.setScheme('http')
            abs_url.setHost(self.server)
            abs_url.setPort(5000)
            file_path = rf'/{self.route}/{self.path}'
            abs_url.setPath(file_path)
            return abs_url
        else:
            return QUrl.fromLocalFile(os.path.abspath(self.path))



class AudioPlayer(QWidget):
    request_search = Signal(str, str)
    request_reveal = Signal(ListItem)

    def __init__(self, settings):
        super().__init__()

        # data
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
        self.api_url = self.remote_base = rf'http://{self.server}:5000'
        self.playlists = []

        # Mixing/transition config
        self.mix_method = settings["mix_method"]
        self.transition_duration = settings["transition_duration"]

        self.gap_enabled = settings["gap_enabled"]
        self.silence_threshold_db = settings["silence_threshold_db"]
        self.silence_min_duration = settings["silence_min_duration"]
        self._silence_ms = 0
        self._fade_step = None
        self.fade_timer = None
        self.scan_worker = None
        self.progress = None
        self.setWindowTitle(f"Ultimate Media Player. Current Server: {self.api_url}")
        self.resize(1200, 800)
        self.playlist = []
        self.current_index = -1
        self.show_remaining = False
        self.short_albums = True
        self.lyrics = None
        self.lyrics_timer = QTimer(self)
        self.lyrics_timer.setInterval(200)
        self.lyrics_timer.timeout.connect(self.update_lyrics_display)
        self.meta_data =None

        # Layout
        layout = QVBoxLayout(self)

        # ----- Menu bar -----
        menubar = QMenuBar(self)

        # File menu
        local_menu = QMenu("&Local", self)
        menubar.addMenu(local_menu)

        self.open_action = QAction("&Open Playlist | Add Songs", self)
        self.open_action.setShortcut(QKeySequence.Open)
        self.open_action.setToolTip("Add Songs/folders and/or Playlists to playing cue")
        self.open_action.triggered.connect(self.show_playlist_menu)
        local_menu.addAction(self.open_action)

        self.load_action = QAction("Load &Playlists", self)
        self.load_action.setShortcut(QKeySequence.Print)
        self.load_action.triggered.connect(self.get_local_playlists)
        local_menu.addAction(self.load_action)

        self.load_action = QAction("List all &Songs", self)
        self.load_action.setShortcut(QKeySequence("Ctrl+S"))
        self.load_action.triggered.connect(self.get_local_songs)
        local_menu.addAction(self.load_action)

        self.load_action = QAction("List all &Artists", self)
        self.load_action.setShortcut(QKeySequence("Ctrl+A"))
        self.load_action.triggered.connect(self.get_local_artists)
        local_menu.addAction(self.load_action)

        self.load_action = QAction("List all Al&bums", self)
        self.load_action.setShortcut(QKeySequence("Ctrl+B"))
        self.load_action.triggered.connect(self.get_local_albums)
        local_menu.addAction(self.load_action)

        self.scan_action = QAction("Scan &Library", self)
        self.scan_action.setShortcut(QKeySequence("Ctrl+L"))
        self.scan_action.triggered.connect(self.scan_library)
        local_menu.addAction(self.scan_action)

        self.purge_action = QAction("P&urge Library", self)
        self.purge_action.setShortcut(QKeySequence("Ctrl+U"))
        self.purge_action.triggered.connect(self.purge_library)
        local_menu.addAction(self.purge_action)

        self.save_action = QAction("&Save Current Queue", self)
        self.save_action.setShortcut(QKeySequence.Save)
        self.save_action.triggered.connect(self.save_current_playlist)
        local_menu.addAction(self.save_action)

        self.clear_action = QAction("&Clear Playlist", self)
        self.clear_action.setShortcut(QKeySequence.Delete)
        self.clear_action.triggered.connect(self.clear_playlist)
        local_menu.addAction(self.clear_action)

        self.local_web_action = QAction("Launch &Web UI", self)
        self.local_web_action.setShortcut(QKeySequence("Ctrl+W"))
        self.local_web_action.triggered.connect(self.local_web_ui)
        local_menu.addAction(self.local_web_action)

        self.local_shutdown_action = QAction("Shutdown Lo&cal Server", self)
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

        self.server_action = QAction("Connect to R&emote", self)
        self.server_action.setShortcut(QKeySequence("Ctrl+E"))
        self.server_action.triggered.connect(self.enter_server)
        remote_menu.addAction(self.server_action)

        self.load_action = QAction("Load &Playlists", self)
        self.load_action.setShortcut(QKeySequence.Print)
        self.load_action.triggered.connect(self.get_playlists)
        remote_menu.addAction(self.load_action)

        self.load_action = QAction("List all &Songs", self)
        self.load_action.setShortcut(QKeySequence("Ctrl+S"))
        self.load_action.triggered.connect(self.get_songs)
        remote_menu.addAction(self.load_action)

        self.load_action = QAction("List all &Artists", self)
        self.load_action.setShortcut(QKeySequence("Ctrl+A"))
        self.load_action.triggered.connect(self.get_artists)
        remote_menu.addAction(self.load_action)

        self.load_action = QAction("List all Al&bums", self)
        self.load_action.setShortcut(QKeySequence("Ctrl+B"))
        self.load_action.triggered.connect(self.get_albums)
        remote_menu.addAction(self.load_action)

        self.scan_action = QAction("Scan &Library", self)
        self.scan_action .setShortcut(QKeySequence("Ctrl+R"))
        self.scan_action .triggered.connect(self.scan_remote_library)
        remote_menu.addAction(self.scan_action )

        self.purge_action = QAction("P&urge Library", self)
        self.purge_action.setShortcut(QKeySequence("Ctrl+U"))
        self.purge_action.triggered.connect(self.purge_remote_library)
        remote_menu.addAction(self.purge_action)

        self.web_action = QAction("Launch &Web UI", self)
        self.web_action.setShortcut(QKeySequence("Ctrl+I"))
        self.web_action.triggered.connect(self.remote_web_ui)
        remote_menu.addAction(self.web_action)

        self.desktop_action = QAction("Launch &Desktop UI", self)
        self.desktop_action.setShortcut(QKeySequence("Ctrl+D"))
        self.desktop_action.triggered.connect(self.remote_desk_ui)
        remote_menu.addAction(self.desktop_action)

        self.shutdown_action = QAction("S&hutdown Server", self)
        self.shutdown_action.setShortcut(QKeySequence("Ctrl+C"))
        self.shutdown_action.triggered.connect(self.shutdown_server)
        remote_menu.addAction(self.shutdown_action)

        remote_menu.addSeparator()

        self.exit_action = QAction("E&xit", self)
        self.exit_action.setShortcut(QKeySequence.Quit)
        self.exit_action.triggered.connect(self.quit)
        remote_menu.addAction(self.exit_action)

        # Help menu
        help_menu = QMenu("&Help", self)
        menubar.addMenu(help_menu)

        self.instructions_action = QAction("&Instructions", self)
        self.instructions_action.triggered.connect(self.show_instructions)
        help_menu.addAction(self.instructions_action)

        self.about_action = QAction("&About", self)
        self.about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(self.about_action)

        # Audio/Player
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(1.0)  # or any value between 0.0 (mute) to 1.0 (full volume)
        self.player.setAudioOutput(self.audio_output)
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
            "font-size: 12px; background-color: lightyellow; opacity: 0.6; "
            "border-color: #D4D378; border-width: 2px; border-style: inset; ")
        self.playlist_widget.setStyleSheet(
            "QListView::item:selected{ background-color: blue; }")
        self.playlist_label = QLabel("Cue:")
        self.btn_shuffle = QPushButton("Shuffle")
        self.btn_shuffle.setFixedSize(QSize(60, 26))
        self.playlist_widget.setDragDropMode(QListWidget.InternalMove)
        self.playlist_widget.itemClicked.connect(
            self.play_selected_playlist)
        self.playlist_widget.itemDoubleClicked.connect(
            self.play_selected_track)
        self.playlist_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.playlist_widget.customContextMenuRequested.connect(
            self.show_playlist_context_menu)

        # Drag-and-drop support
        self.setAcceptDrops(True)
        self.playlist_widget.viewport().setAcceptDrops(True)
        self.playlist_widget.viewport().installEventFilter(self)

        # Controls/UI
        self.album_art = QLabel()
        self.album_art.setFixedSize(256, 256)
        self.album_art.setScaledContents(True)
        self.album_art.setPixmap(
            QPixmap("static/images/default_album_art.png") if os.path.exists(
                "static/images/default_album_art.png") else QPixmap())
        self.title_label = QLabel("Title --")
        self.title_label.setFixedWidth(256)
        self.artist_label = QLabel("Artist --")
        self.artist_label.setFixedWidth(256)
        self.album_label = QLabel("Album --")
        self.album_label.setFixedWidth(256)
        self.year_label = QLabel("Year --")
        self.codec_label = QLabel("Codec --")

        self.text = QTextEdit(readOnly=True)
       # self.text_label = QLabel("Artist and Song Info:")
        self.btn_info = QPushButton("Push for Artist and Song Info.")
        self.btn_info.setFixedSize(QSize(256, 26))

        self.time_label = QPushButton("--:--"); self.time_label.setFlat(True)
        self.time_label.setCursor(Qt.PointingHandCursor)
        self.time_label.clicked.connect(self.toggle_time_display)
        self.slider = QSlider(Qt.Horizontal); self.slider.setRange(0, 100)
      #  self.slider.sliderMoved.connect(self.seek_position) replaced by slider released
        self.slider.sliderMoved.connect(self.on_slider_moved)
        self.slider.sliderReleased.connect(self.on_slider_released)
        self._slider_moving = False

        image_path = 'static/images/buttons.jpg'
        tile_width = 1650
        tile_height = 1650
        self.sub_images = self.split_image(image_path, tile_width, tile_height)

        self.prev_button = QPushButton()
        pixmap = QPixmap.fromImage(self.sub_images[2])
        self.prev_button.setIcon(QIcon(pixmap))
        self.prev_button.setIconSize(QSize(50, 50))
        self.prev_button.setFixedSize(QSize(50, 50))
        self.play_button = QPushButton()
        pixmap = QPixmap.fromImage(self.sub_images[0])
        self.play_button.setIcon(QIcon(pixmap))
        self.play_button.setIconSize(QSize(50, 50))
        self.play_button.setFixedSize(QSize(50, 50))
        self.next_button = QPushButton()
        pixmap = QPixmap.fromImage(self.sub_images[3])
        self.next_button.setIcon(QIcon(pixmap))
        self.next_button.setIconSize(QSize(50, 50))
        self.next_button.setFixedSize(QSize(50, 50))
        self.prev_button.clicked.connect(self.prev_track)
        self.play_button.clicked.connect(self.toggle_play_pause)
        self.next_button.clicked.connect(self.next_track)

        # Lyrics
        self.lyrics_display = LyricsDisplay()
        self.lyrics_display.setReadOnly(True)

        # Mixing Controls UI
        self.crossfade_modes = ["Fade", "Smooth", "Full", "Scratch", "Cue"]
        self.mix_method_combo = QComboBox()
        self.mix_method_combo.addItems(self.crossfade_modes)
        self.mix_method_combo.setCurrentText(self.mix_method)
        self.mix_method_combo.currentTextChanged.connect(self.set_mix_method)

        self.transition_spin = QSpinBox()
        self.transition_spin.setRange(1, 10)
        self.transition_spin.setValue(self.transition_duration)
        self.transition_spin.setSuffix(" s")
        self.transition_spin.valueChanged.connect(self.set_transition_duration)



       # self.silence_check = QPushButton("Skip Silence")
       # self.silence_check.setCheckable(True)
       # self.silence_check.setChecked(self.skip_silence)
       # self.silence_check.toggled.connect(self.set_skip_silence)

        # StatusBar
        self.status_bar = QStatusBar()
        self.status_bar.showMessage("Welcome! Drag-and-drop Playlists or/and Songs to Playlist pane to start the music.")

        mix_form = QFormLayout()
        mix_form.addRow("Mix Method:", self.mix_method_combo)
        mix_form.addRow("Transition:", self.transition_spin)
     #   mix_form.addRow(self.silence_check)
        mix_group = QGroupBox("Mixing Options")
        mix_group.setFixedSize(QSize(180, 80))
        mix_group.setLayout(mix_form)

        gap_killer_group = QGroupBox("Gap Killer")
     #   gap_killer_group.setFixedSize(QSize(180, 80))
        gap_box = QHBoxLayout()
        self.chk_gap = QCheckBox("ON")
        self.chk_gap.setChecked(True)
        self.silence_db = QSlider(Qt.Horizontal)
        self.silence_db.setRange(-60, -20)
        self.silence_db.setValue(-46)
        self.silence_dur = QSlider(Qt.Horizontal)
        self.silence_dur.setRange(1, 50)
        self.silence_dur.setValue(5)
        self.gap_status = QLabel("Monitoring")
        gap_box.addWidget(self.chk_gap)
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
        meta_layout.addWidget(self.codec_label)

        metadata_layout = QVBoxLayout(self)
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
        shuffle_box.addWidget(self.playlist_label, )
        shuffle_box.addWidget(self.btn_shuffle, )
        playlist_layout.addLayout(shuffle_box)
        playlist_layout.addWidget(self.playlist_widget)

        main_layout = QHBoxLayout(self)
        main_layout.addLayout(playlist_layout, 1)
        main_layout.addLayout(left_layout, 2)
        layout.addWidget(menubar)
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
        self.btn_info.clicked.connect(self.get_info)
        self.request_search.connect(self.search_tracks)
        self.request_reveal.connect(self.reveal_path)
        self.player.positionChanged.connect(self.update_slider)
        self.player.durationChanged.connect(self.update_duration)
        self.player.mediaStatusChanged.connect(self.media_status_changed)
        self.player.playbackStateChanged.connect(self.update_play_button)
        self.slider.sliderPressed.connect(lambda: self.player.pause())
        self.slider.sliderReleased.connect(lambda: self.player.play())
     #   self.player.metaDataChanged.connect(self.on_metadata_changed)
        self.chk_gap.toggled.connect(lambda v: setattr(self, "gap_enabled", v))
        self.silence_db.valueChanged.connect(
            lambda v: setattr(self, "silence_threshold_db", v))
        self.silence_dur.valueChanged.connect(
            lambda v: setattr(self, "silence_min_duration", v / 10.0))
        self.reveal_btn.clicked.connect(self.reveal_current)
        self.player.errorOccurred.connect(self.handle_error)


        # For mixing (transition to next track)
        self.player.positionChanged.connect(self.check_for_mix_transition)

        # Init
        self.init_database()
        self.update_play_button()
        self.show()
        for item in self.playlists:
            self.playlist_widget.addItem(item['name'])

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
                rect = QRect(left, top, min(tile_width, img_width - left),
                             min(tile_height, img_height - top))
                sub_img = image.copy(rect)
                sub_images.append(sub_img)
        return sub_images

    # Database initialization
    def init_database(self):
        """Initialize the database with proper error handling"""
        try:
            self.status_bar.showMessage("Initializing database...")
            conn = sqlite3.connect('Music.db')
            cursor = conn.cursor()

            # Create Songs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS Songs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path CHAR(255) NOT NULL,
                    file_name CHAR(120) NOT NULL,
                    artist CHAR(120) NOT NULL,
                    song_title CHAR(120) NOT NULL,
                    duration INT NOT NULL,
                    album CHAR(120),
                    year SMALLINT
                )
            ''')

            # Create Playlists table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS Playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path CHAR(255) NOT NULL,
                    PL_name CHAR(120) NOT NULL
                )
            ''')

            conn.commit()
            conn.close()
            self.status_bar.showMessage("Database initialized successfully")

        except sqlite3.Error as e:
            QMessageBox.critical(self, "Database Error",f"Database initialization failed: {str(e)}")
            raise
        except Exception as e:
            QMessageBox.critical(self, "Error",
                f"Unexpected error during database initialization: {e}")
            raise

    def scan_for_audio_files(self, directory):
        """Scan directory for audio files and playlists with error handling"""
        try:
            self.status_bar.showMessage(f"Scanning directory: {directory}")

            if not os.path.exists(directory):
                QMessageBox.critical(self, "Error", f"Directory does not exist: {directory}")
                return

            if not os.path.isdir(directory):
                QMessageBox.critical(self, "Error", f"Path is not a directory: {directory}")
                return

            audio_files = []
            playlist_files = []
            scan_errors = 0

            for root, dirs, files in os.walk(directory):
                self.status_bar.showMessage(f"Scanning folder: {root}")

                for file in files:
                    try:
                        file_path = os.path.join(root, file)
                        file_ext = Path(file).suffix.lower()

                        if file_ext in audio_extensions:
                            audio_files.append(file_path)
                        elif file_ext in playlist_extensions:
                            playlist_files.append(file_path)

                    except Exception as e:
                        QMessageBox.warning(self, "Scan Error", f"Error processing file {file}: {e}")
                        scan_errors += 1

            self.status_bar.showMessage(f"Scan complete. Found {len(audio_files)} audio files and {len(playlist_files)} playlists")
            if scan_errors > 0:
                QMessageBox.warning(self, "Scan Error",f"Encountered {scan_errors} errors during scanning")

            return audio_files, playlist_files

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error scanning directory {directory}: {e}")
            return

    def add_songs_to_database(self, audio_files):
        """Add audio files to database with error handling"""
        try:
            self.status_bar.showMessage(f"Adding {len(audio_files)} audio files to database")

            conn = sqlite3.connect('Music.db')
            cursor = conn.cursor()
            added_songs = 0
            errors = 0

            for file_path in audio_files:
                try:
                    # Check if file already exists
                    cursor.execute("SELECT id FROM Songs WHERE path = ?", (file_path,))
                    if cursor.fetchone():
                        self.status_bar.showMessage(f"File already in database: {file_path}")
                        continue

                    metadata = self.get_audio_metadata(file_path)
                    if metadata:
                        file_name = os.path.basename(file_path)
                        cursor.execute('''
                            INSERT INTO Songs (path, file_name, artist, song_title, duration, album, year)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            file_path,
                            file_name,
                            metadata['artist'],
                            metadata['title'],
                            metadata['duration'],
                            metadata['album'],
                            metadata['year']
                        ))
                        added_songs += 1
                        self.status_bar.showMessage(f"Added song: {metadata['artist']} - {metadata['title']}")
                    else:
                        QMessageBox.warning(self, "Scan Error", f"Could not extract metadata from: {file_path}")
                        errors += 1

                except sqlite3.Error as e:
                    QMessageBox.critical(self, "Error",f"Database error adding song {file_path}: {e}")
                    errors += 1
                except Exception as e:
                    QMessageBox.critical(self, "Error",f"Unexpected error adding song {file_path}: {e}")
                    errors += 1

            conn.commit()
            conn.close()

            QMessageBox.warning(self, "Scan Error", f"Successfully added {added_songs} songs to database")
            if errors > 0:
                QMessageBox.warning(self, "Scan Error", f"Encountered {errors} errors while adding songs")

            return added_songs

        except Exception as e:
            QMessageBox.critical(self, "Error",f"Error adding songs to database: {e}")

    def add_playlists_to_database(self, playlist_files):
        """Add playlist files to database with error handling"""
        try:
            self.status_bar.showMessage(f"Adding {len(playlist_files)} playlists to database")

            conn = sqlite3.connect('Music.db')
            cursor = conn.cursor()
            added_playlists = 0
            errors = 0

            for file_path in playlist_files:
                try:
                    # Check if playlist already exists
                    cursor.execute("SELECT id FROM Playlists WHERE path = ?",
                                   (file_path,))
                    if cursor.fetchone():
                        self.status_bar.showMessage(
                            f"Playlist already in database: {file_path}")
                        continue

                    pl_name = os.path.basename(file_path)
                    cursor.execute('''
                        INSERT INTO Playlists (path, PL_name)
                        VALUES (?, ?)
                    ''', (file_path, pl_name))
                    added_playlists += 1
                    self.status_bar.showMessage(f"Added playlist: {pl_name}")

                except sqlite3.Error as e:
                    QMessageBox.warning(self, 'error'
                        f"Database error adding playlist {file_path}: {str(e)}")
                    errors += 1
                except Exception as e:
                    QMessageBox.critical(self, 'error'
                        f"Unexpected error adding playlist {file_path}: {str(e)}")
                    errors += 1

            conn.commit()
            conn.close()

            QMessageBox.information(self, 'success',
                f"Successfully added {added_playlists} playlists to database")
            if errors > 0:
                QMessageBox.warning(self, 'error',
                    f"Encountered {errors} errors while adding playlists")

            return added_playlists

        except Exception as e:
            QMessageBox.warning(self, 'error', f"Error adding playlists to database: {str(e)}")

    @Slot(dict)
    def on_server_reply(self, data: dict):
        """Handle successful playlist retrieval completion"""
        if 'error' in data:
            QMessageBox.warning(self, "Scan Error", data['error'])
        self.status_bar.repaint()

     #   status_code = data['status']
        if data['status'] == 200:
            self.server = data['API_URL']
            self.playlist_widget.clear()
            self.api_url = self.remote_base = f'http://{self.server}:5000'
            self.setWindowTitle(
                f"Ultimate Media Player. Current Server: {self.api_url}")
            self.status_bar.showMessage(
                f'Remote Server is now: {self.api_url}', 8000)
            QMessageBox.information(self, 'Success!',
                                    f'Remote Server is now: {self.api_url}')
        else:
            QMessageBox.warning(self, 'Error', data['status'])



    def on_server_error(self, error_message):
        """Handle server check error"""
        if error_message == '':
            error_message = f'Remote Server not responding.\nMake sure the Server is Up and Connected'
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
        server, ok_pressed = QInputDialog.getText(self, "Input",
                                                "Enter Remote Server name or IP:",
                                                QLineEdit.Normal, "")
        if ok_pressed and server != '':
            self.status_bar.showMessage(f'Please Wait, testing connection with server: {server}')
            self.status_bar.repaint()
            self.progress = QProgressBar()
            self.progress.setRange(0, 0)  # Indeterminate progress
            self.status_bar.addWidget(self.progress)
            self.status_bar.repaint()

            self.server_worker = Worker('server', server)
            self.server_worker.work_completed.connect(
                self.on_server_reply)
            self.server_worker.work_error.connect(self.on_server_error)
            self.server_worker.finished.connect(self.cleanup_server)

            try:
                # Start the async operation
                self.server_worker.start()
            except Exception as e:
                self.status_bar.clearMessage()
                QMessageBox.warning(self, 'Error',
                                  f'Server {server} not responding.\nMake sure the Server is Up and Connected')



    def scan_remote_library(self):
        """async scan_remote_library"""

        # Get folder path from user input
        folder_path, ok = QInputDialog.getText(
            self,
            "Input",
            "Enter the Remote Absolute Path of Folder to Scan:",
            QLineEdit.Normal,
            ""
        )

        if not (ok and folder_path):
            return

        # Update status bar and show progress
        self.status_bar.showMessage(
            'Scanning your Music Library. Please Wait, it might take some time depending on the library size'
        )

        # Create and configure progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Indeterminate progress
        self.status_bar.addWidget(self.progress)
        self.status_bar.repaint()

        # Create and configure worker thread
        self.scan_worker = Worker(folder_path, self.api_url)
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
        if 'error' in data:
            QMessageBox.warning(self, "Scan Error", data['error'])
        elif 'answer' in data:
            QMessageBox.warning(self, "Scan Error", data['answer']['error'])
        else:
            QMessageBox.information(self, "Success", data['message'])
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
            ""
        )

        if not (ok and folder_path):
            return

        # Update status bar and show progress
        self.status_bar.showMessage(
            'Scanning your Music Library for deleted files. Please Wait, it might take some time depending on the library size'
        )

        # Create and configure progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Indeterminate progress
        self.status_bar.addWidget(self.progress)
        self.status_bar.repaint()

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
        if 'error' in data:
            QMessageBox.warning(self, "Purge Error", data['error'])
        elif 'answer' in data:
            QMessageBox.warning(self, "Purge Error", data['answer']['error'])
        else:
            QMessageBox.information(self, "Success", data['message'])
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
                json={}
            )
            self.status_bar.showMessage(resp.text)
            self.status_bar.repaint()
        except Exception as e:
            QMessageBox.warning(self, "Error",
                                "Failed to shutdown Local Server."
                                "\nMake Sure the Server is Up")


    def shutdown_server(self):
        try:
            resp = requests.post(
                f"{self.api_url}/shutdown",
                headers={"X-API-Key": SHUTDOWN_SECRET},
                json={}
            )
            self.status_bar.showMessage(resp.text.replace("\n", ""))
            self.status_bar.repaint()
        except Exception as e:
            if 'An existing connection was forcibly closed by the remote host' in str(e):
                self.status_bar.showMessage("Remote server successfully Shut Down!")
            else:
                QMessageBox.warning(self, "Error",
                                f"Failed to shutdown Remote Server @ "
                                f"{self.api_url}:\nMake Sure the Server is Up")


    def save_current_playlist(self):
        if not self.playlist:
            QMessageBox.information(self, "Playlists",
                                    "No current queue to save.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Current Playlist", "",
            "Playlist Files (*.m3u8);;All Files (*)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    for item in self.playlist:
                        f.write(item + '\n')
                    f.write("# Playlist created with EcoG's Ultimate Audio Player")
                self.status_bar.showMessage(f"Saved: {path}")
            except Exception as e:
                QMessageBox.warning(self, "Error",
                                    f"Could not save file:\n{str(e)}")


    def show_instructions(self):
        self.instructions = TextEdit()
        self.instructions.show()



    def show_about_dialog(self):
        QMessageBox.about(
            self,
            "About...",
            "<h3>Ultimate Audio Player</h3>"
            "<p>HiRes Audio Player / API Client</p>"
            "<p>Created with ❤️ by EcoG</p>"
        )



    def on_go(self):
        col = self.combo.currentText()
        q = self.search.text().strip()
        if q:
            self.is_local = False
            self.status_bar.showMessage(
                f'Searching for {col} {q}. Please Wait...')
            progress = QProgressBar()
            progress.setValue(50)
            self.status_bar.addWidget(progress)
            self.status_bar.repaint()
            self.search_tracks(col, q)


    def on_local(self):
        col = self.combo.currentText()
        q = self.search.text().strip()
        if q:
            self.is_local = True
            self.status_bar.showMessage(
                f'Searching for {col} {q}. Please Wait...')
            progress = QProgressBar()
            progress.setValue(50)
            self.status_bar.addWidget(progress)
            self.status_bar.repaint()
            self.search_tracks(col, q)


    def get_album_art(self, path):
        img_data = None
        try:
            audio = File(path)
            if audio is not None and hasattr(audio, 'tags'):
                tags = audio.tags
                if 'APIC:' in tags:
                    img_data = tags['APIC:'].data
                elif hasattr(tags, 'get') and tags.get('covr'):
                    img_data = tags['covr'][0]
                elif hasattr(audio, 'pictures') and audio.pictures:
                    img_data = audio.pictures[0].data
            if img_data:
                try:
                    album_art = base64.b64encode(img_data).decode('utf-8')
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Error encoding album art: {str(e)}")
                    album_art = None
                return album_art
        except Exception as e:
            self.status_bar.showMessage("Artwork extraction error:" + str(e))



    def search_tracks(self, column: str, query: str):
        if not column or not query:
            QMessageBox.warning(self, "Error", "Missing search parameters")
            return
        q = query.lower()
        if self.is_local:
            try:
                conn = sqlite3.connect('Music.db')
                cursor = conn.cursor()

                # First try exact match
                cursor.execute(
                    f"SELECT id, artist, song_title, album, path, file_name FROM Songs WHERE {column} LIKE ?",
                    (f'%{query}%',))
                results = cursor.fetchall()

                # If no results, try fuzzy matching
                if not results:
                    self.status_bar.showMessage("No exact matches, trying fuzzy search")
                    cursor.execute(
                        f"SELECT id, artist, song_title, album, path, file_name, {column} FROM Songs")
                    all_songs = cursor.fetchall()

                    fuzzy_matches = []
                    for song in all_songs:
                        try:
                            ratio = fuzz.ratio(query.lower(), song[6].lower())
                            if ratio > 60:  # Threshold for fuzzy matching
                                fuzzy_matches.append((song[:6], ratio))
                        except Exception as e:
                            self.status_bar.showMessage(
                                f"Error in fuzzy matching for song {song[0]}: {e}")

                    # Sort by similarity
                    fuzzy_matches.sort(key=lambda x: x[1], reverse=True)
                    results = [match[0] for match in
                               fuzzy_matches[:10]]  # Top 10 matches

                conn.close()
                self.status_bar.showMessage(f"Search returned {len(results)} results")
            except sqlite3.Error as e:
                QMessageBox.critical(self, "Error",
                                     f"Database error searching songs: {str(e)}")
            try:
                albums = []
                new_results = []
                for result in results:
                    if not f'{result[1]} - {result[3]}' in albums:
                        albums.append(result[3])
                        album_art = self.get_album_art(result[4])
                    else:
                        album_art = None
                    result_list = list(result)
                    result_list.append(album_art)
                    new_result = tuple(result_list)
                    new_results.append(new_result)

                search_result = [{
                    'id'       : r[0],
                    'artist'   : r[1],
                    'title'    : r[2],
                    'album'    : r[3],
                    'path'     : r[4],
                    'filename' : r[5],
                    'album_art': r[6]
                } for r in new_results]
                self.on_search_completed({"search_result": search_result})
            except Exception as e:
                QMessageBox.critical(self, "Error",f"Error searching songs: {str(e)}")
        else:
            params = {"column":column, "query":q}
            url = f"{self.api_url}/search_songs"

            # Create and configure progress bar
            self.progress = QProgressBar()
            self.progress.setRange(0, 0)  # Indeterminate progress
            self.status_bar.addWidget(self.progress)
            self.status_bar.repaint()

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
            songs = []
            albums = {}
            for track in data:
                song = ListItem()
                song.is_remote = is_remote
                song.item_type = 'song_title' # or self.combo.currentText()
                song.path = track["path"]
                song.display_text =f"{track['artist']} - {track['title']} ({track['album']})"
                songs.append(song)
                if self.short_albums:
                    album = track['album_art']
                    if not track["album_art"] in albums.keys():
                        albums[album] = []
                    albums[album].append(song)
            self.clear_playlist()
            if self.short_albums:
                self.add_albums(albums)
            else:
                self.add_files(songs)
        else:
            col = self.combo.currentText()
            q = self.search.text().strip()
            self.status_bar.showMessage(
                f'{col} {q} was not found on Server')
            QMessageBox.information(self, 'Sorry 😞',
                                    f'{col} {q} was not found on Server')


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
        if self.playlist and self.playlist[0].item_type == 'song_title':
            shuffle(self.playlist)
            self.playlist_widget.clear()
            self.current_index = -1
            for song in self.playlist:
                item = QListWidgetItem(os.path.basename(song.display_text))
                self.playlist_widget.addItem(item)


    # --- Mixing/transition config slots ---
    def set_mix_method(self, method):
        self.mix_method = method

    def set_transition_duration(self, val):
        self.transition_duration = val

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
                if self.mix_method == "Fade":
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

    def start_fade_to_next(self, mode="fade"):
        """Perform the selected crossfade mode when transitioning."""
        next_idx = self.current_index + 1
        if not (0 <= next_idx < len(self.playlist)):
            return
        next_song = self.playlist[next_idx]
        while next_song.item_type != "song_title":
            next_idx += 1
            if not (0 <= next_idx < len(self.playlist)):
                return
            next_song = self.playlist[next_idx]
        if next_song.is_remote:
           # abs_path = next_path.split('5000/')[1]
         #   next_song.server = self.api_url
            next_song.route = 'serve_audio'
      #      next_path = next_song.absolute_path()  # f"{next_song}/serve_audio/{abs_path}"
      #  else:
       #     next_path = next_song.path
        self.next_player = QMediaPlayer(self)
        self.next_output = QAudioOutput(self)
        self.next_player.setAudioOutput(self.next_output)
        self.next_player.setSource(next_song.absolute_path())
#        self.next_player.setSource(QUrl.fromLocalFile(next_path))
        self.next_output.setVolume(0)
        self.slider.setValue(0)
     #   self.update_metadata(next_idx)
       # if self.is_local_file(next_path):
        #    self.set_album_art(next_path)
        self.next_player.play()
        self.update_metadata(next_idx)
       # self.load_lyrics(next_path)
        self.lyrics_timer.start()
        self.playlist_widget.setCurrentRow(next_idx)
        self.fade_timer = QTimer(self)
        self.fade_timer.setInterval(100)
        fade_steps = int(self.transition_duration * 1000 / 100)
        self._fade_step = 0

        def fade():
            self._fade_step += 1
            frac = self._fade_step / fade_steps

            if mode == "fade":
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
                    self.audio_output.setVolume(max(0, 1.0 - 2*frac))
                    self.next_output.setVolume(0.0)
                else:
                    self.audio_output.setVolume(0.0)
                    self.next_output.setVolume(1.0)
            else:
                # Default to fade
                self.audio_output.setVolume(max(0, 1.0 - frac))
                self.next_output.setVolume(min(1.0, frac))

            if self._fade_step >= fade_steps:
                self.fade_timer.stop()
                self.audio_output.setVolume(1.0)
                self.player.stop()
                # Switch to next player
                self.player = self.next_player
                self.audio_output = self.next_output
                self.current_index = next_idx
            #    self.load_track(self.current_index, auto_play=False, skip_mix_check=True)
            #    self.player.play()
            #    if self.is_local_file(next_path):
             #       self.update_metadata(self.current_index)
                self.update_play_button()
                self.player.positionChanged.connect(self.update_slider)
                self.player.durationChanged.connect(self.update_duration)
                self.player.mediaStatusChanged.connect(self.media_status_changed)
                self.player.playbackStateChanged.connect(self.update_play_button)
            #    self.player.metaDataChanged.connect(self.on_metadata_changed)
                self.player.errorOccurred.connect(self.handle_error)
                self.player.positionChanged.connect(self.check_for_mix_transition)
                self.next_player = None
                self.next_output = None
                self._mixing_next = False

        self.fade_timer.timeout.connect(fade)
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

    def load_track(self, idx, auto_play=True, skip_mix_check=False, skip_silence=False):
        if 0 <= idx < len(self.playlist):
            file = self.playlist[idx]
            if file.item_type == 'cover':
                idx += 1
                if 0 <= idx < len(self.playlist):
                    file = self.playlist[idx]
                else:
                    return
            path = file.path
            self.current_index = idx
            if file.is_remote:
                file.route = 'serve_audio'
            media_url = file.absolute_path()
            self.player.setSource(media_url)
            self.slider.setValue(0)
            if auto_play:
                try:
                    self.player.play()
                except Exception as e:
                    QMessageBox.critical(self, "Error!", str(e))
            self.lyrics_timer.start()
         #   if self.is_local_file(path):
            self.update_metadata(idx)
            self.playlist_widget.setCurrentRow(idx)
            # Optionally skip silence at start (very basic, see note below)
            if skip_silence:
                QTimer.singleShot(500, self.skip_leading_silence)
            # Reset mix triggers unless skip_mix_check (for fade handover)
            if not skip_mix_check:
                self._mixing_next = False
            self.update_play_button()
        else:
            self.title_label.setText("No Track Loaded")
            self.artist_label.setText("--")
            self.album_label.setText("--")
            self.year_label.setText("--")
            self.codec_label.setText("--")
            self.album_art.setPixmap(QPixmap())
            self.lyrics_display.clear()
            self.lyrics_timer.stop()
            self.update_play_button()

    def skip_leading_silence(self):
        """A very basic silence-skip: jump forward if amplitude is zero
        (needs real audio analysis for best results)."""
        # QMediaPlayer does NOT support sample-level analysis.
        # A real solution would use something like pydub or ffmpeg to find silence start/end.
        # Here, we just jump ahead 1s, up to 4 times, if still at start.
        max_tries = 4
        for i in range(max_tries):
            if self.player.position() < 1500:
                self.player.setPosition(self.player.position() + 1000)
            else:
                break

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
        audio_file = File(file_path)
        if audio_file is None:
            self.status_bar.showMessage(
                f"Could not read audio file: {file_path}. Make sure the file exists.")
            return None

        metadata = {
            'artist': '',
            'title': '',
            'album': '',
            'year': '',
            'duration': 0,
            'lyrics': '',
            'codec': '',
            'picture': None
        }

        # Get basic metadata
        try:
            if 'TPE1' in audio_file:  # Artist
                metadata['artist'] = str(audio_file['TPE1'])
            elif 'ARTIST' in audio_file:
                metadata['artist'] = str(audio_file['ARTIST'][0])
            elif '©ART' in audio_file:
                metadata['artist'] = str(audio_file['©ART'][0])
        except Exception as e:
            self.status_bar.showMessage(
                f"Error reading artist metadata from {file_path}: {str(e)}")

        try:
            if 'TIT2' in audio_file:  # Title
                metadata['title'] = str(audio_file['TIT2'])
            elif 'TITLE' in audio_file:
                metadata['title'] = str(audio_file['TITLE'][0])
            elif '©nam' in audio_file:
                metadata['title'] = str(audio_file['©nam'][0])
        except Exception as e:
            self.status_bar.showMessage(
                f"Error reading title metadata from {file_path}: {str(e)}")

        try:
            if 'TALB' in audio_file:  # Album
                metadata['album'] = str(audio_file['TALB'])
            elif 'ALBUM' in audio_file:
                metadata['album'] = str(audio_file['ALBUM'][0])
            elif '©alb' in audio_file:
                metadata['album'] = str(audio_file['©alb'][0])
        except Exception as e:
            self.status_bar.showMessage(
                f"Error reading album metadata from {file_path}: {str(e)}")

        display_text = f"{metadata['artist']} - {metadata['title']} ({metadata['album']})"

        return display_text




    def show_playlist_menu(self, pos=None):
        menu = QFileDialog(self)
        menu.setFileMode(QFileDialog.ExistingFiles)
        menu.setNameFilters([
            "Audio files (*.mp3 *.flac *.ogg *.wav *.m4a *.aac *.wma *.opus)",
            "Playlists (*.m3u *.m3u8 *.cue)",
            "All files (*)"])
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
        for f in files:
            if f.item_type == "playlist": # if os.path.isfile(f):
                ext = Path(f.path).suffix.lower()
                if ext in ['.m3u', '.m3u8']:
                    pl = self.load_m3u_playlist(f.path)
                    self.playlist += pl
                    for i in pl:
                        item = QListWidgetItem(i.display_text)  # QListWidgetItem(os.path.basename(i))
                        self.playlist_widget.addItem(item)
                    self.playlist_label.setText(f'Playlist: {f.display_text}')
                elif ext == '.cue':
                    pl = self.load_cue_playlist(f.path)
                    self.playlist += pl
                    for i in pl:
                        item = QListWidgetItem(os.path.basename(i.display_text))
                        self.playlist_widget.addItem(item)
                    self.playlist_label.setText(
                        f'Playlist: {os.path.basename(f.display_text)}')
            elif f.item_type == "song_title" or f.item_type == 'artist' or f.item_type == 'album':  # if ext in audio_extensions:
                self.playlist.append(f)
                item = QListWidgetItem(f.display_text) # item = QListWidgetItem(os.path.basename(f))
                self.playlist_widget.addItem(item)
            elif f.item_type == 'directory': # os.path.isdir(f):
                self.load_dir(f)
            if self.current_index == -1 and self.playlist[-1].item_type == 'song_title':
                self.load_track(0)
        if self.progress:
            self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()

    def load_m3u_playlist(self, path):
        songs = []
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            # Try with ANSI encoding if UTF-8 fails
            try:
                with open(path, 'r', encoding='ANSI') as f:
                    lines = f.readlines()
            except UnicodeDecodeError:
                try:
                    # Try to guess the encoding if UTF-8 and ANSI fail
                    from charset_normalizer import from_path
                    result = from_path(path).best()
                    with open(path, 'r', encoding=result.encoding) as f:
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
                    audio = File(line)
                else:
                    audio = None
                if not line or not audio:
                    continue
                song = ListItem()
                song.item_type = "song_title"
                song.display_text = os.path.basename(line)
                song.path = line
                song.is_remote = False
                songs.append(song)
        return songs

    def load_cue_playlist(self, path):
        songs = []
        with open(path, encoding='utf-8-sig') as f:
            for line in f:
                if re.match('^FILE .(.*). (.*)$', line):
                    file_path = line[6:-7]
                    if not os.path.isabs(file_path):
                        file_path = os.path.abspath(
                            os.path.join(os.path.dirname(path), file_path))
                    song = ListItem()
                    song.item_type = "song_title"
                    song.path = file_path
                    song.is_remote = False
                    song.display_text = file_path
                    songs.append(song)
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
                    QMessageBox.critical(self, "Error!", f"Error processing file {file}: {e}")
                    scan_errors += 1
        self.status_bar.showMessage(
            f"Scan complete. Found {len(songs)} files ")
        if scan_errors > 0:
            QMessageBox.critical(self, "Error!", f"Encountered {scan_errors} errors during directory scanning")

        self.add_files(songs)


    def add_albums(self, albums):
        for album in albums:
            self.add_album(album)
            for song in albums[album]:
                self.playlist.append(song)
                item = QListWidgetItem(song.display_text)
                self.playlist_widget.addItem(item)

            if self.current_index == -1 and self.playlist:
                self.load_track(0)
        if self.progress:
            self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()


    def add_album(self, data):
      #  if 0 > self.current_index >= len(self.playlist) - 1:
         #   return
        if not data:
            self.status_bar.showMessage(
                "Metadata fetch error:")
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
        cover.item_type = 'cover'
        self.playlist.append(cover)
        try:
            if data != '':
                img_bytes = base64.b64decode(data)
                img = QImage.fromData(img_bytes)
                pix = QPixmap.fromImage(img)
                self.album_only_art.setPixmap(
                    pix.scaled(self.album_art.size(), Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)
                )
            else:
                self.album_only_art.setPixmap(
                    QPixmap(
                        "static/images/default_album_art.png") if os.path.exists(
                        "static/images/default_album_art.png") else QPixmap())
            return
        except Exception as e:
            self.album_only_art.setPixmap(
                QPixmap(
                    "static/images/default_album_art.png") if os.path.exists(
                    "static/images/default_album_art.png") else QPixmap())
            self.status_bar.showMessage(
                "Base64 album art decode error:" + str(e))


    def play_selected_track(self, item):
        idx = self.playlist_widget.row(item)
       # self.update_metadata(idx)
        self.load_track(idx)

    def show_playlist_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self.playlist_widget)
        menu.setStyleSheet(
            "background-color: lightGrey; border-color: darkGray; "
            "border-width: 2px; border-style: outset;")
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
                self.player.stop()
                self.current_index = -1
                self.lyrics_display.clear()
                self.update_play_button()
            elif row < self.current_index:
                self.current_index -= 1

    def clear_playlist(self):
        self.playlist_widget.clear()
        self.playlist.clear()
        self.playlist_label.setText('Cue:')
        self.player.stop()
        self.current_index = -1
        self.lyrics_display.clear()
        self.update_play_button()

    def is_remote_file(self, path):
        return path.is_remote

    def set_album_art(self, file):
        """
        Sets album art using metadata JSON if provided (remote), otherwise falls back to local extraction.
        """
        if self.is_remote_file(file):
            if self.meta_data and 'picture' in self.meta_data and self.meta_data[
                'picture']:
                try:
                    img_bytes = base64.b64decode(self.meta_data['picture'])
                    img = QImage.fromData(img_bytes)
                    pix = QPixmap.fromImage(img)
                    self.album_art.setPixmap(
                        pix.scaled(self.album_art.size(), Qt.KeepAspectRatio,
                                   Qt.SmoothTransformation)
                    )
                    return
                except Exception as e:
                    self.album_art.setPixmap(
                        QPixmap(
                            "static/images/default_album_art.png") if os.path.exists(
                            "static/images/default_album_art.png") else QPixmap())
                    self.status_bar.showMessage("Base64 album art decode error:" + str(e))
            else:
                # Fallback image
                self.album_art.setPixmap(
                    QPixmap(
                        "static/images/default_album_art.png") if os.path.exists(
                        "static/images/default_album_art.png") else QPixmap())
            return
        # fallback below if fetch fails
        img_data = None
        try:
            audio = File(file.path)
            if audio is not None and hasattr(audio, 'tags'):
                tags = audio.tags
                if 'APIC:' in tags:
                    img_data = tags['APIC:'].data
                elif hasattr(tags, 'get') and tags.get('covr'):
                    img_data = tags['covr'][0]
                elif hasattr(audio, 'pictures') and audio.pictures:
                    img_data = audio.pictures[0].data
            if img_data:
                img = QImage.fromData(img_data)
                pix = QPixmap.fromImage(img)
                self.album_art.setPixmap(
                    pix.scaled(self.album_art.size(), Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)
                )
                return
        except Exception as e:
            self.status_bar.showMessage("Artwork extraction error:" + str(e))
        # Fallback image
        self.album_art.setPixmap(
            QPixmap("static/images/default_album_art.png") if os.path.exists(
"static/images/default_album_art.png") else QPixmap())


    def load_lyrics(self, file):
        self.lyrics = SynchronizedLyrics(file)
        self.lyrics_display.set_lyrics(self.lyrics.lines, self.lyrics.is_synchronized())
        self.update_lyrics_display()

    def update_lyrics_display(self):
        if self.lyrics and self.lyrics.lines:
            idx = self.lyrics.get_current_line(
                self.player.position()) if self.lyrics.is_synchronized() else -1
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
            next_path = self.playlist[next_idx]
            while next_path == "None":
                next_idx += 1
                if not (0 <= next_idx < len(self.playlist) - 1):
                    return
                next_path = self.playlist[next_idx]
            if not (0 <= next_idx < len(self.playlist) - 1):
                return
            self.load_track(next_idx)

    def toggle_play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def update_play_button(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            pixmap = QPixmap.fromImage(self.sub_images[1])
        else:
            pixmap = QPixmap.fromImage(self.sub_images[0])
        self.play_button.setIcon(QIcon(pixmap))

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
            if hasattr(self, '_cue_next') and self._cue_next is not None:
                next_idx = self._cue_next
                self._cue_next = None
                self.load_track(next_idx)
        #    else:
         #       self.next_track()

    def handle_error(self, error, error_string):
        if error != QMediaPlayer.NoError:
            self.next_track()
            self.status_bar.showMessage("Playback Error: " + error_string)
            self.update_play_button()

    def on_metadata_changed(self):
        path = self.playlist[self.current_index]
        if self.is_local_file(path):
            md = self.player.metaData()
            if not md.isEmpty():
                self.update_metadata(self.current_index)

    def move_to_top(self):
        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.text.setTextCursor(cursor)

    @Slot(dict)
    def on_receive_metadata(self, data):
        if self.meta_worker:
            self.meta_worker.mutex.unlock()
        file = self.playlist[self.current_index]
        if not data:
            self.status_bar.showMessage(
                "Remote metadata fetch error:")
        else:
            if 'error' in data['retrieved_metadata']:
                self.status_bar.showMessage(f'Error retrieving metadata: {data["retrieved_metadata"]["error"]}')
            else:
                self.meta_data = data['retrieved_metadata']
                title = self.meta_data.get('title', file.display_text)
                artist = self.meta_data.get('artist', "--")
                album = self.meta_data.get('album', "--")
                year = self.meta_data.get('year', "--")
                codec = self.meta_data.get('codec', "--").replace('audio/', '')
              #  self.set_album_art(path)

                self.set_metadata_label()
                self.year_label.setText('Year: ' + self.meta_data['year'])
                self.codec_label.setText(codec)
                self.load_lyrics(file)
                self.set_album_art(file)
                if self.meta_data:
                    for key in self.meta_data:
                        if key != 'picture' and key != 'lyrics':
                            self.text.append(f"{key}: {self.meta_data[key]}")
                self.move_to_top()

    def on_metadata_error(self, error_message):
        """Handle metadata error"""
        self.meta_worker.mutex.unlock()
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()

    def cleanup_metadata(self):
        """Clean up after scan completion"""
        # Remove progress bar and clear status

        if self.progress:
            self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()

        # Clean up worker reference
        if self.meta_worker:
            self.meta_worker.deleteLater()
            self.meta_worker = None

    def get_audio_metadata(self, file_path):
        """Extract metadata from audio file with comprehensive error handling"""
        try:
            self.status_bar.showMessage(f"Extracting metadata from: {file_path}")

            if not os.path.exists(file_path):
                self.status_bar.showMessage(f"File does not exist: {file_path}")
                return None

            audio_file = File(file_path)
            if audio_file is None:
                self.status_bar.showMessage(f"Could not read audio file: {file_path}. Make sure the file exists.")
                return None

            metadata = {
                'artist'  : '',
                'title'   : '',
                'album'   : '',
                'year'    : '',
                'duration': 0,
                'lyrics'  : '',
                'codec'   : '',
                'picture' : None
            }

            # Get basic metadata
            try:
                if 'TPE1' in audio_file:  # Artist
                    metadata['artist'] = str(audio_file['TPE1'])
                elif 'ARTIST' in audio_file:
                    metadata['artist'] = str(audio_file['ARTIST'][0])
                elif '©ART' in audio_file:
                    metadata['artist'] = str(audio_file['©ART'][0])
            except Exception as e:
                self.status_bar.showMessage(
                    f"Error reading artist metadata from {file_path}: {str(e)}")

            try:
                if 'TIT2' in audio_file:  # Title
                    metadata['title'] = str(audio_file['TIT2'])
                elif 'TITLE' in audio_file:
                    metadata['title'] = str(audio_file['TITLE'][0])
                elif '©nam' in audio_file:
                    metadata['title'] = str(audio_file['©nam'][0])
            except Exception as e:
                self.status_bar.showMessage(
                    f"Error reading title metadata from {file_path}: {str(e)}")

            try:
                if 'TALB' in audio_file:  # Album
                    metadata['album'] = str(audio_file['TALB'])
                elif 'ALBUM' in audio_file:
                    metadata['album'] = str(audio_file['ALBUM'][0])
                elif '©alb' in audio_file:
                    metadata['album'] = str(audio_file['©alb'][0])
            except Exception as e:
                self.status_bar.showMessage(
                    f"Error reading album metadata from {file_path}: {str(e)}")

            try:
                if 'TDRC' in audio_file:  # Year
                    metadata['year'] = str(audio_file['TDRC'])
                elif 'DATE' in audio_file:
                    metadata['year'] = str(audio_file['DATE'][0])
                elif '©day' in audio_file:
                    metadata['year'] = str(audio_file['©day'][0])
            except Exception as e:
                self.status_bar.showMessage(
                    f"Error reading year metadata from {file_path}: {str(e)}")

            # Duration
            try:
                if audio_file.info:
                    metadata['duration'] = int(audio_file.info.length)
            except Exception as e:
                self.status_bar.showMessage(f"Error reading duration from {file_path}: {str(e)}")

            # Lyrics
            try:
                lrc_path = os.path.splitext(file_path)[0] + ".lrc"
                if os.path.exists(lrc_path):
                    with open(lrc_path, encoding='utf-8-sig') as f:
                        metadata['lyrics'] = f.read()
                else:
                    # FLAC/Vorbis
                    if audio_file.__class__.__name__ == 'FLAC':
                        for key in audio_file:
                            if key.lower() in ('lyrics', 'unsyncedlyrics',
                                               'lyric'):
                                metadata['lyrics'] = audio_file[key][0]
                        # MP3 (ID3)
                    elif hasattr(audio_file, 'tags') and audio_file.tags:
                        # USLT (unsynchronized lyrics) is the standard for ID3
                        for k in audio_file.tags.keys():
                            if k.startswith('USLT') or k.startswith('SYLT'):
                                metadata['lyrics'] = str(audio_file.tags[k])
                            if k.lower() in ('lyrics', 'unsyncedlyrics',
                                             'lyric'):
                                metadata['lyrics'] = str(audio_file.tags[k])
                        # MP4/AAC
                    elif hasattr(audio_file, 'tags') and hasattr(
                            audio_file.tags, 'get'):
                        if audio_file.tags.get('\xa9lyr'):
                            metadata['lyrics'] = audio_file.tags['\xa9lyr'][0]
                    else:
                        metadata['lyrics'] = "--"
            except Exception as e:
                self.status_bar.showMessage(f"Error reading lyrics from {file_path}: {str(e)}")

            # Codec
            try:
                codec = audio_file.mime[0] if hasattr(audio_file,
                                                      'mime') and audio_file.mime else audio_file.__class__.__name__

                # Sample rate and bitrate
                sample_rate = getattr(audio_file.info, 'sample_rate', None)
                bits = getattr(audio_file.info, 'bits_per_sample', None)
                bitrate = getattr(audio_file.info, 'bitrate', None)
                if codec == 'audio/mp3':
                    metadata['codec'] = codec + ' ' + str(
                        sample_rate / 1000) + 'kHz ' + str(
                        round(bitrate / 1000)) + 'kbps'
                else:
                    metadata['codec'] = codec + ' ' + str(
                        sample_rate / 1000) + 'kHz/' + str(
                        round(bits)) + 'bits  ' + str(
                        round(bitrate / 1000)) + 'kbps'
            except Exception as e:
                self.status_bar.showMessage(f"Error reading codec from {file_path}: {str(e)}")

            # Album art
            try:
                if 'APIC:' in audio_file:
                    metadata['picture'] = audio_file['APIC:'].data
                elif hasattr(audio_file, 'pictures') and audio_file.pictures:
                    metadata['picture'] = audio_file.pictures[0].data
                elif 'covr' in audio_file:
                    metadata['picture'] = audio_file['covr'][0]
            except Exception as e:
                self.status_bar.showMessage(
                    f"Error reading album art from {file_path}: {e}")

            self.status_bar.showMessage(f"Successfully extracted metadata from: {file_path}")
            return metadata

        except Exception as e:
            self.status_bar.showMessage( f"Error extracting metadata from {file_path}: {str(e)}")
            return None

    def update_metadata(self, index):
        self.text.clear()
        file = self.playlist[index]
        if file.item_type != "song_title":
            return
        if file.is_remote:
            url = rf"http://{file.server}:5000/get_song_metadata/{file.path}"
            self.meta_worker = Worker('meta', url)
            self.meta_worker.work_completed.connect(
                self.on_receive_metadata)
            self.meta_worker.work_error.connect(self.on_metadata_error)
            self.meta_worker.finished.connect(self.cleanup_metadata)

            # Start the async operation
            self.meta_worker.start()
            self.meta_worker.mutex.lock()
        else:
            # local fallback
            self.meta_data = None
            self.meta_data = self.get_audio_metadata(file.path)
            self.set_metadata_label()
            if self.meta_data['year'] is None:
                self.year_label.setText('Year: ---')
            else:
                self.year_label.setText('Year: ' + self.meta_data['year'])
            codec = self.meta_data['codec']
            self.codec_label.setText(codec.replace('audio/', ''))
            self.load_lyrics(file)
            self.set_album_art(file)
            meta_list = mutagen.File(file.path).pprint().split('=')
            new_meta_list = [meta_list[0]]
            for m in range(len(meta_list) - 1):
                if (not 'LYRICS' in meta_list[m]) and (not 'lyrics' in meta_list[m]):
                    new_meta_list.append(meta_list[m + 1])
            new_meta_str = ': '.join([str(s) for s in new_meta_list])
            new_meta_str = new_meta_str.replace('LYRICS:', 'DATE:')
            final_meta = new_meta_str.split('\n: ')
            for item in final_meta:
                self.text.append(item)
            self.move_to_top()



    def set_metadata_label(self):
        '''Sets metadata labels, splitting them in multiple lines if necessary'''
        if not self.meta_data or "error" in self.meta_data:
            path = self.playlist[self.current_index].path
            title = self.playlist[self.current_index].display_text #  os.path.basename(path)
            artist = album = year = codec = "--"
            self.title_label.setText('Title: ' + title)
            self.artist_label.setText('Artist: ' + artist)
            self.album_label.setText('Album: ' + album)
            self.year_label.setText('Year: ' + year)
            self.codec_label.setText('Codec: ' + codec)
            return

        title = self.meta_data['title']
        artist = self.meta_data['artist']
        album = self.meta_data['album']
        if len(title) > 41:
            multiline_title = title[:41] + '\n         '
            l = (len(title) // 41)
            for i in range(1, l):
                multiline_title += title[i * 41:(i + 1) * 41] + '\n         '
            self.title_label.setText(
                'Title: {0}{1}'.format(multiline_title, title[(l * 41):]))
        else:
            self.title_label.setText('Title: ' + title)
        if len(artist) > 40:
            multiline_artist = artist[:40] + '\n          '
            l = (len(artist) // 40)
            for i in range(1, l):
                multiline_artist += artist[
                                        i * 40:(i + 1) * 40] + '\n          '
            self.artist_label.setText(
                'Artist: {0}{1}'.format(multiline_artist, artist[(l * 40):]))
        else:
            self.artist_label.setText('Artist: ' + artist)
        if len(album) > 35:
            multiline_album = album[:35] + '\n             '
            l = (len(album) // 35)
            for i in range(1, l):
                multiline_album += album[
                                       i * 35:(i + 1) * 35] + '\n             '
            self.album_label.setText(
                'Album: {0}{1}'.format(multiline_album, album[(l * 35):]))
        else:
            self.album_label.setText('Album: ' + album)
      #  self.reveal_label.setText(self.meta_data["title"])

    def get_info(self):
        meta = self.player.metaData()
        title = meta.stringValue(QMediaMetaData.Title) or None
       # index = self.playlist_widget.currentRow()
       # path = self.playlist[index]
        artist = self.meta_data.get('artist', None)
        album = self.meta_data.get('album', None)
      #  album_artist = meta.stringValue(QMediaMetaData.AlbumArtist) or meta.stringValue(QMediaMetaData.Author) or None
        summ = self.get_wiki_summary(artist)
        self.text.clear()
        self.text.append(summ)
        summ = self.get_wiki_summary(f"{title} ({artist} song)")
        if summ == f"No results for '{title} ({artist} song)'." or summ == f"No suitable article found for '{title} ({artist} song)'":
            summ = self.get_wiki_summary(f'{title} (record)')
        if summ == f"No results for '{title} (record)'." or summ == f"No suitable article found for '{title} (record)'":
            summ = self.get_wiki_summary(title)
        if summ == f"No results for '{title}'." or summ == f"No suitable article found for '{title}'":
            summ = self.get_wiki_summary(f'{album} ({artist} album)')
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

    def extract_year(self, meta):
        # Try from Qt meta first (works for MP3/MP4, rarely for FLAC)
        date_val = meta.value(QMediaMetaData.Date) if hasattr(meta,
                                                              "value") else None
        if date_val:
            if isinstance(date_val, QDate):
                return str(date_val.year())
            if isinstance(date_val, str):
                match = re.search(r'\b(\d{4})\b', date_val)
                if match:
                    return match.group(1)
            date_str = str(date_val)
            match = re.search(r'\b(\d{4})\b', date_str)
            if match:
                return match.group(1)
        # If FLAC, try mutagen
        audio_path = self.playlist[self.current_index]
        if audio_path.lower().endswith(".flac"):
            try:
                audio = FLAC(audio_path)
                for tag in ("date", "year", "year_released"):
                    if tag in audio:
                        return audio[tag][0][:4]
            except Exception:
                pass
        return "--"

    def extract_audio_info(self):
        path = self.playlist[self.current_index]
        if self.is_remote_file(path):
            try:
                if self.meta_data and 'codec' in self.meta_data and self.meta_data[
                    'codec']:
                    codec = self.meta_data.get('codec')
                    return codec
            except Exception as e:
                self.status_bar.showMessage("Remote metadata fetch error: " + str(e))
        else:
            audio = File(self.playlist[self.current_index])
            if not audio:
                self.status_bar.showMessage(f"{audio} is not an audio file, or it is unsupported or corrupted.")
                return None

            # Codec
            codec = audio.mime[0] if hasattr(audio,
                                             'mime') and audio.mime else audio.__class__.__name__

            # Sample rate and bitrate
            sample_rate = getattr(audio.info, 'sample_rate', None)
            bits = getattr(audio.info, 'bits_per_sample', None)
            bitrate = getattr(audio.info, 'bitrate', None)
            if codec == 'audio/mp3':
                return codec + ' ' + str(sample_rate/1000) + 'kHz ' + str(round(bitrate/1000)) + 'kbps'
            else:
                return codec + ' ' + str(sample_rate/1000) + 'kHz/' + str(round(bits)) + 'bits  ' + str(round(bitrate/1000)) + 'kbps'

        # --- Gap Killer (experimental)

    def on_buffer(self, buf):
        self._probe_buffer(buf)

    def _probe_buffer(self, buffer):
        if not self.skip_silence:
            self._silence_ms = 0
            return
        try:
            fmt = buffer.format()
            if fmt.sampleFormat() not in (fmt.Int16, fmt.Int8, fmt.Int32,
                                          fmt.Float):
                return
            frames = buffer.frameCount()
            if frames <= 0:
                return
            data = buffer.data()
            import array, struct
            if fmt.sampleFormat() == fmt.Float:
                floats = [abs(struct.unpack_from('f', data, i)[0]) for i in
                          range(0, len(data), 4)]
                if not floats: return
                rms = math.sqrt(sum(x * x for x in floats) / len(floats))
            elif fmt.sampleFormat() == fmt.Int16:
                arr = array.array('h')
                arr.frombytes(data[:len(data) // 2 * 2])
                if not arr: return
                norm = [abs(x) / 32768.0 for x in arr]
                rms = math.sqrt(sum(x * x for x in norm) / len(norm))
            elif fmt.sampleFormat() == fmt.Int8:
                arr = array.array('b')
                arr.frombytes(data)
                if not arr: return
                norm = [abs(x) / 128.0 for x in arr]
                rms = math.sqrt(sum(x * x for x in norm) / len(norm))
            else:
                arr = array.array('i')
                arr.frombytes(data[:len(data) // 4 * 4])
                if not arr: return
                norm = [abs(x) / 2147483648.0 for x in arr]
                rms = math.sqrt(sum(x * x for x in norm) / len(norm))

            db = 20 * math.log10(rms) if rms > 0 else -120
            if db < self.silence_threshold_db:
                self._silence_ms += buffer.duration() / 1000.0
                self.gap_status.setText(
                    f"Silent {self._silence_ms:.1f}ms @ {db:.1f}dB")
                if self._silence_ms >= self.silence_min_duration * 1000.0:
                    self._silence_ms = 0
                    p = self.current_player()
                    if p.duration() - p.position() < 12_000:
                        self.next_track()
                    else:
                        p.setPosition(
                            min(p.position() + 10_000, p.duration() - 1000))
                        self.gap_status.setText("Skipped silence")
            else:
                self._silence_ms = 0
                self.gap_status.setText("Monitoring")
        except Exception:
            pass


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
            'Scanning your Music Library. Please Wait, it might take some time depending on the library size'
        )

        audio_files, playlist_files = self.scan_for_audio_files(folder_path)
        # Add to database
        added_songs = self.add_songs_to_database(audio_files)
        added_playlists = self.add_playlists_to_database(playlist_files)

        success_msg = f'Successfully added {added_songs} songs and {added_playlists} playlists to the database.'
        self.status_bar.showMessage(success_msg, 8)
        QMessageBox.information(self,'info', success_msg)



    def delete_missing_songs(self):
        """Delete missing audio files to database with error handling"""
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
            for song_id, path in db_songs:
                if not os.path.exists(path):
                    songs_to_delete.append(song_id)
                    self.status_bar.showMessage(
                        f"File deleted externally, removing from DB: {path}")
                    deleted_songs += 1

                # Perform the deletion (if any)
            try:
                if songs_to_delete:
                    # The '?' allows safe parameter passing for multiple values
                    while len(songs_to_delete) > 999:
                        placeholders = ', '.join(['?'] * 999)
                        sql = f"DELETE FROM Songs WHERE id IN ({placeholders})"
                        cursor.execute(sql, songs_to_delete[:999])
                        for item in range(999):
                            songs_to_delete.pop(0)

                    placeholders = ', '.join(['?'] * len(songs_to_delete))
                    sql = f"DELETE FROM Songs WHERE id IN ({placeholders})"
                    cursor.execute(sql, songs_to_delete)
                # Delete duplicates
                cursor.execute('''
                    DELETE FROM Songs WHERE ROWID NOT IN (SELECT MIN(ROWID) FROM Songs GROUP BY path);
                ''')
            except sqlite3.Error as e:
                QMessageBox.critical(self, "Error", f"Database error deleting songs from db: {str(e)}")
                errors += 1
            except Exception as e:
                QMessageBox.critical(self, "Error",
                    f"Unexpected error deleting songs from db: {str(e)}")
                errors += 1

            conn.commit()
            conn.close()
            if deleted_songs > 0:
                self.status_bar.showMessage(
                f"Successfully deleted {deleted_songs} songs from database")
            if errors > 0:
                QMessageBox.critical(self, "Error",
                    f"Encountered {errors} errors while deleting songs")

            return deleted_songs

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error deleting songs from database: {str(e)}")
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
                        f"Playlist deleted externally, removing from DB: {path}")
                    deleted_playlists += 1

            # 3. Perform the deletion (if any)
            try:
                if playlists_to_delete:
                    # The '?' allows safe parameter passing for multiple values
                    placeholders = ', '.join(['?'] * len(playlists_to_delete))
                    sql = f"DELETE FROM Playlists WHERE id IN ({placeholders})"
                    cursor.execute(sql, playlists_to_delete)
                # Delete duplicates
                cursor.execute('''
                                DELETE FROM Playlists WHERE ROWID NOT IN (SELECT MIN(ROWID) FROM Playlists GROUP BY path);
                            ''')
            except sqlite3.Error as e:
                QMessageBox.critical(self, "Error",
                    f"Database error deleting playlists from db: {str(e)}")
                errors += 1
            except Exception as e:
                QMessageBox.critical(self, "Error",
                    f"Unexpected error deleting playlists from db: {str(e)}")
                errors += 1

            conn.commit()
            conn.close()
            if deleted_playlists > 0:
                self.status_bar.showMessage(
                f"Successfully deleted {deleted_playlists} playlists from database", 4)
            else:
                self.status_bar.showMessage(
                                        f"No playlists were deleted from database", 4)
            if errors > 0:
                QMessageBox.critical(self, "Error",
                    f"Encountered {errors} errors while deleting playlists")

            return deleted_playlists

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error deleting playlists from database: {str(e)}")
            return 0

    def purge_library(self):
        folder_path = self.selectDirectoryDialog()
        if not folder_path:
            return
        # Update status bar and show progress
        self.status_bar.showMessage(
            'Scanning your Music Library for deleted songs and playlists. '
            'Please Wait, it might take some time depending on the library size'
        )
        self.status_bar.repaint()
        progress = QProgressBar()
        progress.setValue(50)
        self.status_bar.addWidget(progress)
        self.status_bar.repaint()
        try:
            # Check for deleted audio files and playlists
            self.status_bar.showMessage("Starting library purge")

            # Add to database
            deleted_songs = self.delete_missing_songs()
            deleted_playlists = self.delete_missing_playlists()
            if deleted_songs == 0 and deleted_playlists == 0:
                success_msg = ('No missing/duplicate songs and playlists were found.\n'
                               'No deletions were made')
            else:
                success_msg = f'Successfully deleted {deleted_songs} songs and {deleted_playlists} playlists from the database.'
            self.status_bar.removeWidget(self.progress)
            QMessageBox.information(self, 'info',  success_msg)


        except Exception as e:
            QMessageBox.critical(self, "Error",f"Error during library purge: {str(e)}")


    def get_local_playlists(self):
        self.playlist_widget.clear()
        self.playlist.clear()
        conn = sqlite3.connect('Music.db')
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
                pl.api_url = ''
                pl.is_remote = False
                pl.id = item[0]
                self.playlist.append(pl)
                self.playlist_widget.addItem(item[1])
            self.playlist_label.setText('Local Playlists: ')
            self.status_bar.clearMessage()
        except Exception as e:
            self.status_bar.clearMessage()
            QMessageBox.critical(self, "Error", str(e))



    def get_playlists(self):
        self.playlist_label.setText('Loading Playlists from Server')
        self.status_bar.showMessage(
            'Loading Playlists from Server. Please Wait, it might take some time...')
        self.status_bar.repaint()
        progress = QProgressBar()
        progress.setValue(50)
        self.status_bar.addWidget(progress)
        self.status_bar.repaint()
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
        if 'error' in data:
            QMessageBox.warning(self, "Error", data['error'])
        self.status_bar.repaint()

        try:
            self.clear_playlist()
            playlists = data['retrieved_playlists']
            for item in playlists:
                pl = ListItem()
                pl.item_type = "playlist"
                pl.display_text = os.path.basename(item['name'])
                pl.path = item['name']
                pl.api_url = self.api_url
                pl.is_remote = True
                pl.id = item['id']
                self.playlist.append(pl)
                self.playlist_widget.addItem(pl.display_text)
            self.playlist_label.setText('Playlists from Server: ')
            self.status_bar.clearMessage()
        except Exception as e:
            self.status_bar.clearMessage()
            QMessageBox.critical(self, "Error",
                                 "Server Search error: Make sure the Server is Up and Connected")

    def on_playlists_error(self, error_message):
        """Handle error"""
        if error_message == '':
            error_message = f'Remote Server not responding.\nMake sure the Server is Up and Connected'
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()

    def cleanup_playlists(self):
        """Clean up after scan completion"""
        # Remove progress bar and clear status
        self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()

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
        self.playlist_label.setText('Getting local song list')
        self.status_bar.showMessage(
            'Getting local song list. Please Wait, it might take some time...')
    #    self.status_bar.repaint()
        progress = QProgressBar()
        progress.setValue(50)
        self.status_bar.addWidget(progress)
        self.status_bar.repaint()
        self.playlist_widget.clear()
        self.playlist.clear()
        try:
            conn = sqlite3.connect('Music.db')
            cursor = conn.cursor()
            if query == "song_title":
                selection = "SELECT id, artist, song_title, album, path, file_name FROM Songs ORDER BY artist ASC"
            elif query == "artist":
                selection = f"SELECT DISTINCT artist FROM Songs ORDER BY artist ASC"
            else:
                selection = f"SELECT DISTINCT album, artist FROM Songs ORDER BY artist ASC"
            cursor.execute(selection)
            results = cursor.fetchall()
            conn.close()

            self.status_bar.showMessage(f"Retrieved {len(results)} {query}s. Creating {query} list.")
            self.clear_playlist()
            files = []
            for r in results:
                song = ListItem()
             #   self.get_audio_metadata(r[4])
                if query == 'song_title':
                    song.display_text = f"{ r[1]} - {r[2]} ({ r[3]})"
                elif query == "artist":
                    song.display_text = r[1]
                else:
                    if r[3] in files:
                        continue
                    else:
                        song.display_text = r[3]
                song.is_remote = False
                song.item_type = query
                song.path = r[4]

                files.append(song)
            self.playlist_label.setText(f'{query} List: ')


        except sqlite3.Error as e:
            QMessageBox.critical(self, "Error",f"Database error getting query: {str(e)}")
        except Exception as e:
            QMessageBox.critical(self, "Error",f"Error getting query: {str(e)}")

        self.add_files(files)
        self.status_bar.showMessage(
            'List loaded. Enjoy!')



    def get_list(self, query):
        self.is_local = False
        self.remote_base = self.api_url
        self.playlist_label.setText(f'Getting {query} list from Server')
        self.status_bar.showMessage(
            f'Getting {query} list from Server. Please Wait, it might take '
            'some time...')
        self.status_bar.repaint()
        progress = QProgressBar()
        progress.setValue(50)
        self.status_bar.addWidget(progress)
        self.status_bar.repaint()
        self.playlist_widget.clear()
        self.playlist.clear()
        self.songs_worker = Worker(query, f'{self.api_url}/get_all')
        self.songs_worker.work_completed.connect(self.receive_list)
        self.songs_worker.work_error.connect(self.on_songs_error)
        self.songs_worker.finished.connect(self.cleanup_songs)

        # Start the async operation
        self.songs_worker.start()
        self.songs_worker.mutex.lock()



    @Slot(dict)
    def receive_list(self, retrieved: dict):
        """Handle successful playlist retrieval completion"""
        if self.songs_worker:
            self.is_local = False
            self.songs_worker.mutex.unlock()
        else:
            self.is_local = True
        if 'error' in retrieved:
            QMessageBox.warning(self, "Error", retrieved['error'])
        self.status_bar.repaint()

        try:
            self.clear_playlist()
            files = []
            data = retrieved['retrieved']
            if "path" in data[0].keys():
                for file in data:
                    song = ListItem()
                    song.is_remote = not self.is_local
                    song.item_type = 'song_title'
                    song.path = file["path"]
                    song.display_text = f"{file['artist']} - {file['title']} ({file['album']})"
                    files.append(song)
                self.playlist_label.setText('Songs List: ')
            elif "artist" in data[0].keys():
              #  files = list(itertools.repeat("artist", len(self.songs)))
                for file in data:
                    song = ListItem()
                    song.is_remote = not self.is_local
                    song.item_type = 'artist'
                    song.path = ''
                    song.display_text = file['artist']
                    files.append(song)
                self.playlist_label.setText('Artists List: ')
            elif "album" in data[0].keys():
              #  files = list(itertools.repeat("album", len(self.songs)))
              for file in data:
                  song = ListItem()
                  song.is_remote = not self.is_local
                  song.item_type = 'album'
                  song.path = ''
                  song.display_text = f"{file['album'][1]} - {file['album'][0]}"
                  files.append(song)
              self.playlist_label.setText('Album List: ')

          #  self.playlist_label.setText('Songs List: ')
            self.status_bar.clearMessage()

            self.add_files(files)
            self.status_bar.showMessage(
                'List loaded. Enjoy!')
        except Exception as e:
            self.status_bar.clearMessage()
            QMessageBox.critical(self, "Error",
                                 f"Server error: {str(e)} \nMake sure the Server is Up and Connected")

    def on_songs_error(self, error_message):
        """Handle error"""
        if error_message == '':
            error_message = f'Remote Server not responding.\nMake sure the Server is Up and Connected'
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()


    def cleanup_songs(self):
        """Clean up after scan completion"""
        # Remove progress bar and clear status
     #   self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()

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
        data = pl_data['pl']
        if data and data['success']:
            songs = []
            idx = self.playlist_widget.currentRow()
            playlist_name = data['name']
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
            self.status_bar.showMessage(
                f'Playlist {playlist_name} loaded. Enjoy!')

    def on_pl_error(self, error_message):
        """Handle playlist error"""
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()


    def cleanup_pl(self):
        """Clean up after scan completion"""
        # Remove progress bar and clear status
     #   self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()

        # Clean up worker reference
        if self.pl_worker:
            self.pl_worker.deleteLater()
            self.pl_worker = None

    def parse_playlist_file(self, playlist_path):
        """Parse playlist file and return list of media files with error handling"""
        try:
            self.status_bar.showMessage(f"Parsing playlist: {playlist_path}")

            if not os.path.exists(playlist_path):
                QMessageBox.critical(self,'error', f"Playlist file does not exist: {playlist_path}")
                return []

            playlist = []
            playlist_dir = os.path.dirname(playlist_path)
            line_count = 0
            try:
                with open(playlist_path, 'r', encoding='utf-8-sig') as f:
                    lines = f.readlines()
            except UnicodeDecodeError:
                # Try with ANSI encoding if UTF-8 fails
                try:
                    with open(playlist_path, 'r', encoding='ANSI') as f:
                        lines = f.readlines()
                except UnicodeDecodeError:
                    try:
                        # Try to guess the encoding if UTF-8 and ANSI fail
                        from charset_normalizer import from_path
                        result = from_path(playlist_path).best()
                        with open(playlist_path, 'r',
                                  encoding=result.encoding) as f:
                            lines = f.readlines()
                    except Exception as e:
                        QMessageBox.critical(self,"error", str(e))
                        return playlist

            for line in lines:
                line_count += 1
                try:
                    line = line.strip()
                    line = line.strip('.\\')
                    if not sys.platform.startswith("win"):
                        line = line.replace("\\", "/")
                    if line and not line.startswith(('#', '﻿#')):
                        # Convert relative path to absolute path
                        if not os.path.isabs(line):
                            line = os.path.join(playlist_dir, line)

                        if os.path.exists(line):
                            playlist.append(line)
                            self.status_bar.showMessage(f"Added to playlist: {line}")
                        else:
                            QMessageBox.critical(self,"warning",
                                f"File not found in playlist (line {line_count}): {line}")

                except Exception as e:
                    QMessageBox.critical(self,"warning",
                        f"Error processing playlist line {line_count}: {e}")

            self.status_bar.showMessage(
                f"Parsed playlist with {len(playlist)} valid files")
            return playlist

        except Exception as e:
            QMessageBox.critical(self,"error",
                                 f"Error parsing playlist {playlist_path}: {e}")
            return []


    def play_selected_playlist(self):
        idx = self.playlist_widget.currentRow()
        item = self.playlist_widget.currentItem()
        file = self.playlist[idx]
        if file.item_type == "cover":
            return
        # item_ext = Path(item.text()).suffix
        elif file.item_type == 'artist':
            self.search_tracks('artist', file.display_text)
        elif file.item_type == 'album':
            dash = file.display_text.find(' - ')
            self.search_tracks('album', file.display_text[dash+3:])
            return
        elif file.item_type == 'song_title':
            self.play_selected_track(item)
        elif file.item_type == 'playlist':
            playlist_id = file.id
            if not file.is_remote:
                try:
                    conn = sqlite3.connect('Music.db')
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT path, PL_name FROM Playlists WHERE id = ?",
                        (playlist_id,))
                    playlist_data = cursor.fetchone()
                    conn.close()

                    if not playlist_data:
                        QMessageBox.critical(self,'error',
                            f"Playlist not found: {playlist_id}")
                        return

                    playlist_path, playlist_name = playlist_data
                    playlist_files = self.parse_playlist_file(playlist_path)

                    self.status_bar.showMessage(
                        f"Loaded playlist '{playlist_name}' with {len(playlist_files)} files")
                    data = {
                        'success' : True,
                        'playlist': playlist_files,
                        'name'    : playlist_name
                    }

                except sqlite3.Error as e:
                    QMessageBox.critical(self,'error',
                        f"Database error loading playlist {playlist_id}: {e}")
                    return
                except Exception as e:
                    QMessageBox.critical(self, 'error',
                        f"Error loading playlist {playlist_id}: {e}")
                    return

                if data:
                    songs = []
                    idx = self.playlist_widget.currentRow()
                    playlist_name = data['name']
                    for line in data["playlist"]:
                        line = line.strip()
                        if not os.path.isabs(line):
                            line = os.path.abspath(
                                os.path.join(os.path.dirname(line), line))
                        if os.path.isfile(line):
                            audio = File(line)
                        else:
                            audio = None
                        if not line or not audio:
                            continue
                        song = ListItem()
                        song.item_type = "song_title"
                        song.display_text = os.path.basename(line)
                        song.path = line
                        song.is_remote = False
                        songs.append(song)
                    self.clear_playlist()
                    self.add_files(songs)
                    self.playlist_label.setText(
                        f"Playlist: {playlist_name}")
                    self.status_bar.showMessage(
                        f'Playlist {playlist_name} loaded. Enjoy!')
            else:
                self.status_bar.showMessage(
                    'Loading Playlist from Server. Please Wait, it might take some time...')
                progress = QProgressBar()
                progress.setValue(50)
                self.status_bar.addWidget(progress)
                self.status_bar.repaint()

                # Create and configure worker thread
                self.pl_worker = Worker('pl', f"{self.api_url}/load_playlist/{playlist_id}")
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
        if os.environ.get(f'WERKZEUG_RUN_MAIN') is None:
            webbrowser.open(self.api_url)

    def remote_web_ui(self):
        try:
            r = requests.post(f"{self.api_url}/web_ui")
            QMessageBox.information(self,'info', r.text)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def remote_desk_ui(self):
        try:
            r = requests.post(f"{self.api_url}/desk_ui")
            QMessageBox.information(self,'info', r.text)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))



    @Slot()
    def on_start_completed(self, result):
        """Handle successful completion"""
        if not result:
            QMessageBox.warning(self, "Error", "Song was not revealed")
            self.status_bar.repaint()
            return
        else:
            self.status_bar.showMessage(result["answer"])
            self.status_bar.repaint()
            QMessageBox.information(self, 'Info:',
                                    result["answer"])



    def on_start_error(self, error_message):
        """Handle error"""
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()


    def cleanup_start(self):
        """Clean up after scan completion"""
        # Remove progress bar and clear status
        #   self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()

        # Clean up worker reference
        if self.start_worker:
            self.start_worker.deleteLater()
            self.start_worker = None

    def reveal_current(self):
        if 0 <= self.current_index < len(self.playlist):
            self.request_reveal.emit(self.playlist[self.current_index])

    def reveal_path(self, song):
        if not song.is_remote:
            if sys.platform.startswith("win"):
                os.startfile(os.path.dirname(song.path))
            elif sys.platform == "darwin":
                os.system(f'open -R "{song.path}"')
            else:
                os.system(f'xdg-open "{os.path.dirname(song.path)}"')
        else:
            folder_path = song.path
            self.status_bar.showMessage(
                'Trying to reveal Song in remote server. Please Wait, it might take some time...'
            )

            # Create and configure progress bar
            self.progress = QProgressBar()
            self.progress.setRange(0, 0)  # Indeterminate progress
            self.status_bar.addWidget(self.progress)
            self.status_bar.repaint()

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


    def quit(self):
      #  save_json(PLAYLISTS_FILE,{"server"   : self.api_url,
      #                                 "playlists": self.playlists})
        save_json(SETTINGS_FILE, {"server"   : self.server,
                                  "mix_method": self.mix_method,
                                  "transition_duration": self.transition_duration,
                                  "gap_enabled"         : self.gap_enabled,
                                  "silence_threshold_db": self.silence_threshold_db,
                                  "silence_min_duration": self.silence_min_duration
                                  })
        self.close()


class Worker(QThread):
    """Worker thread for handling the asynchronous scan operation"""

    # Define signals for communicating with the main thread
    work_completed = Signal(dict)  # Emits scan result data
    work_error = Signal(str)  # Emits error message

    def __init__(self, folder_path, api_url):
        super().__init__()
        self.mutex = QMutex()
        self.folder_path = folder_path
        self.api_url = api_url

    def run(self):
        """Run the async work in a separate thread"""
        result = None
        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Run the async scan
            if self.folder_path is None:
                result = loop.run_until_complete(self.get_playlists_async())
            elif isinstance(self.folder_path, dict):
                result = loop.run_until_complete(self.search_async())
            elif isinstance(self.folder_path, tuple):
                result = loop.run_until_complete(self.purge_library_async())
            elif self.folder_path == 'meta':
                result = loop.run_until_complete(self.get_metadata_async())
            elif self.folder_path in {'song_title', 'artist', 'album'}:
                result = loop.run_until_complete(self.get_songs_async())
            elif self.folder_path == 'pl':
                result = loop.run_until_complete(self.get_pl_async())
            elif self.folder_path == 'server':
                result = loop.run_until_complete(self.check_server_async())
            elif Path(self.folder_path).is_dir():
                if self.api_url.endswith('/scan_library'):
                    result = loop.run_until_complete(self.scan_library_async())
                else:
                    result = loop.run_until_complete(self.reveal_remote_song_async())
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
        """Async function to scan the library"""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    f"{self.api_url}/scan_library",
                    json={'folder_path': self.folder_path}
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception(f"Scan failed: {response.status}")


    async def purge_library_async(self):
        """Async function to purge the library"""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    f"{self.api_url}/purge_library",
                    json={'folder_path': self.folder_path[1]}
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception(f"Purge failed: {response.status}")


    async def search_async(self):
        """Async function to search the library"""
        async with aiohttp.ClientSession() as session:
            async with session.get(self.api_url,
                                   params=self.folder_path) as response:
                if response.status == 200:
                    search_result = await response.json()
                    result = {"search_result": search_result}
                    return result
                else:
                    raise Exception(f"Search failed: {response.status}")


    async def get_playlists_async(self):
        """Async function to get the playlists from server"""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    f"{self.api_url}/get_playlists", timeout=5
            ) as response:
                if response.status == 200:
                    retrieved_playlists =await response.json()
                    result = {'retrieved_playlists': retrieved_playlists}
                    return result
                else:
                    raise Exception(
                        f"Failed to fetch playlists: {response.status}")

    async def get_songs_async(self):
        """Async function to get the playlists from server"""
        async with aiohttp.ClientSession() as session:
            async with session.get(self.api_url, params={"query": self.folder_path}) as response:
                if response.status == 200:
                    retrieved =await response.json()
                    result = {'retrieved': retrieved}
                    return result
                else:
                    raise Exception(f"Failed to fetch songs: {response.status}")

    async def get_pl_async(self):
        """Async function to get a playlist from server"""
        async with aiohttp.ClientSession() as session:
            async with session.get(self.api_url) as response:
                if response.status == 200:
                    retrieved_playlist =await response.json()
                    result = {'pl': retrieved_playlist}
                    return result
                else:
                    raise Exception(f"Failed to fetch playlist: {response.status}")

    async def get_metadata_async(self):
        """Async function to get metadata from server"""
        async with aiohttp.ClientSession() as session:
            async with session.get(self.api_url) as response:
                if response.status == 200:
                    retrieved_metadata = await response.json()
                    result = {'retrieved_metadata': retrieved_metadata}
                    return result
                else:
                    raise Exception(f"Failed to fetch metadata: {response.status}")



    async def check_server_async(self):
        """Async function to check if server is valid"""
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://{self.api_url}:5000', timeout=3) as response:
                if response.status == 200:
                    status = response.status
                    return {'status': status, 'API_URL': self.api_url}
                else:
                    raise Exception(f"Server check failed: {response.status}")


    async def reveal_remote_song_async(self):
        """Async function to reveal playing song in remote server"""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    self.api_url,
                    json=self.folder_path) as response:
                if response.status == 200:
                    answer = await response.json()
                    result = {'answer': answer}
                    return result
                else:
                    raise Exception(f"Failed to fetch songs: {response.status}")


class SynchronizedLyrics:
    def __init__(self, audio=None):
        self.times = []
        self.lines = []
        self.raw_lyrics = ""
        if w.is_remote_file(audio):
            try:
                if w.meta_data and 'lyrics' in w.meta_data and w.meta_data[
                    'lyrics']:
             #       data = r.json()
                    self.raw_lyrics = w.meta_data['lyrics']
                else:
                    self.raw_lyrics = "--"
            except Exception as e:
                w.status_bar.showMessage("Remote lyrics fetch error:" + str(e))
        else:
            if audio.path:
                lrc_path = os.path.splitext(audio.path)[0] + ".lrc"
                if os.path.exists(lrc_path):
                    with open(lrc_path, encoding='utf-8-sig') as f:
                        self.raw_lyrics = f.read()
                else:
                    self.raw_lyrics = self.get_embedded_lyrics(audio.path)
        self.parse_lyrics(self.raw_lyrics)

    def get_embedded_lyrics(self, audio_path):
        audio = File(audio_path)
        if audio is None:
            return ""

            # FLAC/Vorbis
        if audio.__class__.__name__ == 'FLAC':
            for key in audio:
                if key.lower() in ('lyrics', 'unsyncedlyrics', 'lyric'):
                    return audio[key][0]
            return ""

            # MP3 (ID3)
        if hasattr(audio, 'tags') and audio.tags:
            # USLT (unsynchronized lyrics) is the standard for ID3
            for k in audio.tags.keys():
                if k.startswith('USLT') or k.startswith('SYLT'):
                    return str(audio.tags[k])
                if k.lower() in ('lyrics', 'unsyncedlyrics', 'lyric'):
                    return str(audio.tags[k])
            # MP4/AAC
        if hasattr(audio, 'tags') and hasattr(audio.tags, 'get'):
            if audio.tags.get('\xa9lyr'):
                return audio.tags['\xa9lyr'][0]
        return ""

    def parse_lyrics(self, lyrics_text):
        time_tag = re.compile(r"\[(\d+):(\d+)(?:\.(\d+))?\]")
        self.times = []
        self.lines = []
        for line in lyrics_text.splitlines():
            matches = list(time_tag.finditer(line))
            if matches:
                lyric = time_tag.sub('', line).strip()
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
                return max(0, i-1)
        return len(self.lines)-1 if self.lines else -1

    def is_synchronized(self):
        """Return True if lyrics are synchronized (have time tags)."""
        # Synchronized if any time tag is nonzero
        return any(t > 0 for t in self.times)

class LyricsDisplay(QTextEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setReadOnly(True)
        self.setStyleSheet("font-size: 18px; background: #E0F0FF; border-width: 2px; border-color: #7A7EA8; border-style: inset;")
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
        self.instructions_edit.setPlainText("Use Instructions\n\n"
"1. Installation\n"
"The program is Portable. You just unzip the file Web-Media-Server-and-Player.zip\n\n"
"2. Startup\n"
"In the folder you unzipped the program, you run “ecoserver.exe” to start the server and the “advanced_audio_player.exe” to start the player/client.\n"
"You can have any server-player/client combination on any computer on your network, e.g. you can run the ecoserver.exe only on the computer that your music files rely and the Player/client on your HTPC. If you have any music files on more than one computer, you can run the ecoserver.exe on each one of them. The same goes for the “advanced_audio_player.exe”.  You can run it on any computer you use to listen to music.\n\n"
"3. Ecoserver\n"
"Starting the server adds an icon to the hidden icons of the system tray, (a square, black on the outside, white on the inside). By right-clicking on the icon, a mini-menu appears with the following options:\n"
"•  Open in Browser: Opens the program's website, from which the server is managed, as well as the selection and playback of the music is taking place.\n"
"•  Open Desktop Player: Launches “advanced_audio_player.exe”, the desktop application from which the server is managed, as well as the music is selected and played.\n"
"•  Autostart on system boot: Starts the server when the system boots\n"
"•  Quit: Shuts down the server\n"
"4. Audio Player / Client\n"
"It is the desktop application from which the server is managed, as well as the selection and playback of music.\n"
"\n"
"The interface:\n"
"On the left side of the application interface, is the Cue display. It displays the songs cued to play, or the playlists, or the search results, or the lists of all the songs in the music library, or artists or albums. On this Cue display, we can drop songs and/or playlists by drag'n'drop or by choosing them via the menus of the application.  Once the Cue display is filled with songs, it starts playing them immediately. If it displays the list of the music library Playlists, clicking a Playlist it then shows the songs in the playlist and starts playing them immediately. If it displays an artist list, clicking on any artist's name displays all of the artist's songs, sorted by album.\n"
"By clicking on any song in any list, it starts playing.\n"
"At the top right of the list is the Shuffle button to shuffle the songs in the list.\n"
"\n"
"On the right side of the interface, on top there is the search bar. On the left side is a drop-down menu to select the type of search, while on the right there are two buttons, one to search the database of the local computer (the one on which the desktop application is running) and one to search on a remote server on the network. With enter, the search is done on the local computer.\n"
"Below the search bar, the cover art and basic elements of the song that is playing are displayed, while to the right of it, all the metadata. Above the metadata window is the “Push for Artist and Song Info” button. By tapping on it, information about the artist and the song playing is displayed. Below the song's cover and key elements, there's the timer, the playbar, and just below them the play buttons. By clicking on the timer the indicator changes from elapsed time to time remaining for each song. By drag'n'dropping the playbar we proceed the playback forward or backward. Using the three play buttons, we go to the previous or next song, or we pause (and restart) the playback. Below the play buttons appear the lyrics of the song playing, (if embedded or in a .lrc file), which may or may not be synchronized, depending on the lyrics file.\n"
"Below the lyrics there are the options for mixing the songs, through the “Mix Method” menu and the setting of the transition time, as well as the settings of the Gap killer, (which is still in the experimental stage). Finally, at the bottom right is the Reveal button, which displays the song that is playing in File Explorer.\n"
""
"The menus:\n\n"
" There are 3 main menus: Local, Remote and Help.\n"
"Local manages the program's operations on the local computer, while Remote manages the program's operations on a remote server.\n"
"The Local menu options are:\n"
"•	Open Playlist|Load Songs: Displays the open file dialog, to select songs or playlists to play.\n"
"•	Load Playlists: Displays all Playlists in the local computer's library\n"
"•	List all Songs: Displays all songs in the local computer's library\n"
"•	List all Artists: Displays all artists in the local computer's library\n"
"•	List all Albums: Displays all albums in the local computer's library\n"
"•	Scan Library: Displays the folder selection dialog, to select a folder which (its subfolders included) it scans and adds to the local library the audio files and playlists it finds.\n"
"•	Purge Library: Opens the folder selection dialog, to select a folder which (its subfolders included) checks and removes any physical deleted audio and playlist files from the local library.\n"
"•	Save current Cue: Saves the Cue list to a file\n"
"•	Clear Playlist: Clears the Cue list\n"
"•	Launch Web UI. Opens the program's website on the local computer, from which the server is managed, as well as the music is selected and played.\n"
"•	Shutdown Local Server: Shuts down the local server.\n"
"•	Exit: Terminates the operation of the application\n"
"The Remote menu options are:\n"
"•	Connect to Remote: Asks for the name or IP address of a remote computer on which the ecoserver is running and connects to that remote server.\n"
"•	Load Playlists: Displays all Playlists in the remote server's library\n"
"•	List all Songs: Displays all songs in the remote server's library\n"
"•	List all Artists: Displays all artists in the remote server's library\n"
"•	List all Albums: Displays all albums in the remote server's library\n"
"•	Scan Library: Opens the folder selection dialog, to select a remote server's folder which (its subfolders included) it scans and adds to the remote server's library the audio files and playlists it finds.\n"
"•	Purge Library: Opens the folder selection dialog, to select a remote server's folder which (its subfolders included) checks and removes any deleted audio and playlist files from the remote server's library.\n"
"•	Launch Web UI. It opens the program's website on the remote computer, from which the server is managed, as well as the music is selected and played.\n"
"•	Launch Desktop UI: Launches the “advanced_audio_player.exe” on the remote computer, (the desktop application from which the server is managed, as well as the music is selected and played).\n"
"•	Shutdown Local Server: Shuts down the remote server.\n"
"•	Exit: Terminates the operation of the program\n")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon('static/images/favicon.ico'))
    settings = get_settings()
    w = AudioPlayer(settings)
    sys.exit(app.exec())