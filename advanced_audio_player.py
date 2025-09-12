import sys
import os

# from django.contrib.gis.gdal.prototypes.srs import islocal
from PySide6.QtCore import Qt, QDate, QEvent, QUrl, QTimer, QSize, QRect, Signal, QThread, Slot
from PySide6.QtGui import QPixmap, QTextCursor, QImage, QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSlider, QListWidget, QFileDialog, QTextEdit, QListWidgetItem, QMessageBox,
    QComboBox, QSpinBox, QFormLayout, QGroupBox, QLineEdit, QInputDialog, QMenuBar,
    QMenu, QStatusBar,QProgressBar, QFrame, QCheckBox)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaMetaData
import mutagen
from mutagen import File
from mutagen.flac import FLAC
import traceback
from pathlib import Path
from random import shuffle
import re
import math
import json
import asyncio
import aiohttp
import requests
import base64
import webbrowser
import wikipedia
from dotenv import load_dotenv

load_dotenv()
SHUTDOWN_SECRET = os.getenv("SHUTDOWN_SECRET")

# API_URL = "http://localhost:5000"
APP_DIR = Path.home() / "Web-Media-Server-and-Player"
APP_DIR.mkdir(exist_ok=True)
SETTINGS_FILE = APP_DIR / "settings.json"
PLAYLISTS_FILE = APP_DIR / "playlists.json"
wikipedia.set_lang("en")

