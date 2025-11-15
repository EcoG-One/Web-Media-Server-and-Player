import os
import ffmpeg
from ffcuesplitter.cuesplitter import FFCueSplitter
# from ffcuesplitter.user_service import FileSystemOperations
import sys
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QThread, Signal, QMutex, Slot
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QWizard, QWizardPage, QLabel, QCheckBox, QPushButton,
    QToolBar, QTextEdit, QFileDialog, QLineEdit, QDialog, QFormLayout, QDialogButtonBox, QMessageBox)
from formats import ffmpeg_formats
from pathlib import Path
import json

# basic ffmpeg_formats = ["mp4", "flac", "mov", "avi", "mkv", "webm"]
APP_DIR = Path.home() / "Codec Converter"
APP_DIR.mkdir(exist_ok=True)
SETTINGS_FILE = APP_DIR / "settings.json"


def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        QMessageBox.warning(window, "Error!", str(e))
    return default


def save_json(path: Path, obj):
    try:
        path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    except Exception as e:
        QMessageBox.warning(window, "Error!", str(e))

def get_settings():
    default = {"show_welcome": True
               }
    json_settings = load_json(SETTINGS_FILE, default=default)
    # Ensure keys exist
    for k, v in default.items():
        if k not in json_settings:
            json_settings[k] = v
    return json_settings


def cue_spliter(cue_file: str, output_dir: str = '.', dry_run: bool = False):
    splitter = FFCueSplitter(cue_file, output_dir, dry=dry_run)
    if dry_run:
        splitter.dry_run_mode()
    else:
        overwrite = splitter.check_for_overwriting()
        if not overwrite:
            splitter.work_on_temporary_directory()



def select_directory_dialog():
    global selected_directory
    selected_directory = None
    file_dialog = QFileDialog()
    file_dialog.setWindowTitle("Select Directory")
    file_dialog.setFileMode(QFileDialog.FileMode.Directory)
    file_dialog.setViewMode(QFileDialog.ViewMode.List)
    if file_dialog.exec():
        selected_directory = file_dialog.selectedFiles()[0]
        try:
            window.editor.append(f"Selected Directory: {selected_directory}")
            if window.c_from:
                window.editor.append("\nNow hit [ Go ] to start the convertion!")
        except NameError:
            pass
    else:
        try:
            window.editor.append("You cancelled the directory selection.")
        except NameError:
            pass
    return selected_directory


class TwoInputCustomDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set Codecs")

        # 1. Create the main layout
        main_layout = QVBoxLayout(self)

        # 2. Create a form layout for labels and input fields
        form_layout = QFormLayout()

        self.input1_field = QLineEdit(self)
        if window.c_from:
            self.input1_field.setText(window.c_from)
        self.input2_field = QLineEdit(self)
        if window.c_to:
            self.input2_field.setText(window.c_to)
        self.delete_files = QCheckBox(self)
        self.delete_files.setChecked(False)

        form_layout.addRow("From:", self.input1_field)
        form_layout.addRow("To:", self.input2_field)
        form_layout.addRow('Delete original files after conversion', self.delete_files)

        main_layout.addLayout(form_layout)

        # 3. Add standard OK/Cancel buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(
            self.accept)  # Connect OK button to accept the dialog
        self.button_box.rejected.connect(
            self.reject)  # Connect Cancel button to reject the dialog

        main_layout.addWidget(self.button_box)

    def get_inputs(self):
        """Method to retrieve the text values."""
        return self.input1_field.text(), self.input2_field.text(), self.delete_files.isChecked()



