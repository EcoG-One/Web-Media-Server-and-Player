import asyncio
from pathlib import Path
import os
from functools import partial
from PyQt5.QtCore import QTimer  # to schedule GUI calls on main thread

'''asyncio with run_in_executor (requires integration into Qt event loop; use qasync)
What it does: schedules the blocking scan on a threadpool via asyncio.get_event_loop().run_in_executor, 
allowing other asyncio tasks to run concurrently. 
To use this from Qt, you need a bridge (qasync) so the Qt event loop runs with asyncio.'''

async def scan_for_audio_files_async(self, directory):
    loop = asyncio.get_running_loop()

    def _sync_scan(directory, audio_extensions, playlist_extensions):
        audio_files = []
        playlist_files = []
        scan_errors = 0
        for root, dirs, files in os.walk(directory):
            # No GUI calls here; only collect data
            for file in files:
                try:
                    file_path = os.path.join(root, file)
                    file_ext = Path(file).suffix.lower()
                    if file_ext in audio_extensions:
                        audio_files.append(file_path)
                    elif file_ext in playlist_extensions:
                        playlist_files.append(file_path)
                except Exception:
                    scan_errors += 1
        return audio_files, playlist_files, scan_errors

    # Pre-checks on the main thread (synchronous)
    if not os.path.exists(directory):
        QMessageBox.critical(self, "Error", f"Directory does not exist: {directory}")
        return [], []
    if not os.path.isdir(directory):
        QMessageBox.critical(self, "Error", f"Path is not a directory: {directory}")
        return [], []

    # Optionally show initial message on main thread
    self.status_bar.showMessage(f"Scanning directory: {directory}")

    # Run the blocking scan in the default thread pool
    audio_files, playlist_files, scan_errors = await loop.run_in_executor(
        None, partial(_sync_scan, directory, audio_extensions, playlist_extensions)
    )

    # Update GUI on main thread (we're back on the Qt event loop if using qasync)
    self.status_bar.showMessage(f"Scan complete. Found {len(audio_files)} audio files and {len(playlist_files)} playlists")
    if scan_errors > 0:
        QMessageBox.warning(self, "Scan Error", f"Encountered {scan_errors} errors during scanning")

    return audio_files, playlist_files

'''The core scan is still synchronous (os.walk) but runs in a thread pool; 
that’s appropriate because os.walk is CPU/IO-bound.
To update the GUI safely you must run GUI calls on the main Qt thread. 
If you run the coroutine via qasync (qasync.run or by launching an asyncio task inside a qasync-running loop), 
GUI calls will be safe. If you cannot use qasync, prefer the QThread option.
You lose per-folder progress updates unless you implement a generator/iterable 
and periodically schedule GUI callbacks (using loop.call_soon_threadsafe or Qt signals).'''