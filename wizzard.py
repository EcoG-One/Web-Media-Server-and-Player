import sys
from codec_converter import ape_to_flac_converter

from llvmlite.binding import initialize
from PySide6.QtWidgets import QApplication, QWizard, QLabel, QVBoxLayout, QWizardPage, QLineEdit, QCheckBox, QPushButton, QFileDialog


def intro_page():
    page = QWizardPage()
    page.setTitle("Introduction")
    label = QLabel("This wizard will help you to convert your files from one codec to another.")
    label.setWordWrap(True)
    layout = QVBoxLayout()
    layout.addWidget(label)
    page.setLayout(layout)
    return page


def codecs_page():
    page = QWizardPage()
    page.setTitle("Set Codecs")
    page.setSubTitle("Please fill both fields.")

    from_label = QLabel("Covert from:")
    from_line_edit = QLineEdit()
    from_line_edit.setFixedWidth(120)
    from_line_edit.setMaxLength(16)
    page.registerField("from*", from_line_edit)

    to_label = QLabel("To:")
    to_line_edit = QLineEdit()
    to_line_edit.setFixedWidth(120)
    to_line_edit.setMaxLength(16)
    page.registerField("to*", to_line_edit)

    delete_files = QCheckBox("Delete original files after conversion")
    delete_files.setChecked(False)

    layout = QVBoxLayout()
    layout.addWidget(from_label)
    layout.addWidget(from_line_edit)
    layout.addWidget(to_label)
    layout.addWidget(to_line_edit)
    layout.addWidget(delete_files)
    page.setLayout(layout)

    return page


def dir_page():
    page = QWizardPage()
    page.setTitle("Select Directory")
    label = QLabel("Please select the directory containing the files to be converted.")
    label.setWordWrap(True)
    button = QPushButton("Browse...")
    button.clicked.connect(select_directory)
    button.setFixedSize(100, 40)
    layout = QVBoxLayout()
    layout.addWidget(label)
    layout.addWidget(button)
    page.setLayout(layout)
    return page


def conclusion_page():
    initialize()
    page = QWizardPage()
    page.setTitle("Conclusion")
    label = QLabel()
    label.setWordWrap(True)
    layout = QVBoxLayout()
    layout.addWidget(label)
    page.setLayout(layout)
    label.setText(f"You have completed the wizard. You chose to convert from: {wizard.field('from')}, to: {wizard.field('to')}, on directory: {selected_directory}.")
    return page



if __name__ == "__main__":
    app = QApplication([])
    wizard = QWizard()
    if sys.platform == 'darwin':
        wizard.setWizardStyle(QWizard.ModernStyle)
    wizard.addPage(intro_page())
    wizard.addPage(codecs_page())
    wizard.addPage(dir_page())
    wizard.addPage(conclusion_page())
    wizard.setWindowTitle("EcoG's File Convertion Wizard")
    wizard.show()
    sys.exit(app.exec())