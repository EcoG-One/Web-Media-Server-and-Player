import tkinter as tk
from tkinter import filedialog
import pyperclip

# Create a root window (it won't be shown)
root = tk.Tk()
root.withdraw()  # Hide the root window

# Open file dialog
file_path = filedialog.askopenfilename(title="Select a file",
                                       filetypes=[("Media files", "*.*"), ("All files", "*.*")])

# Print the selected file path
if file_path:
    print(file_path)
else:
    print("No file selected.")
