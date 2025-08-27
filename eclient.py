import sys
import requests
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QTableWidget, QTableWidgetItem, QMessageBox

API_URL = "http://localhost:5000"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EcoServer Desktop UI")
        self.setGeometry(100, 100, 900, 600)

        self.btn_scan = QPushButton("Scan Library", self)
        self.btn_scan.setGeometry(30, 30, 120, 40)
        self.btn_scan.clicked.connect(self.scan_library)

        self.btn_playlists = QPushButton("View Playlists", self)
        self.btn_playlists.setGeometry(170, 30, 120, 40)
        self.btn_playlists.clicked.connect(self.get_playlists)

        self.table = QTableWidget(self)
        self.table.setGeometry(30, 100, 800, 400)

    def scan_library(self):
        try:
            r = requests.post(f"{API_URL}/scan_library")
            data = r.json()
            if 'error' in data:
                QMessageBox.warning(self, "Scan Error", data['error'])
            else:
                QMessageBox.information(self, "Success", data['message'])
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def get_playlists(self):
        try:
            r = requests.get(f"{API_URL}/get_playlists")
            playlists = r.json()
            self.table.clear()
            self.table.setColumnCount(2)
            self.table.setHorizontalHeaderLabels(['ID', 'Name'])
            self.table.setRowCount(len(playlists))
            for i, pl in enumerate(playlists):
                self.table.setItem(i, 0, QTableWidgetItem(str(pl['id'])))
                self.table.setItem(i, 1, QTableWidgetItem(pl['name']))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())