class AudioPlayer(QWidget):
    request_search = Signal(str, str)
    request_reveal = Signal(str)

    def __init__(self):
        super().__init__()
        # data
        data = self.load_json(PLAYLISTS_FILE, default={"server": "http://localhost:5000", "playlists":[]})
        global API_URL
        API_URL = data["server"]
        self.remote_base = API_URL
        self.playlists = data["playlists"]
        self.settings  = self.load_json(SETTINGS_FILE, default={"crossfade":6})

        # variables
        self.gap_enabled = True
        self.silence_threshold_db = -46
        self.silence_min_duration = 0.5
        self._silence_ms = 0
        self._fade_step = None
        self.fade_timer = None
        self.scan_worker = None
        self.progress = None
        self.setWindowTitle(f"Ultimate Media Player. Current Server: {API_URL}")
        self.resize(1200, 800)
        self.playlist = []
        self.current_index = -1
        self.show_remaining = False
        self.lyrics = None
        self.lyrics_timer = QTimer(self)
        self.lyrics_timer.setInterval(200)
        self.lyrics_timer.timeout.connect(self.update_lyrics_display)
        self.meta_data =None


        # Mixing/transition config
        self.mix_method = "Full"  # Default
        self.transition_duration = 4  # seconds

        # Layout
        layout = QVBoxLayout(self)

        # ----- Menu bar -----
        menubar = QMenuBar(self)

        # File menu
        local_menu = QMenu("&Local", self)
        menubar.addMenu(local_menu)

        self.open_action = QAction("&Open Playlist | Add Songs", self)
        self.open_action.setShortcut(QKeySequence.Open)
        self.open_action.triggered.connect(self.show_playlist_menu)
        local_menu.addAction(self.open_action)

        self.scan_action = QAction("Scan &Library", self)
        self.scan_action.setShortcut(QKeySequence("Ctrl+L"))
        self.scan_action.triggered.connect(self.scan_library)
        local_menu.addAction(self.scan_action)

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

        self.server_action = QAction("&Enter Remote Server", self)
        self.server_action.setShortcut(QKeySequence("Ctrl+E"))
        self.server_action.triggered.connect(self.enter_server)
        remote_menu.addAction(self.server_action)

        self.load_action = QAction("Load &Playlists from Server", self)
        self.load_action.setShortcut(QKeySequence.Print)
        self.load_action.triggered.connect(self.get_playlists)
        remote_menu.addAction(self.load_action)

        self.scan_action = QAction("Scan Remote &Library", self)
        self.scan_action .setShortcut(QKeySequence("Ctrl+R"))
        self.scan_action .triggered.connect(self.scan_remote_library)
        remote_menu.addAction(self.scan_action )

        self.web_action = QAction("Launch &Remote Web UI", self)
        self.web_action.setShortcut(QKeySequence("Ctrl+I"))
        self.web_action.triggered.connect(self.remote_web_ui)
        remote_menu.addAction(self.web_action)

        self.desktop_action = QAction("Launch Remote &Desktop UI", self)
        self.desktop_action.setShortcut(QKeySequence("Ctrl+D"))
        self.desktop_action.triggered.connect(self.remote_desk_ui)
        remote_menu.addAction(self.desktop_action)

        self.shutdown_action = QAction("S&hutdown Remote Server", self)
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
        self.combo.addItems(["artist", "title", "album"])
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search Server for Artist or Song, or Album…")
        self.btn_go = QPushButton("Search Server")
        top.addWidget(self.combo)
        top.addWidget(self.search, 2)
        top.addWidget(self.btn_go)

        # Playlist browser with context menu support
        shuffle_box = QHBoxLayout()
        self.playlist_widget = QListWidget()
        self.playlist_widget.setStyleSheet(
            "font-size: 12px; background-color: lightyellow; opacity: 0.6; border-color: #D4D378; border-width: 2px; border-style: inset;")
        self.playlist_label = QLabel("Playlist")
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
        self.btn_go.clicked.connect(self.on_go)
        self.search.returnPressed.connect(self.on_go)
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



    @Slot(dict)
    def on_server_reply(self, data: dict):
        """Handle successful playlist retrieval completion"""
        if 'error' in data:
            QMessageBox.warning(self, "Scan Error", data['error'])
        self.status_bar.repaint()

     #   status_code = data['status']
        if data['status'] == 200:
          #  global API_URL
            API_URL = data['API_URL']
            self.remote_base = API_URL
            self.setWindowTitle(
                f"Ultimate Media Player. Current Server: {API_URL}")
            self.status_bar.showMessage(
                f'Remote Server is now: {API_URL}', 8000)
            QMessageBox.information(self, 'Success!',
                                    f'Remote Server is now: {API_URL}')
        else:
            QMessageBox.warning(self, 'Error', data['status'])



    def on_server_error(self, error_message):
        """Handle scan error"""
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()


    def cleanup_server(self):
        """Clean up after scan completion"""
        # Remove progress bar and clear status
        #   self.status_bar.removeWidget(self.progress)
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

            self.server_worker = Worker('server',  f'http://{server}:5000')
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
        self.scan_worker = Worker(folder_path, API_URL)
        self.scan_worker.work_completed.connect(self.on_scan_completed)
        self.scan_worker.work_error.connect(self.on_scan_error)
        self.scan_worker.finished.connect(self.cleanup_scan)

        # Start the async operation
        self.scan_worker.start()

    def on_scan_completed(self, data):
        """Handle successful scan completion"""
        if 'error' in data:
            QMessageBox.warning(self, "Scan Error", data['error'])
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
     #   self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()

        # Clean up worker reference
        self.scan_worker.deleteLater()
        self.scan_worker = None

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
                f"{API_URL}/shutdown",
                headers={"X-API-Key": SHUTDOWN_SECRET},
                json={}
            )
            self.status_bar.showMessage(resp.text.replace("\n", ""))
            self.status_bar.repaint()
        except Exception as e:
            QMessageBox.warning(self, "Error",
                                f"Failed to shutdown Remote Server @ "
                                f"{API_URL}:\nMake Sure the Server is Up")


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
            self.status_bar.showMessage(
                f'Searching for {col} {q}. Please Wait...')
            progress = QProgressBar()
            progress.setValue(50)
            self.status_bar.addWidget(progress)
            self.status_bar.repaint()
            self.search_tracks(col, q)

    def search_tracks(self, column: str, query: str):
        q = query.lower()
        params = {"column":column, "query":q}
        url = f"{API_URL}/search_songs"
        try:
            r = requests.get(url, params=params, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data:
                    files = []
                    for track in data:
                        files.append(track["path"])
                    self.clear_playlist()
                    self.add_files(files)
                    return
                else:
                    self.status_bar.showMessage(
                        f'{column} {q} was not found on Server')
                    QMessageBox.information(self, 'Sorry 😞',
                                            f'{column} {q} was not found on Server')

            else:
                self.status_bar.showMessage(r.reason)
        except Exception as e:
            self.status_bar.showMessage("Server Search error: Make sure the Server is Up and Connected")
            QMessageBox.information(self, "Server Search error!", "Make sure the Server is Up and Connected")



    def do_shuffle(self):
        shuffle(self.playlist)
        self.playlist_widget.clear()
        self.current_index = -1
        for song in self.playlist:
            item = QListWidgetItem(os.path.basename(song))
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
        next_path = self.playlist[next_idx]
        if self.is_remote_file(next_path):
            abs_path = next_path.split('5000/')[1]
            next_path = f"{self.remote_base}/serve_audio/{abs_path}"
        self.next_player = QMediaPlayer(self)
        self.next_output = QAudioOutput(self)
        self.next_player.setAudioOutput(self.next_output)
        self.next_player.setSource(QUrl.fromLocalFile(next_path))
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
        elif self.remote_base and not path.startswith("http"):
            # Assume path is a filename, construct full URL
            filename = os.path.basename(path)
            return QUrl(f"{self.remote_base}/{filename}")
        else:
            # Already a URL
            return QUrl(path)

    def load_track(self, idx, auto_play=True, skip_mix_check=False, skip_silence=False):
        if 0 <= idx < len(self.playlist):
            path = self.playlist[idx]
            self.current_index = idx
            # Use the new get_media_source logic
            if self.is_remote_file(path):
                abs_path = path.split('5000/')[1]
                if self.remote_base == None:
                    self.remote_base = path.split('5000/')[0] + '5000/'
                media_url = f"{self.remote_base}/serve_audio/{abs_path}"
            else:
                media_url = self.get_media_source(path)
            self.player.setSource(media_url)
            self.slider.setValue(0)
          #  self.update_metadata(idx)
            #    self.load_lyrics(path)
           # if self.is_local_file(path):
            #    self.set_album_art(path)
            if auto_play:
                self.player.play()
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
        self.add_files(files)

    def eventFilter(self, source, event):
        if source == self.playlist_widget.viewport() and event.type() == QEvent.Drop:
            files = [u.toLocalFile() for u in event.mimeData().urls()]
            self.add_files(files)
            return True
        return super().eventFilter(source, event)

    def show_playlist_menu(self, pos=None):
        menu = QFileDialog(self)
        menu.setFileMode(QFileDialog.ExistingFiles)
        menu.setNameFilters(["Playlists (*.m3u *.m3u8 *.cue)",
                             "Audio files (*.mp3 *.flac *.ogg *.wav *.m4a *.aac *.wma *.opus)", "All files (*)"])
        if menu.exec():
            self.add_files(menu.selectedFiles())

    def add_files(self, files):
        for f in files:
            if os.path.isfile(f):
                ext = os.path.splitext(f)[1].lower()
                if ext in ['.m3u', '.m3u8']:
                    pl = self.load_m3u_playlist(f)
                    self.playlist += pl
                    for i in pl:
                        item = QListWidgetItem(os.path.basename(i))
                        self.playlist_widget.addItem(item)
                    self.playlist_label.setText(f'Playlist: {os.path.basename(f)}')
                elif ext == '.cue':
                    pl = self.load_cue_playlist(f)
                    self.playlist += pl
                    for i in pl:
                        item = QListWidgetItem(os.path.basename(i))
                        self.playlist_widget.addItem(item)
                    self.playlist_label.setText(
                        f'Playlist: {os.path.basename(f)}')
                else:
                    audio = File(f)
                    if audio:
                            self.playlist.append(f)
                            item = QListWidgetItem(os.path.basename(f))
                            self.playlist_widget.addItem(item)
            elif f.startswith("http"):
                # Support adding remote URLs directly
                self.playlist.append(f)
                item = QListWidgetItem(os.path.basename(f))
                self.playlist_widget.addItem(item)
            elif self.remote_base:
                # If remote base is set, treat as filename on remote
                remote_url = f"{self.remote_base}/{f}"
                self.playlist.append(remote_url)
                item = QListWidgetItem(os.path.basename(f))
                self.playlist_widget.addItem(item)
            if self.current_index == -1 and self.playlist:
                self.load_track(0)
        self.status_bar.clearMessage()

    def load_m3u_playlist(self, path):
        tracks = []
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                line = os.path.abspath(os.path.join(os.path.dirname(path), line))
                if os.path.isfile(line):
                    audio = File(line)
                else:
                    audio = None
                if not line or not audio:
                    continue
                tracks.append(os.path.abspath(line))
        return tracks

    def load_cue_playlist(self, path):
        tracks = []
        with open(path, encoding='utf-8') as f:
            for line in f:
                if re.match('^FILE .(.*). (.*)$', line):
                    file_path = line[6:-7]
                    if not os.path.isabs(file_path):
                        file_path = os.path.abspath(
                            os.path.join(os.path.dirname(path), file_path))
                    tracks.append(file_path)
        return tracks

    def play_selected_track(self, item):
        idx = self.playlist_widget.row(item)
       # self.update_metadata(idx)
        self.load_track(idx)

    def show_playlist_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self.playlist_widget)
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
        self.playlist_label.setText('Playlist')
        self.player.stop()
        self.current_index = -1
        self.lyrics_display.clear()
        self.update_play_button()

    def is_remote_file(self, path):
        return self.remote_base and (not os.path.isfile(path) or path.startswith("http"))

    def set_album_art(self, path):
        """
        Sets album art using metadata JSON if provided (remote), otherwise falls back to local extraction.
        """
        if self.is_remote_file(path):
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


    def load_lyrics(self, audio_path):
        self.lyrics = SynchronizedLyrics(audio_path)
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
            self.load_track(self.current_index - 1)

    def next_track(self):
        if self.current_index < len(self.playlist) - 1:
            self.load_track(self.current_index + 1)

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
        path = self.playlist[self.current_index]
        if not data:
            self.status_bar.showMessage(
                "Remote metadata fetch error:")
            title = os.path.basename(path)
            artist = album = year = codec = "--"
        else:
            if 'error' in data:
                QMessageBox.warning(self, "Error retrieving metadata",
                                    data['error'])
                title = os.path.basename(path)
                artist = album = year = codec = "--"
            else:
                self.meta_data = data['retrieved_metadata']
                title = self.meta_data.get('title', os.path.basename(path))
                artist = self.meta_data.get('artist', "--")
                album = self.meta_data.get('album', "--")
                year = self.meta_data.get('year', "--")
                codec = self.meta_data.get('codec', "--").replace('audio/', '')
              #  self.set_album_art(path)

        self.set_metadata_label()
        self.year_label.setText('Year: ' + self.meta_data['year'])
        self.codec_label.setText(codec)
        self.load_lyrics(path)
        self.set_album_art(path)
        if self.meta_data:
            for key in self.meta_data:
                if key != 'picture' and key != 'lyrics':
                    self.text.append(f"{key}: {self.meta_data[key]}")
        self.move_to_top()

    def on_metadata_error(self, error_message):
        """Handle metadata error"""
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()

    def cleanup_metadata(self):
        """Clean up after scan completion"""
        # Remove progress bar and clear status
     #   self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()

        # Clean up worker reference
        self.meta_worker.deleteLater()
        self.meta_worker = None

    def get_audio_metadata(self, file_path):
        """Extract metadata from audio file with comprehensive error handling"""
        try:
            print(f"Extracting metadata from: {file_path}")

            if not os.path.exists(file_path):
                print(f"File does not exist: {file_path}")
                return None

            audio_file = File(file_path)
            if audio_file is None:
                print(f"Could not read audio file: {file_path}")
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
                print(
                    f"Error reading artist metadata from {file_path}: {e}")

            try:
                if 'TIT2' in audio_file:  # Title
                    metadata['title'] = str(audio_file['TIT2'])
                elif 'TITLE' in audio_file:
                    metadata['title'] = str(audio_file['TITLE'][0])
                elif '©nam' in audio_file:
                    metadata['title'] = str(audio_file['©nam'][0])
            except Exception as e:
                print(
                    f"Error reading title metadata from {file_path}: {e}")

            try:
                if 'TALB' in audio_file:  # Album
                    metadata['album'] = str(audio_file['TALB'])
                elif 'ALBUM' in audio_file:
                    metadata['album'] = str(audio_file['ALBUM'][0])
                elif '©alb' in audio_file:
                    metadata['album'] = str(audio_file['©alb'][0])
            except Exception as e:
                print(
                    f"Error reading album metadata from {file_path}: {e}")

            try:
                if 'TDRC' in audio_file:  # Year
                    metadata['year'] = str(audio_file['TDRC'])
                elif 'DATE' in audio_file:
                    metadata['year'] = str(audio_file['DATE'][0])
                elif '©day' in audio_file:
                    metadata['year'] = str(audio_file['©day'][0])
            except Exception as e:
                print(
                    f"Error reading year metadata from {file_path}: {e}")

            # Duration
            try:
                if audio_file.info:
                    metadata['duration'] = int(audio_file.info.length)
            except Exception as e:
                print(f"Error reading duration from {file_path}: {e}")

            # Lyrics
            try:
                lrc_path = os.path.splitext(file_path)[0] + ".lrc"
                if os.path.exists(lrc_path):
                    with open(lrc_path, encoding='utf-8') as f:
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
                print(f"Error reading lyrics from {file_path}: {e}")

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
                print(f"Error reading codec from {file_path}: {e}")

            # Album art
            try:
                if 'APIC:' in audio_file:
                    metadata['picture'] = audio_file['APIC:'].data
                elif hasattr(audio_file, 'pictures') and audio_file.pictures:
                    metadata['picture'] = audio_file.pictures[0].data
                elif 'covr' in audio_file:
                    metadata['picture'] = audio_file['covr'][0]
            except Exception as e:
                print(
                    f"Error reading album art from {file_path}: {e}")

            print(f"Successfully extracted metadata from: {file_path}")
            return metadata

        except Exception as e:
            print(f"Error extracting metadata from {file_path}: {e}")
            print(traceback.format_exc())
            return None

    def update_metadata(self, index):
        self.text.clear()
        file_path = self.playlist[index]
        if self.is_remote_file(file_path):
            filename = file_path.split('5000/')[1]
            url = f"{self.remote_base}/get_song_metadata/{filename}"

            self.meta_worker = Worker('meta', url)
            self.meta_worker.work_completed.connect(
                self.on_receive_metadata)
            self.meta_worker.work_error.connect(self.on_metadata_error)
            self.meta_worker.finished.connect(self.cleanup_metadata)

            # Start the async operation
            self.meta_worker.start()
        else:
            # local fallback
            self.meta_data = None
            self.meta_data = self.get_audio_metadata(file_path)
            self.set_metadata_label()
            self.year_label.setText('Year: ' + self.meta_data['year'])
            codec = self.meta_data['codec']
            self.codec_label.setText(codec.replace('audio/', ''))
            self.load_lyrics(file_path)
            self.set_album_art(file_path)
            meta_list = mutagen.File(file_path).pprint().split('=')
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

        # Create and configure progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Indeterminate progress
        self.status_bar.addWidget(self.progress)
        self.status_bar.repaint()

        # Create and configure worker thread
        self.scan_worker = Worker(folder_path, "http://localhost:5000")
        self.scan_worker.work_completed.connect(self.on_scan_completed)
        self.scan_worker.work_error.connect(self.on_scan_error)
        self.scan_worker.finished.connect(self.cleanup_scan)

        # Start the async operation
        self.scan_worker.start()


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

        self.playlists_worker = Worker(None, API_URL)
        self.playlists_worker.work_completed.connect(self.receive_playlists)
        self.playlists_worker.work_error.connect(self.on_playlists_error)
        self.playlists_worker.finished.connect(self.cleanup_playlists)

        # Start the async operation
        self.playlists_worker.start()

    @Slot(dict)
    def receive_playlists(self, data: dict):
        """Handle successful playlist retrieval completion"""
        if 'error' in data:
            QMessageBox.warning(self, "Scan Error", data['error'])
        self.status_bar.repaint()

        try:
            self.playlists = data['retrieved_playlists']
            for item in self.playlists:
                self.playlist_widget.addItem(item['name'])
            self.playlist_label.setText('Playlists from Server: ')
            self.status_bar.clearMessage()
        except Exception as e:
            self.status_bar.clearMessage()
            QMessageBox.critical(self, "Error",
                                 "Server Search error: Make sure the Server is Up and Connected")

    def on_playlists_error(self, error_message):
        """Handle scan error"""
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()


    def cleanup_playlists(self):
        """Clean up after scan completion"""
        # Remove progress bar and clear status
     #   self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()

        # Clean up worker reference
        self.playlists_worker.deleteLater()
        self.playlists_worker = None


    def on_pl_completed(self, pl_data):
        data = pl_data['pl']
        if data:
            files = []
            idx = self.playlist_widget.currentRow()
            playlist_name = self.playlists[idx]['name']
            for track in data["playlist"]:
                files.append(track)
            self.clear_playlist()
            self.add_files(files)
            self.playlist_label.setText(f"Playlist: {playlist_name}")
            self.status_bar.showMessage(
                f'Playlist {playlist_name} loaded. Enjoy!')

    def on_pl_error(self, error_message):
        """Handle scan error"""
        QMessageBox.critical(self, "Error", error_message)
        self.status_bar.repaint()


    def cleanup_pl(self):
        """Clean up after scan completion"""
        # Remove progress bar and clear status
     #   self.status_bar.removeWidget(self.progress)
        self.status_bar.clearMessage()

        # Clean up worker reference
        self.pl_worker.deleteLater()
        self.pl_worker = None

    def play_selected_playlist(self):
        idx = self.playlist_widget.currentRow()
        item = self.playlist_widget.currentItem()
        if item is not None:
            item_ext = item.text().split('.')[-1]
            if item_ext == 'm3u' or item_ext == 'm3u8' or item_ext == 'cue':
                playlist_id = self.playlists[idx]['id']
                self.status_bar.showMessage(
                    'Loading Playlist from Server. Please Wait, it might take some time...')
                progress = QProgressBar()
                progress.setValue(50)
                self.status_bar.addWidget(progress)
                self.status_bar.repaint()

                # Create and configure worker thread
                self.pl_worker = Worker('pl', f"{API_URL}/load_playlist/{playlist_id}")
                self.pl_worker.work_completed.connect(self.on_pl_completed)
                self.pl_worker.work_error.connect(self.on_pl_error)
                self.pl_worker.finished.connect(self.cleanup_pl)

                try:
                    self.pl_worker.start()
                except Exception as e:
                    QMessageBox.critical(self, "Error", str(e))

    def local_web_ui(self):
        if os.environ.get(f'WERKZEUG_RUN_MAIN') is None:
            webbrowser.open(API_URL)

    def remote_web_ui(self):
        try:
            r = requests.post(f"{API_URL}/web_ui")
            data = r.text
            self.status_bar.showMessage(data)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def remote_desk_ui(self):
        try:
            r = requests.post(f"{API_URL}/desk_ui")
         #   data = r.text
         #   self.status_bar.showMessage(data)
        except Exception as e:
            self.status_bar.showMessage("Error: " + str(e))


    def load_json(self, path: Path, default):
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return default

    def save_json(self, path: Path, obj):
        try:
            path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
            print(path)
        except Exception as e:
            QMessageBox.warning(self,"Error!", str(e))


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
        self.start_worker.deleteLater()
        self.start_worker = None

    def reveal_current(self):
        if 0 <= self.current_index < len(self.playlist):
            self.request_reveal.emit(self.playlist[self.current_index])

    def reveal_path(self, path: str):
        if self.is_local_file(path):
            if sys.platform.startswith("win"):
                os.startfile(os.path.dirname(path))
            elif sys.platform == "darwin":
                os.system(f'open -R "{path}"')
            else:
                os.system(f'xdg-open "{os.path.dirname(path)}"')
        else:
            folder_path = path.split("5000/")[1]
            self.status_bar.showMessage(
                'Trying to reveal Song in remote server. Please Wait, it might take some time...'
            )

            # Create and configure progress bar
            self.progress = QProgressBar()
            self.progress.setRange(0, 0)  # Indeterminate progress
            self.status_bar.addWidget(self.progress)
            self.status_bar.repaint()

            # Create and configure worker thread
            self.start_worker = Worker(folder_path, f"{API_URL}/start")
            self.start_worker.work_completed.connect(self.on_start_completed)
            self.start_worker.work_error.connect(self.on_start_error)
            self.start_worker.finished.connect(self.cleanup_start)

            # Start the async operation
            try:
                self.start_worker.start()
            except Exception as e:
                self.status_bar.showMessage("Error: " + str(e))


    def quit(self):
        self.save_json(PLAYLISTS_FILE,{"server"   : API_URL,
                                       "playlists": self.playlists})
        self.save_json(SETTINGS_FILE, {"crossfade": 6})
        self.close()


