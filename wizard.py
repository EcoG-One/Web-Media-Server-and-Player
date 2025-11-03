
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import ( QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QMessageBox,
    QCheckBox, QDialog)
from pathlib import Path
import json
from ecoplayer import AudioPlayer
from text import text_1, text_2, text_3, text_4, text_5

APP_DIR = Path.home() / "Web-Media-Server-and-Player"
APP_DIR.mkdir(exist_ok=True)
SETTINGS_FILE = APP_DIR / "settings.json"

# --- Welcome Wizard ---
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
    def __init__(self, audio_player: 'AudioPlayer'):
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
            "font-size: 12px; background: lightyellow; border-width: 2px; border-color: #7A7EA8; border-style: inset;")
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
            self._add_button("Scan", self._scan_async)
            self._add_button("Next", self.next_step, default=True)

        elif self.step == 3:
            self.label.setText(text_3)
            self._add_button("Cancel", self.reject)
            self._add_button("Next", self.next_step, default=True)

        elif self.step == 4:
            self.label.setText(text_4)
            self._add_button("Cancel", self.reject)
            self._add_button("Connect to Remote", self._connect_remote)
            self._add_button("Next", self.next_step, default=True)

        elif self.step == 5:
            self.label.setText("Placeholder for Text 5")
            # Add the "Don't show again" checkbox
            self.layout.addWidget(self.dont_show_checkbox)
            self._add_button("End", self.finish_wizard, default=True)

    def next_step(self):
        if self.step < 5:
            self.step += 1
            self.update_step()
        else:
            self.finish_wizard()

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

    def load_json(self, path: Path, default):
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            QMessageBox.warning(self, "Error!", str(e))
        return default

    def save_json(self, path: Path, obj):
        try:
            path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "Error!", str(e))

    def get_settings(self):
        default = {"server"              : "localhost",
                   "mix_method"          : "Auto",
                   "transition_duration" : 4,
                   "gap_enabled"         : True,
                   "silence_threshold_db": -46,
                   "silence_min_duration": 0.1,
                   "scan_for_lyrics"     : False,
                   "show_welcome"        : True,
                   "style"               : "default"
                   }
        json_settings = self.load_json(SETTINGS_FILE, default=default)
        # Ensure keys exist
        for k, v in default.items():
            if k not in json_settings:
                json_settings[k] = v
        return json_settings


    def finish_wizard(self):
        # Persist "don't show again" option if checked
        try:
            settings = self.load_json(SETTINGS_FILE, default={})
            if not isinstance(settings, dict):
                settings = {}
            settings['show_welcome'] = not self.dont_show_checkbox.isChecked()
            # Ensure other known settings remain (merge defaults)
            defaults = self.get_settings()
            for k, v in defaults.items():
                if k not in settings:
                    settings[k] = v
            self.save_json(SETTINGS_FILE, settings)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not save settings: {e}")
        self.accept()




# --- End of Welcome Wizard Implementation ---
