import sys
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLineEdit, QLabel
from PySide6.QtCore import Qt


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QLineEdit Set Validator")

        # 1. Define the predefined set of valid strings
        self.valid_elements = {"Apple", "Banana", "Cherry", "Date", "Elderberry"}

        # 2. Set up the UI
        self.layout = QVBoxLayout(self)

        self.input_line = QLineEdit()
        self.input_line.setPlaceholderText("Type a fruit name (e.g., Apple)")
        self.layout.addWidget(self.input_line)

        self.status_label = QLabel("Status: Awaiting input")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.status_label)

        # 3. Connect the signal to the validation function
        # 'editingFinished' is often better for final validation
        self.input_line.editingFinished.connect(self.validate_input)

        # Alternatively, use 'textChanged' for continuous, immediate feedback:
        # self.input_line.textChanged.connect(self.validate_input_continuous)

    def validate_input(self):
        """Validates the input text against the predefined set."""
        # Get the text from the QLineEdit
        input_text = self.input_line.text().strip()

        if input_text in self.valid_elements:
            # Match found
            self.status_label.setText(
                f"Status: **'{input_text}' is a valid element** ✅"
            )
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            # You can add logic here, like processing the input
        elif not input_text:
            # Input is empty
            self.status_label.setText("Status: Input is empty")
            self.status_label.setStyleSheet("color: black;")
        else:
            # No match found
            self.status_label.setText(
                f"Status: **'{input_text}' is NOT in the set** ❌"
            )
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            # You could optionally clear the field: self.input_line.clear()

    # If you choose to use the 'textChanged' signal:
    def validate_input_continuous(self, text):
        """Continuous validation as text changes."""
        input_text = text.strip()
        if input_text in self.valid_elements:
            self.status_label.setText(f"Status: **'{input_text}' is valid** ✅")
            self.status_label.setStyleSheet("color: blue;")
        else:
            self.status_label.setText(f"Status: Typing... Current text: '{input_text}'")
            self.status_label.setStyleSheet("color: black;")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
