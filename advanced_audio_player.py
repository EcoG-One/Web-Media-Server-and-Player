import sys
import os
from pickle import GLOBAL

from PySide6.QtCore import Qt, QDate, QEvent, QUrl, QTimer, QSize, QRect, Signal, QThread
from PySide6.QtGui import QPixmap, QTextCursor, QImage, QAction, QIcon, QKeySequence, QIcon
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSlider, QListWidget, QFileDialog, QTextEdit, QListWidgetItem, QMessageBox,
    QComboBox, QSpinBox, QFormLayout, QGroupBox, QLineEdit, QInputDialog, QMenuBar,
    QMenu, QStatusBar,QProgressBar, QFrame)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaMetaData
import mutagen
from mutagen import File
from mutagen.flac import FLAC
from pathlib import Path
from random import shuffle
import re
import asyncio
import aiohttp
import requests
import base64
import webbrowser
from dotenv import load_dotenv
from sympy.printing.dot import slotClasses

load_dotenv()
SHUTDOWN_SECRET = os.getenv("SHUTDOWN_SECRET")

API_URL = "http://localhost:5000"
APP_DIR = Path.home() / "Web-Media-Server-and-Player"
APP_DIR.mkdir(exist_ok=True)

class AudioPlayer(QWidget):
    request_search = Signal(str, str)
    def __init__(self):
        super().__init__()
        self.scan_worker = None
        self.playlists_worker = None
        self.setWindowTitle("Ultimate Media Player. Current Server: Local")
        self.resize(1200, 800)
        self.playlist = []
        self.current_index = -1
        self.show_remaining = False
        self.lyrics = None
        self.lyrics_timer = QTimer(self)
        self.lyrics_timer.setInterval(200)
        self.lyrics_timer.timeout.connect(self.update_lyrics_display)
        self.remote_base = None
        self.data = None


        # Mixing/transition config
        self.mix_method = "Fade"  # Default
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

        self.save_action = QAction("&Save Playlist", self)
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
        self.exit_action.triggered.connect(self.close)
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
        self.exit_action.triggered.connect(self.close)
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
        self.skip_silence = False  # Optionally configurable

        top = QHBoxLayout()
        self.combo = QComboBox();
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
        self.album_art = QLabel();
        self.album_art.setFixedSize(256, 256)
        self.album_art.setScaledContents(True)
        self.album_art.setPixmap(
            QPixmap("static/images/default_album_art.png") if os.path.exists(
                "static/images/default_album_art.png") else QPixmap())
        self.title_label = QLabel("Title --")
        self.title_label.setFixedWidth(256)
        self.artist_label = QLabel("Artist --")
        self.album_label = QLabel("Album --")
        self.year_label = QLabel("Year --")
        self.codec_label = QLabel("Codec --")

        self.text = QTextEdit(readOnly=True)
        self.text_label = QLabel("Metadata")

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
        self.lyrics_display = LyricsDisplay(); self.lyrics_display.setReadOnly(True)

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

        self.silence_check = QPushButton("Skip Silence")
        self.silence_check.setCheckable(True)
        self.silence_check.setChecked(self.skip_silence)
        self.silence_check.toggled.connect(self.set_skip_silence)

        # StatusBar
        self.status_bar = QStatusBar()
        self.status_bar.showMessage("Welcome! Drag-and-drop Playlists or/and Songs to Playlist pane to start the music.")

        mix_form = QFormLayout()
        mix_form.addRow("Mix Method:", self.mix_method_combo)
        mix_form.addRow("Transition:", self.transition_spin)
        mix_form.addRow(self.silence_check)
        mix_group = QGroupBox("Mixing Options")
        mix_group.setLayout(mix_form)

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
        metadata_layout.addWidget(self.text_label)
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
        left_layout.addWidget(mix_group)

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
        self.request_search.connect(self.search_tracks)
        self.player.positionChanged.connect(self.update_slider)
        self.player.durationChanged.connect(self.update_duration)
        self.player.mediaStatusChanged.connect(self.media_status_changed)
        self.player.playbackStateChanged.connect(self.update_play_button)
        self.slider.sliderPressed.connect(lambda: self.player.pause())
        self.slider.sliderReleased.connect(lambda: self.player.play())
        self.player.metaDataChanged.connect(self.on_metadata_changed)
        self.player.errorOccurred.connect(self.handle_error)

        # For mixing (transition to next track)
        self.player.positionChanged.connect(self.check_for_mix_transition)

        # Init
        self.update_play_button()
        self.show()

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

    def enter_server(self):
        server, ok_pressed = QInputDialog.getText(self, "Input",
                                                "Enter Remote Server name or IP:",
                                                QLineEdit.Normal, "");
        if ok_pressed and server != '':
            self.status_bar.showMessage(f'Please Wait, testing connection with server: {server}')
            self.status_bar.repaint()
            self.progress = QProgressBar()
            self.progress.setRange(0, 0)  # Indeterminate progress
            self.status_bar.addWidget(self.progress)
            self.status_bar.repaint()
            try:
                r = requests.get(f'http://{server}:5000', timeout=5)
                if r.status_code == 200:
                    global API_URL
                    API_URL = f'http://{server}:5000'
                    self.remote_base = API_URL
                    self.setWindowTitle(f"Ultimate Media Player. Current Server: {server}")
                    self.status_bar.showMessage(f'Remote Server is now: {API_URL}', 8000)
                    QMessageBox.information(self, 'Success!', f'Remote Server is now: {API_URL}')
                else:
                    QMessageBox.warning(self,'Error', r.text)
            except Exception as e:
                self.status_bar.clearMessage()
                QMessageBox.warning(self,'Error', f'Server {server} not responding.\nMake sure the Server is Up and Connected')



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
        self.scan_worker = ScanWorker(folder_path, API_URL)
        self.scan_worker.scan_completed.connect(self.on_scan_completed)
        self.scan_worker.scan_error.connect(self.on_scan_error)
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
        if self.scan_worker:
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
            self.status_bar.showMessage(resp.text)
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
            QMessageBox.information(self, "Server Search error: Make sure the Server is Up and Connected")



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
        self.update_metadata(next_idx)
        if self.is_local_file(next_path):
            self.set_album_art(next_path)
        self.load_lyrics(next_path)
        self.next_player.play()
     #   self.update_metadata()
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
                if self.is_local_file(next_path):
                    self.update_metadata(self.current_index)
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
          #  self.title_label.setText(os.path.basename(path))
          #  self.artist_label.setText("-- Artist --")
          #  self.album_label.setText("-- Album --")
          #  self.year_label.setText("-- Date --")
          #  self.codec_label.setText("-- Audio --")
          #  if self.is_remote_file(path):
            self.update_metadata(idx)
            if self.is_local_file(path):
                self.set_album_art(path)
            self.load_lyrics(path)
            if auto_play:
                self.player.play()
            self.lyrics_timer.start()
            if self.is_local_file(path):
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
                             "Audio files (*.mp3 *.flac *.ogg *.wav *.m4a)", "All files (*)"])
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
        self.update_metadata(idx)
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
            if self.data and 'picture' in self.data and self.data[
                'picture']:
                try:
                    img_bytes = base64.b64decode(self.data['picture'])
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

    def update_metadata(self, index):
        self.text.clear()
        path = self.playlist[index]
        if self.is_remote_file(path):
            try:
                filename = path.split('5000/')[1]
                url = f"{self.remote_base}/get_song_metadata/{filename}"
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    self.data = r.json()
                    title = self.data.get('title', os.path.basename(path))
                    artist = self.data.get('artist', "--")
                    album = self.data.get('album', "--")
                    year = self.data.get('year', "--")
                    codec = self.data.get('codec', "--").replace('audio/', '')
                    self.set_album_art(path)
                    for key in self.data:
                        self.text.append(f"{key}: {self.data[key]}")
                    self.move_to_top()
                else:
                    title = os.path.basename(path)
                    artist = album = year = codec = "--"
                #    self.set_album_art(path)
            except Exception as e:
                self.status_bar.showMessage("Remote metadata fetch error:" + str(e))
                title = os.path.basename(path)
                artist = album = year = codec = "--"
                self.set_album_art(path)
            self.title_label.setText('Title: ' + title)
            self.artist_label.setText('Artist: ' + artist)
            self.album_label.setText('Album: '+ album)
            self.year_label.setText('Year: ' + year)
            self.codec_label.setText(codec)
        else:
            # local fallback
            self.text.append(mutagen.File(path).pprint())
            self.move_to_top()
            meta = self.player.metaData()
            title = meta.stringValue(QMediaMetaData.Title) or os.path.basename(path)
            album_artist = meta.stringValue(QMediaMetaData.AlbumArtist) or meta.stringValue(QMediaMetaData.Author) or "--"
            try:
                audio_file = File(path)
                if 'TPE1' in audio_file:  # Artist
                    artist = str(audio_file['TPE1'])
                elif 'ARTIST' in audio_file:
                    artist = str(audio_file['ARTIST'][0])
                elif '©ART' in audio_file:
                    artist = str(audio_file['©ART'][0])
                else:
                    artist = "--"
            except Exception as e:
                artist = "--"
                self.status_bar.showMessage(
                    f"Error reading artist metadata from {path}: {str(e)}")
            album = meta.stringValue(QMediaMetaData.AlbumTitle) or "--"
            year = self.extract_year(meta) or "--"
            self.title_label.setText('Title: ' + title)
            self.artist_label.setText('Artist: ' + artist)
            self.album_label.setText('Album: '+ album)
            self.year_label.setText('Year: ' + year)
            codec = self.extract_audio_info()
            if codec:
                self.codec_label.setText(codec.replace('audio/', ''))
            self.set_album_art(path)

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
                if self.data and 'codec' in self.data and self.data[
                    'codec']:
                    codec = self.data.get('codec')
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
        self.scan_worker = ScanWorker(folder_path, "http://localhost:5000")
        self.scan_worker.scan_completed.connect(self.on_scan_completed)
        self.scan_worker.scan_error.connect(self.on_scan_error)
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

        self.playlists_worker = ScanWorker(None, API_URL)
        self.playlists_worker.scan_completed.connect(self.receive_playlists)
        self.playlists_worker.finished.connect(self.cleanup_scan)

        # Start the async operation
        self.playlists_worker.start()



    def receive_playlists(self, data):
        """Handle successful scan completion"""
        if 'error' in data:
            QMessageBox.warning(self, "Scan Error", data['error'])
        self.status_bar.repaint()

        try:
         #   r = requests.get(f"{API_URL}/get_playlists")
            r = received_playlists
            self.playlists = r
            for item in self.playlists:
                self.playlist_widget.addItem(item['name'])
            self.playlist_label.setText('Playlists from Server: ')
            self.status_bar.clearMessage()
        except Exception as e:
            self.status_bar.clearMessage()
            QMessageBox.critical(self, "Error",
                                 "Server Search error: Make sure the Server is Up and Connected")


    def play_selected_playlist(self):
        files = []
        idx = self.playlist_widget.currentRow()
        item = self.playlist_widget.currentItem()
        if item is not None:
            item_ext = item.text().split('.')[-1]
            if item_ext == 'm3u' or item_ext == 'm3u8':
                self.status_bar.showMessage(
                    'Loading Playlist from Server. Please Wait, it might take some time...')
                progress = QProgressBar()
                progress.setValue(50)
                self.status_bar.addWidget(progress)
                self.status_bar.repaint()
                try:
                    playlist_id = self.playlists[idx]['id']
                    playlist_name = self.playlists[idx]['name']
                    r = requests.get(f"{API_URL}/load_playlist/{playlist_id}")
                    data = r.json()
                    if data:
                        for track in data["playlist"]:
                            files.append(track)
                        self.clear_playlist()
                        self.add_files(files)
                        self.playlist_label.setText(f"Playlist: {playlist_name}")

                except Exception as e:
                    QMessageBox.critical(self, "Error", str(e))
                self.status_bar.showMessage(
                    f'Playlist {playlist_name} loaded. Enjoy!')

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



