from enum import Enum
import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QWidget, QWidgetAction


_default_server = "localhost"


def set_default_server(server: str):
    global _default_server
    _default_server = server or "localhost"


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
        return item_type


class ListItem:
    def __init__(self):
        super().__init__()
        self.is_remote = False
        self.item_type = ItemType
        self.display_text = "Unknown"
        self.route = ""
        self.path = ""
        self.server = _default_server

    def absolute_path(self):
        if self.is_remote:
            abs_url = QUrl()
            abs_url.setScheme("http")
            abs_url.setHost(self.server)
            abs_url.setPort(5000)
            file_path = rf"/{self.route}/{self.path}"
            abs_url.setPath(file_path)
            return abs_url
        return QUrl.fromLocalFile(os.path.abspath(self.path))


class CheckBoxAction(QWidgetAction):
    def __init__(self, parent, text):
        super().__init__(parent)
        layout = QHBoxLayout()
        self.widget = QWidget()
        label = QLabel(text)
        label.setAlignment(Qt.AlignLeft)
        layout.addWidget(QCheckBox())
        layout.addWidget(label)
        self.widget.setLayout(layout)
        self.setDefaultWidget(self.widget)