class AppWindow(QMainWindow):
    work_error = Signal(str)
    worker_messages = Signal(str)
    def __init__(self, settings):
        super().__init__()
        self.worker = None
        self.setWindowTitle("EcoG's Codec Converter")
        self.setGeometry(500, 100, 500, 400)
        self.settings = settings
        self.selected_directory = None
        self.del_files = False
        self.c_from = None
        self.c_to = None

        # Central Widget
        c_widget = QWidget()

        # Menubar
        menubar = self.menuBar()

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)


        # Toolbar Actions
        wiz_action = QAction(QIcon("icons/wizard.png"), "Start Wizard", self)
        wiz_action.setShortcut('Ctrl+W')
        wiz_action.triggered.connect(self.start_wizard)
        set_action = QAction(QIcon("icons/codecs.png"), "Set", self)
        set_action.setShortcut('Ctrl+S')
        set_action.triggered.connect(self.show_two_input_dialog)
        open_action = QAction(QIcon("icons/open.png"), "Choose", self)
        open_action.setShortcut("Ctrl+C")
        open_action.triggered.connect(select_directory_dialog)
        go_action = QAction(QIcon("icons/go.png"), "Go", self)
        go_action.setShortcut("Ctrl+G")
        go_action.triggered.connect(self.ready)
        quit_action = QAction(QIcon("icons/power.png"),"Quit", self)
        quit_action.setShortcut("Ctrl+Q")

        '''copy_action = QAction(QIcon("icons/copy.png"), "Copy", self)
        copy_action.setShortcut('Ctrl+C')
        cut_action = QAction(QIcon("icons/cut.png"), "Cut", self)
        cut_action.setShortcut("Ctrl+X")
        paste_action = QAction(QIcon("icons/paste.png"), "Paste", self)
        paste_action.setShortcut("Ctrl+V")
'''
        # Add action to toolbar
        toolbar.addAction(wiz_action)
        toolbar.addAction(set_action)
        toolbar.addAction(open_action)
        toolbar.addAction(go_action)

        # Create menu items
        wizard_menu = menubar.addMenu('Wizard')
        wizard_menu.addAction(wiz_action)

        file_menu = menubar.addMenu('Manual')

        file_menu.addAction(set_action)
        file_menu.addAction(open_action)
        file_menu.addAction(go_action)
        file_menu.addAction(quit_action)

        ''' # Edit menu
        edit_menu = menubar.addMenu('Edit')

        edit_menu.addAction(copy_action)
        edit_menu.addAction(cut_action)
        edit_menu.addAction(paste_action)
'''

        # Layouts
        main_layout = QVBoxLayout(c_widget)

        self.editor = QTextEdit()
        main_layout.addWidget(self.editor)
        self.editor.append("Welcome to <b>EcoG's Codec Converter!</b><br>"
                           "Please <b>set codecs</b> and <b>choose directory</b> to proceed.")

        # Set central widget
        self.setCentralWidget(c_widget)

        # Connections
        quit_action.triggered.connect(self.close)
        self.worker_messages.connect(self.editor_update)

        # Wizard
        if self.settings.get('show_welcome', True):
            self.start_wizard()


    def save_json(self, path: Path, obj):
        try:
            path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(window, "Error!", str(e))

    def get_settings(self):
        default = {"show_welcome": True
                   }
        json_settings = load_json(SETTINGS_FILE, default=default)
        # Ensure keys exist
        for k, v in default.items():
            if k not in json_settings:
                json_settings[k] = v
        return json_settings

    def editor_update(self, msg):
        self.editor.append(msg)

    def file_converter(self, from_codec: str, to_codec: str, convert_dir: str, del_files=False):
        # convert_dir = "/path/to/folder/tobeconverted"
        f_codec = "." + from_codec
        t_codec = "." + to_codec
        for root, dirs, files in os.walk(convert_dir):
            for name in files:
                if name.endswith(f_codec):
                    # filepath+name
                    file = root + "/" + name
                    # file = file.replace("\\", "/")
                    file = os.path.normpath(file)
                    output = file.replace(f_codec, t_codec)
                    try:
                        (ffmpeg.input(file).output(output).run())
                        self.worker_messages.emit(f"File {output} created.")
                    except FileNotFoundError as e:
                        self.work_error.emit("File not found. " + str(e))
                    except Exception as e:
                        self.work_error.emit("Error: "+ str(e))
                    finally:
                        if del_files and os.path.exists(output):
                            os.remove(file)
                            self.worker_messages.emit(f"File {file} deleted.")
                else:
                    continue
                   # self.worker_messages.emit(
                       # f"{name} is NOT a {from_codec} file.")


    def show_two_input_dialog(self):
        from_to_input = TwoInputCustomDialog(self)

        # Show the dialog modally and wait for user interaction
        if from_to_input.exec():
            # exec() returns QDialog.Accepted (1) if OK was clicked
            self.valid_elements_lower = {item.lower() for item in
                                         ffmpeg_formats}
            self.c_from, self.c_to, self.del_files = from_to_input.get_inputs()
            if self.c_from.lower() in self.valid_elements_lower and self.c_to.lower() in self.valid_elements_lower:
                if self.del_files:
                    no = ''
                else:
                    no = 'NOT'
                self.editor.append(
                    f"You chose to convert from: <b>{self.c_from}</b>, "
                    f"to: <b>{self.c_to}</b> and {no} delete the {self.c_from} files.")
                if selected_directory:
                    self.editor.append(f"You selected the directory: {selected_directory}"
                        f"\nNow hit [ Go ] to start the convertion!")
                else:
                    self.editor.append("Please select <b>directory</b> to proceed.")

            else:
                if self.c_from.lower() not in ffmpeg_formats:
                    QMessageBox.critical(self, 'Oops',
                                         f'{self.c_from} is not a valid format')
                else:
                    QMessageBox.critical(self, 'Oops',
                                         f'{self.c_to} is not a valid format')
                self.show_two_input_dialog()
        else:
            # exec() returns QDialog.Rejected (0) if Cancel was clicked
            self.editor.append("User cancelled the dialog.")



    def start_wizard(self):
        wizard = ConvertWizard(self)
      #  selected_directory = None
        if sys.platform == 'darwin':
            wizard.setWizardStyle(QWizard.ModernStyle)
        if wizard.exec():
            wizard.finish_wizard()
            self.c_from = wizard.field('from')
            self.c_to = wizard.field('to')
            self.del_files = wizard.field("delete_files")
            self.ready()
          #  del_files = wizard.field("delete_files")
           # self.go(wizard.field('from'), wizard.field('to'), del_files)


    def ready(self):
        self.go(self.c_from, self.c_to, self.del_files)


    def go(self, c_from, c_to, del_files):
        if not c_from:
            QMessageBox.warning(self, 'Ooops!', 'Please set conversion codecs.')
            return
        try:
            self.selected_directory = selected_directory
        except NameError:
            QMessageBox.warning(self, 'Ooops!', 'Please select a Directory.')
            return
        if  self.selected_directory is None:
            QMessageBox.warning(self, 'Ooops!', 'Please select a Directory.')
            return
        if del_files:
            no = ''
        else:
            no = 'NOT'
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setText(f"You chose to "
                       f"convert all {c_from} files to {c_to},\n"
                       f"on directory: {self.selected_directory}\n"
                        f"and {no} delete the {c_from} files.")
        msg_box.setInformativeText(
            "<h2>Do you want to proceed with conversion?</h2>")
        msg_box.setStandardButtons(
            QMessageBox.Apply | QMessageBox.StandardButton.Cancel)
        msg_box.setDefaultButton(QMessageBox.Apply)
        ret = msg_box.exec()
        if ret == QMessageBox.Apply:
            self.editor.clear()
            self.editor.append("Convertion Begins...")
            self.worker = LocalMetaWorker(c_from, c_to,
                                self.selected_directory, del_files, self.file_converter)
            self.worker.work_completed.connect(self.on_work_completed)
            self.worker.work_error.connect(self.on_work_error)
            self.worker.finished.connect(self.cleanup_worker)
            # mirror behavior of other workers (lock so handler will unlock)
            self.worker.mutex.lock()
            self.worker.start()
          #  self.file_converter(c_from, c_to,
                             #   self.selected_directory, del_files)

    @Slot(str)
    def on_work_completed(self, success_message):
        if self.worker:
            self.worker.mutex.unlock()
        self.editor.append(success_message)
        QMessageBox.information(self,"Success!", success_message)


    def on_work_error(self, error_message):
        """Handle metadata error"""
        self.worker.mutex.unlock()
        QMessageBox.critical(self, "Error", error_message)


    def cleanup_worker(self):
        """Clean up after scan completion"""
        # Clean up worker reference
        if self.worker:
            self.worker.deleteLater()
            self.worker = None



