import tkinter as tk
from tkinter import filedialog

# Create a root window (it won't be shown)
root = tk.Tk()
root.withdraw()  # Hide the root window

# Open file dialog
dir_path = filedialog.askdirectory(title="Select Music Library Folder")

# Print the selected file path
if dir_path:
    print(dir_path)
else:
    print("No file selected.")