class Worker(QThread):
    """Worker thread for handling the asynchronous scan operation"""

    # Define signals for communicating with the main thread
    work_completed = Signal(dict)  # Emits scan result data
    work_error = Signal(str)  # Emits error message

    def __init__(self, folder_path, api_url):
        super().__init__()
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
            elif self.folder_path == 'meta':
                result = loop.run_until_complete(self.get_metadata_async())
            elif self.folder_path == 'pl':
                result = loop.run_until_complete(self.get_pl_async())
            elif self.folder_path == 'server':
                result = loop.run_until_complete(self.check_server_async())
            else:
                if Path(self.folder_path).is_dir():
                    result = loop.run_until_complete(self.scan_library_async())
                else:
                    result = loop.run_until_complete(self.reveal_remote_song_async())


            # Emit success signal
            self.work_completed.emit(result)

        except Exception as e:
            # Emit error signal
            self.work_error.emit(str(e))

        finally:
            loop.close()

    async def scan_library_async(self):
        """Async function to scan the library"""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    f"{self.api_url}/scan_library",
                    json=self.folder_path
            ) as response:
                return await response.json()


    async def get_playlists_async(self):
        """Async function to get the playlists from server"""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    f"{self.api_url}/get_playlists"
            ) as response:
                retrieved_playlists =await response.json()
                result = {'retrieved_playlists': retrieved_playlists}
                return result

    async def get_pl_async(self):
        """Async function to get a playlist from server"""
        async with aiohttp.ClientSession() as session:
            async with session.get(self.api_url) as response:
                retrieved_playlist =await response.json()
                result = {'pl': retrieved_playlist}
                return result

    async def get_metadata_async(self):
        """Async function to get metadata from server"""
        async with aiohttp.ClientSession() as session:
            async with session.get(self.api_url) as response:
                retrieved_metadata = await response.json()
                result = {'retrieved_metadata': retrieved_metadata}
                return result

    async def check_server_async(self):
        """Async function to check if server is valid"""
        async with aiohttp.ClientSession() as session:
            async with session.get(self.api_url, timeout=3) as response:
                status = response.status
                return {'status': status, 'API_URL': self.api_url}


    async def reveal_remote_song_async(self):
        """Async function to reveal playing song in remote server"""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    self.api_url,
                    json=self.folder_path) as response:
                answer = await response.json()
                result = {'answer': answer}
                return result


class SynchronizedLyrics:
    def __init__(self, audio_path=None):
        self.times = []
        self.lines = []
        self.raw_lyrics = ""
        if w.is_remote_file(audio_path):
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
            if audio_path:
                lrc_path = os.path.splitext(audio_path)[0] + ".lrc"
                if os.path.exists(lrc_path):
                    with open(lrc_path, encoding='utf-8') as f:
                        self.raw_lyrics = f.read()
                else:
                    self.raw_lyrics = self.get_embedded_lyrics(audio_path)
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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon('static/images/favicon.ico'))
    w = AudioPlayer()
    sys.exit(app.exec())