class LocalMetaWorker(QThread):
    """
    Runs local audio metadata extraction off the GUI thread.
    Expects an extractor callable that takes a single file_path arg and
    returns the metadata dict (same structure as get_audio_metadata).
    """
    work_completed = Signal(str)   # Emits {'retrieved_metadata': metadata}
    work_error = Signal(str)

    def __init__(self, c_from, c_to, selected_directory, del_files, callable):
        super().__init__()
        self.c_from = c_from
        self.c_to = c_to
        self.selected_directory = selected_directory
        self.del_files = del_files
        self.callable = callable
        self.mutex = QMutex()

    def run(self):
        try:
            # Call the provided extractor (this will perform heavy work)
            self.callable(self.c_from, self.c_to,
                                               self.selected_directory, self.del_files)
            # Emit in same structure as your remote meta worker
            self.work_completed.emit("Convertion Completed!")
        except Exception as e:
            self.work_error.emit(str(e))


class CodecsWizardPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Set Codecs")
        self.setSubTitle("Please fill both fields with valid formats.")

        # --- UI Setup ---
        self.from_label = QLabel("Convert from:")
        self.from_line_edit = QLineEdit()
        self.from_line_edit.setFixedWidth(120)
        self.from_line_edit.setMaxLength(16)
        self.registerField("from*",
                           self.from_line_edit)  # Register 'from' field

        self.to_label = QLabel("To:")
        self.to_line_edit = QLineEdit()
        self.to_line_edit.setFixedWidth(120)
        self.to_line_edit.setMaxLength(16)
        self.registerField("to*", self.to_line_edit)  # Register 'to' field

        self.delete_files = QCheckBox("Delete original files after conversion")
        self.delete_files.setChecked(False)
        self.registerField("delete_files", self.delete_files)

        self.status_label = QLabel("Status: Awaiting input")

        # --- Layout ---
        layout = QVBoxLayout()
        layout.addWidget(self.from_label)
        layout.addWidget(self.from_line_edit)
        layout.addWidget(self.to_label)
        layout.addWidget(self.to_line_edit)
        layout.addWidget(self.delete_files)
        layout.addWidget(self.status_label)
        self.setLayout(layout)

        # --- Continuous Validation Connections ---
        # Connect text changes to show live status feedback
        self.from_line_edit.textChanged.connect(self.update_status_labels)
        self.to_line_edit.textChanged.connect(self.update_status_labels)

    def is_valid_format(self, input_text):
        """Helper to check if a single format is valid (case-insensitive)."""
        input_text_lower = input_text.strip().lower()
        # Pre-calculate the lowercase set once
        valid_elements_lower = {item.lower() for item in ffmpeg_formats}
        return input_text_lower in valid_elements_lower

    def update_status_labels(self):
        """Updates the status label for live feedback."""
        from_text = self.from_line_edit.text().strip()
        to_text = self.to_line_edit.text().strip()

        is_from_valid = self.is_valid_format(from_text)
        is_to_valid = self.is_valid_format(to_text)

        if is_from_valid and is_to_valid:
            self.status_label.setText("Status: **Both formats are valid** ✅")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
        elif not from_text or not to_text:
            self.status_label.setText("Status: Please fill both fields.")
            self.status_label.setStyleSheet("color: black;")
        else:
            self.status_label.setText(
                "Status: **One or both formats are invalid** ❌")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")

        # Call completeChanged() to notify the QWizard if the validation status has changed
        self.completeChanged.emit()

    def isComplete(self):
        """
        QWizardPage's core validation method:
        Determines if the 'Next' button should be enabled.
        """
        from_text = self.from_line_edit.text().strip()
        to_text = self.to_line_edit.text().strip()

        return self.is_valid_format(from_text) and self.is_valid_format(
            to_text)

    def validatePage(self):
        """
        QWizardPage's final validation method:
        Called when the user clicks 'Next'.
        """
        # Since isComplete() handles all the checks, we can just return its result.
        return self.isComplete()



class ConvertWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.addPage(self.intro_page())
        self.addPage(self.codecs_page())  # Calls the function below
        self.addPage(self.dir_page())
        # self.addPage(
            # self.conclusion_page())  # Added conclusion page for completeness

      #  self.addPage(self.conclusion_page())
        self.setWindowTitle("EcoG's File Convertion Wizard")



    def intro_page(self):
        page = QWizardPage()
        page.setTitle("Welcome to EcoG's Codec Converter!")
        label = QLabel(
            "This wizard will help you to convert your files from one codec to another.")
        label.setWordWrap(True)
        layout = QVBoxLayout()
        layout.addWidget(label)
        page.setLayout(layout)
        return page

    def codecs_page(self):
        return CodecsWizardPage(self)


    def dir_page(self):

        def select_directory():
            select_directory_dialog()
            label.setText(f"You selected: {selected_directory}\nNow hit [ Finish ] "
                          f"to start the convertion, or [ Browse ] to select another directory.")


        page = QWizardPage()
        page.setTitle("Select Directory")
        label = QLabel(
            "Please select the directory containing the files to be converted.")
        label.setWordWrap(True)
        button = QPushButton("Browse...")
        button.clicked.connect(select_directory)
        button.setFixedSize(100, 40)
       # status_label = QLabel("Now hit [ Finish ] to start the convertion.")
        layout = QVBoxLayout()
        layout.addWidget(label)
        layout.addWidget(button)
       # layout.addWidget(status_label)
        self.dont_show_checkbox = QCheckBox("Don't show Wizard next time.", self)
        self.dont_show_checkbox.setChecked(False)
       # layout.addWidget(status_label)
        # Add the "Don't show again" checkbox
        layout.addWidget(self.dont_show_checkbox)
        page.registerField("dont_show_wizard", self.dont_show_checkbox)
        page.setLayout(layout)
        return page

    def finish_wizard(self):
        # Persist "don't show again" option if checked
        try:
            settings = load_json(SETTINGS_FILE, default={})
            if not isinstance(settings, dict):
                settings = {}
            settings[
                'show_welcome'] = not self.dont_show_checkbox.isChecked()
            # Ensure other known settings remain (merge defaults)
            defaults = get_settings()
            for k, v in defaults.items():
                if k not in settings:
                    settings[k] = v
            save_json(SETTINGS_FILE, settings)
        except Exception as e:
            QMessageBox.warning(self, "Error",
                                f"Could not save settings: {e}")
        self.accept()

# --- End of Welcome Wizard Implementation ---



if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    settings = get_settings()
    window = AppWindow(settings)
    window.show()
    sys.exit(app.exec())


'''if __name__ == "__main__":
    # Example usage:
    cue_file_path = "example.cue"
    output_directory = "output"
    dry_run_mode = True

    cue_spliter(cue_file_path, output_directory, dry_run_mode)

    convert_directory = "to_be_converted"
    ape_to_flac_converter(convert_directory)'''