import re

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget


class SynchronizedLyrics:
    def __init__(self, lyrics_text="", on_error=None):
        self.times = []
        self.lines = []
        self.raw_lyrics = lyrics_text or "--"
        self.on_error = on_error
        self.parse_lyrics(self.raw_lyrics)

    @classmethod
    def from_metadata(cls, meta_data, on_error=None):
        try:
            lyrics = meta_data.get("lyrics", "") if meta_data else ""
            return cls(lyrics_text=lyrics, on_error=on_error)
        except Exception as e:
            if on_error:
                on_error(f"Remote lyrics fetch error: {e}")
            return cls(lyrics_text="--", on_error=on_error)

    def parse_lyrics(self, lyrics_text):
        time_tag = re.compile(r"\[(\d+):(\d+)(?:\.(\d+))?\]")
        self.times = []
        self.lines = []
        for line in lyrics_text.splitlines():
            matches = list(time_tag.finditer(line))
            if matches:
                lyric = time_tag.sub("", line).strip()
                for match in matches:
                    minute, sec, ms = match.groups()
                    total_ms = int(minute) * 60 * 1000 + int(sec) * 1000 + int(ms or 0)
                    self.times.append(total_ms)
                    self.lines.append(lyric)
            elif line.strip():
                self.times.append(0)
                self.lines.append(line.strip())

    def get_current_line(self, pos_ms):
        for i, lyric_time in enumerate(self.times):
            if pos_ms < lyric_time:
                return max(0, i - 1)
        return len(self.lines) - 1 if self.lines else -1

    def is_synchronized(self):
        return any(lyric_time > 0 for lyric_time in self.times)


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
        if self.is_synchronized:
            if idx != self.current_line_idx:
                self.current_line_idx = idx
                self.update_display(idx)
        elif self.current_line_idx != -1:
            self.current_line_idx = -1
            self.update_display(-1)


class TextEdit(QWidget):
    def __init__(self, instructions_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Instructions")
        self.resize(1180, 780)
        self.instructions_edit = QTextEdit(readOnly=True)
        layout = QVBoxLayout()
        layout.addWidget(self.instructions_edit)
        self.setLayout(layout)
        self.instructions_edit.setText(instructions_text)
