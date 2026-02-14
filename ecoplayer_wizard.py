from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from text import text_1, text_2, text_3, text_4, text_5, text_6, text_7


class WelcomeWizard(QDialog):
    """
    Simple multi-step welcome wizard.
    """

    def __init__(self, audio_player, load_json, save_json, get_settings, settings_file):
        super().__init__(audio_player)
        self.setWindowTitle("Welcome")
        self.setModal(True)
        self.audio = audio_player
        self.load_json = load_json
        self.save_json = save_json
        self.get_settings = get_settings
        self.settings_file = settings_file
        self.step = 1
        self.resize(500, 220)

        self.layout = QVBoxLayout(self)

        self.label = QLabel("", self)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            "font-size: 12px; border-width: 2px; border-color: #7A7EA8; border-style: inset;"
        )
        if self.audio.dark_style == "dark":
            self.label.setStyleSheet(
                "font-size: 12px; color: white; background: #19232D; border-width: 2px; border-color: #7A7EA8; border-style: inset;"
            )
        self.layout.addWidget(self.label)

        self.button_box = QHBoxLayout()
        self.layout.addLayout(self.button_box)

        self.dont_show_checkbox = QCheckBox("Don't show this again", self)

        self.update_step()

    def _clear_buttons(self):
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

    def update_step(self):
        self._clear_buttons()
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
        try:
            QTimer.singleShot(0, lambda: self.audio.scan_library())
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to start library scan: {e}")

    def _connect_remote(self):
        try:
            QTimer.singleShot(0, lambda: self.audio.enter_server())
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open Connect to Remote: {e}")

    def _scan_remote(self):
        try:
            QTimer.singleShot(0, lambda: self.audio.scan_remote_library())
        except Exception as e:
            QMessageBox.warning(
                self, "Error", f"Failed to start remote library scan: {e}"
            )

    def finish_wizard(self):
        try:
            settings = self.load_json(self.settings_file, default={})
            if not isinstance(settings, dict):
                settings = {}
            settings["show_welcome"] = not self.dont_show_checkbox.isChecked()
            defaults = self.get_settings()
            for key, value in defaults.items():
                if key not in settings:
                    settings[key] = value
            self.save_json(self.settings_file, settings)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not save settings: {e}")
        self.accept()
