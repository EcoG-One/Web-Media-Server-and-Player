import os
import re
import sys
import sqlite3
from pathlib import Path

APP_DIR = Path.home() / "Web-Media-Server-and-Player"
APP_DIR.mkdir(exist_ok=True)
SETTINGS_FILE = APP_DIR / "settings.json"
DB_PATH = APP_DIR / 'music.db'
COVERS_DB_PATH = APP_DIR / 'covers.db'


def parse_playlist_file(playlist_path):
    """Parse playlist file and return list of media files with error handling"""
   # print(f"Parsing playlist: {playlist_path}")

    if not os.path.exists(playlist_path):
        print(f"ERROR Playlist file does not exist: {playlist_path}")
        return []

    playlist_dir = os.path.dirname(playlist_path)
    line_count = 0
    try:
        with open(playlist_path, 'r', encoding='utf-8-sig') as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        # Try with ANSI encoding if UTF-8 fails
        try:
            with open(playlist_path, 'r', encoding='ANSI') as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            try:
                # Try to guess the encoding if UTF-8 and ANSI fail
                from charset_normalizer import from_path
                result = from_path(playlist_path).best()
                with open(playlist_path, 'r',
                          encoding=result.encoding) as f:
                    lines = f.readlines()
            except Exception as e:
                print('ERROR' + str(e))
                return
            f.close()
    ext = Path(playlist_path).suffix.lower()
    if lines:
        if ext == '.cue':
            for line in lines:
                line_count += 1
                try:
                    if re.match('^FILE .(.*). (.*)$', line):
                        song_path = line[6:-7]
                        # Convert relative path to absolute path
                        if not os.path.isabs(song_path):
                            song_path = os.path.abspath(
                                os.path.join(playlist_dir, song_path))
                        if os.path.exists(song_path):
                            return
                except Exception as e:
                    print(
                        f"ERROR Error processing playlist {playlist_path} line {line_count}: {e}")
                    return
            print(playlist_path)
            return playlist_path
        else:
            for line in lines:
                line_count += 1
                try:
                    if line.startswith('ufeff01'):
                        line = line.strip('ufeff01')
                    if line.startswith('.\\'):
                        line = line.strip('.\\')
                    line = line.strip()
                    if not line.startswith(('#', '﻿#')):
                        song_path = line
                        # Convert relative path to absolute path
                        if not os.path.isabs(song_path):
                            song_path = os.path.join(playlist_dir, song_path)
                            song_path = os.path.abspath(song_path)
                            if os.path.exists(song_path):
                                return
                except Exception as e:
                    print(
                        f"ERROR Error processing playlist {playlist_path} line {line_count}: {e}")
                    return
            print(playlist_path)
            return playlist_path




try:
    print("Scanning for empty playlists...\nThe following playlists are empty:")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Populate the column for each playlist
    cursor.execute("SELECT id, path, PL_name FROM Playlists")
    rows = cursor.fetchall()
    conn.commit()
    conn.close()
    removed = 0
    bad_playlists = []
    for row in rows:
        song_id, pl_path, pl_name = row
        bad_playlist = parse_playlist_file(pl_path)
        if bad_playlist:
            bad_playlists.append((song_id, pl_path, pl_name))
            removed += 1
    if input("\nPress 'yes' to delete these playlists and their database records...") == 'yes'.lower():
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        for song_id, bad_playlist, pl_name in bad_playlists:
            try:
                os.remove(bad_playlist)
                cursor.execute(F"DELETE from Playlists WHERE id = {song_id}")
                print(f"playlist: {bad_playlist} deleted")
            except Exception as e:
                print(f"ERROR: Error removing {pl_path}: {e}")
        conn.commit()
        conn.close()
        print(bad_playlists)
        print(f"Delete complete. Removed {removed} playlists and their db records.")
    else:
        print("Delete cancelled. Bye bye...")
except Exception as e:
    print(f"ERROR: Delete failed: {e}")
