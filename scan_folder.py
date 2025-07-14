import tkinter as tk
from tkinter import filedialog
import pyperclip

# Create a root window (it won't be shown)
root = tk.Tk()
root.withdraw()  # Hide the root window

# Open file dialog
dir_path = filedialog.askdirectory(title="Select Music Library Folder")
pyperclip.copy(dir_path)