class ScanWorker(QThread):
    """Worker thread for handling the asynchronous scan operation"""

    # Define signals for communicating with the main thread
    scan_completed = Signal(dict)  # Emits scan result data
    scan_error = Signal(str)  # Emits error message

    def __init__(self, folder_path, api_url):
        super().__init__()
        self.folder_path = folder_path
        self.api_url = api_url

    def run(self):
        """Run the async scan in a separate thread"""
        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Run the async scan
            if self.folder_path == None:
                result = loop.run_until_complete(self.get_playlists_async())
            else:
                result = loop.run_until_complete(self.scan_library_async())

            # Emit success signal
            self.scan_completed.emit(result)

        except Exception as e:
            # Emit error signal
            self.scan_error.emit(str(e))

        finally:
            loop.close()

    async def scan_library_async(self):
        """Async function to scan the library"""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    f"{self.api_url}/scan_library",
                    json={"folder_path": self.folder_path}
            ) as response:
                return await response.json()


    async def get_playlists_async(self):
        """Async function to get the playlists from server"""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    f"{self.api_url}/get_playlists"
            ) as response:
                global received_playlists
                received_playlists = await response.json()
                return received_playlists

class SynchronizedLyrics:
    def __init__(self, audio_path=None):
        self.times = []
        self.lines = []
        self.raw_lyrics = ""
        if w.is_remote_file(audio_path):
            try:
                if w.data and 'lyrics' in w.data and w.data[
                    'lyrics']:
             #       data = r.json()
                    self.raw_lyrics = w.data['lyrics']
                else:
                    self.raw_lyrics = "--"
            except Exception as e:
                self.status_bar.showMessage("Remote lyrics fetch error:" + str(e))
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
        self.setStyleSheet("font-size: 18px;")
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
                html += f"<div style='color: #3A89FF; font-weight: bold; background: #E0F0FF'>{line}</div>"
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