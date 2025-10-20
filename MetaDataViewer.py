import sys
from PySide6.QtCore import QUrl, Qt
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QTextEdit, QPushButton, QFileDialog
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaMetaData, QMediaFormat
from PySide6.QtMultimediaWidgets import QVideoWidget
import mutagen
from mutagen.flac import FLAC


class MetaDataViewer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QMediaPlayer Metadata Viewer")
        self.resize(800, 500)

        layout = QVBoxLayout(self)

        self.video_widget = QVideoWidget()
        self.text_edit = QTextEdit(readOnly=True)

        self.btn_open = QPushButton("Open Media File")
        self.btn_open.clicked.connect(self.open_file)

        layout.addWidget(self.video_widget, stretch=2)
        layout.addWidget(self.text_edit, stretch=1)
        layout.addWidget(self.btn_open)

        # Media player
        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)

        # Connect signals
        self.player.metaDataChanged.connect(self.show_metadata)
        self.player.errorOccurred.connect(lambda e, s="": self.text_edit.append(f"Error: {s}"))

    def open_file(self):
        file, _ = QFileDialog.getOpenFileName(self, "Open Media")
        if file:
            print(mutagen.File(file).pprint())
            if file.lower().endswith(".flac"):
                try:
                    audio = FLAC(file)
                    for key in audio:
                        print(key, audio[key])

                except Exception as e:
                    print(str(e))
           # self.player.setSource(QUrl.fromLocalFile(file))
           # self.player.play()

    def show_metadata(self):
        self.text_edit.clear()
        metadata = self.player.metaData()
        if not metadata:
            self.text_edit.setText("No metadata available.")
            return

        for key in metadata.keys():
            raw_value = metadata.value(key)

            # --- normalize value for display ---
            if isinstance(raw_value, QMediaFormat.FileFormat):
                value = raw_value.name  # e.g. "MP3", "MP4"
            elif isinstance(raw_value, QMediaFormat.VideoCodec):
                value = raw_value.name
            elif isinstance(raw_value, QMediaFormat.AudioCodec):
                value = raw_value.name
            else:
                try:
                    value = str(raw_value)
                except Exception:
                    value = repr(raw_value)

            self.text_edit.append(
                f"{QMediaMetaData.metaDataKeyToString(key)}: {value}"
            )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MetaDataViewer()
    w.show()
    sys.exit(app.exec())
