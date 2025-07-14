import os
import sqlite3
import subprocess
import threading
from pathlib import Path
from flask import Flask, render_template, request, jsonify, redirect, url_for, \
    send_file
from mutagen import File
from mutagen.id3 import ID3, APIC
import base64
from fuzzywuzzy import fuzz, process
import json
import pyperclip

app = Flask(__name__)

# Global settings
SETTINGS = {
    'server_port'   : 5000,
    'crossfade_time': 4
}


# Database initialization
def init_database():
    conn = sqlite3.connect('Music.db')
    cursor = conn.cursor()

    # Create Songs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path CHAR(255) NOT NULL,
            file_name CHAR(120) NOT NULL,
            artist CHAR(120) NOT NULL,
            song_title CHAR(120) NOT NULL,
            duration INT NOT NULL,
            album CHAR(120),
            year SMALLINT
        )
    ''')

    # Create Playlists table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path CHAR(255) NOT NULL,
            PL_name CHAR(120) NOT NULL
        )
    ''')

    conn.commit()
    conn.close()


def get_audio_metadata(file_path):
    """Extract metadata from audio file"""
    try:
        audio_file = File(file_path)
        if audio_file is None:
            return None

        metadata = {
            'artist'  : '',
            'title'   : '',
            'album'   : '',
            'year'    : '',
            'duration': 0,
            'picture' : None
        }

        # Get basic metadata
        if 'TPE1' in audio_file:  # Artist
            metadata['artist'] = str(audio_file['TPE1'])
        elif 'ARTIST' in audio_file:
            metadata['artist'] = str(audio_file['ARTIST'][0])

        if 'TIT2' in audio_file:  # Title
            metadata['title'] = str(audio_file['TIT2'])
        elif 'TITLE' in audio_file:
            metadata['title'] = str(audio_file['TITLE'][0])

        if 'TALB' in audio_file:  # Album
            metadata['album'] = str(audio_file['TALB'])
        elif 'ALBUM' in audio_file:
            metadata['album'] = str(audio_file['ALBUM'][0])

        if 'TDRC' in audio_file:  # Year
            metadata['year'] = str(audio_file['TDRC'])
        elif 'DATE' in audio_file:
            metadata['year'] = str(audio_file['DATE'][0])

        # Duration
        if audio_file.info:
            metadata['duration'] = int(audio_file.info.length)

        # Album art
        if 'APIC:' in audio_file:
            metadata['picture'] = audio_file['APIC:'].data
        elif hasattr(audio_file, 'pictures') and audio_file.pictures:
            metadata['picture'] = audio_file.pictures[0].data

        return metadata
    except Exception as e:
        print(f"Error extracting metadata from {file_path}: {e}")
        return None


def scan_for_audio_files(directory):
    """Scan directory for audio files and playlists"""
    audio_extensions = {'.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac',
                        '.wma'}
    playlist_extensions = {'.m3u', '.m3u8', '.pls'}

    audio_files = []
    playlist_files = []

    for root, dirs, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            file_ext = Path(file).suffix.lower()

            if file_ext in audio_extensions:
                audio_files.append(file_path)
            elif file_ext in playlist_extensions:
                playlist_files.append(file_path)

    return audio_files, playlist_files


def add_songs_to_database(audio_files):
    """Add audio files to database"""
    conn = sqlite3.connect('Music.db')
    cursor = conn.cursor()

    added_songs = 0

    for file_path in audio_files:
        # Check if file already exists
        cursor.execute("SELECT id FROM Songs WHERE path = ?", (file_path,))
        if cursor.fetchone():
            continue

        metadata = get_audio_metadata(file_path)
        if metadata:
            file_name = os.path.basename(file_path)
            cursor.execute('''
                INSERT INTO Songs (path, file_name, artist, song_title, duration, album, year)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                file_path,
                file_name,
                metadata['artist'],
                metadata['title'],
                metadata['duration'],
                metadata['album'],
                metadata['year']
            ))
            added_songs += 1

    conn.commit()
    conn.close()
    return added_songs


def add_playlists_to_database(playlist_files):
    """Add playlist files to database"""
    conn = sqlite3.connect('Music.db')
    cursor = conn.cursor()

    added_playlists = 0

    for file_path in playlist_files:
        # Check if playlist already exists
        cursor.execute("SELECT id FROM Playlists WHERE path = ?", (file_path,))
        if cursor.fetchone():
            continue

        pl_name = os.path.basename(file_path)
        cursor.execute('''
            INSERT INTO Playlists (path, PL_name)
            VALUES (?, ?)
        ''', (file_path, pl_name))
        added_playlists += 1

    conn.commit()
    conn.close()
    return added_playlists


def is_localhost(request):
    """Check if request is from localhost"""
    return request.remote_addr in ['127.0.0.1', '::1', 'localhost']


def parse_playlist_file(playlist_path):
    """Parse playlist file and return list of media files"""
    playlist = []
    playlist_dir = os.path.dirname(playlist_path)

    try:
        with open(playlist_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                line = line.strip('.\\')
                if line and not line.startswith(('#', '﻿#')):
                    # Convert relative path to absolute path
                    if not os.path.isabs(line):
                        line = os.path.join(playlist_dir, line)
                    playlist.append(line)
    except Exception as e:
        print(f"Error parsing playlist {playlist_path}: {e}")

    return playlist


@app.route('/')
def index():
    return render_template('index.html', is_localhost=is_localhost(request))


@app.route('/scan_library', methods=['POST'])
def scan_library():
    try:
        # Run scan_folder.py script first
        folder_path = pyperclip.paste()

        if not folder_path or folder_path == "No file selected.":
            return jsonify({'error': 'No folder selected'})

        if not os.path.isdir(folder_path):
            return jsonify({'error': 'Invalid folder path'})

        # Scan for audio files and playlists
        audio_files, playlist_files = scan_for_audio_files(folder_path)

        # Add to database
        added_songs = add_songs_to_database(audio_files)
        added_playlists = add_playlists_to_database(playlist_files)

        return jsonify({
            'success': True,
            'message': f'Successfully added {added_songs} songs and {added_playlists} playlists to the database.'
        })

    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/get_playlists')
def get_playlists():
    conn = sqlite3.connect('Music.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, PL_name FROM Playlists")
    playlists = cursor.fetchall()
    conn.close()

    return jsonify([{'id': p[0], 'name': p[1]} for p in playlists])


@app.route('/load_playlist/<int:playlist_id>')
def load_playlist(playlist_id):
    conn = sqlite3.connect('Music.db')
    cursor = conn.cursor()
    cursor.execute("SELECT path, PL_name FROM Playlists WHERE id = ?",
                   (playlist_id,))
    playlist_data = cursor.fetchone()
    conn.close()

    if not playlist_data:
        return jsonify({'error': 'Playlist not found'})

    playlist_path, playlist_name = playlist_data
    playlist_files = parse_playlist_file(playlist_path)

    return jsonify({
        'success' : True,
        'playlist': playlist_files,
        'name'    : playlist_name
    })


@app.route('/search_songs')
def search_songs():
    column = request.args.get('column')
    query = request.args.get('query')

    if not column or not query:
        return jsonify({'error': 'Missing parameters'})

    conn = sqlite3.connect('Music.db')
    cursor = conn.cursor()

    # First try exact match
    cursor.execute(
        f"SELECT id, artist, song_title, album, path, file_name FROM Songs WHERE {column} LIKE ?",
        (f'%{query}%',))
    results = cursor.fetchall()

    # If no results, try fuzzy matching
    if not results:
        cursor.execute(
            f"SELECT id, artist, song_title, album, path, file_name, {column} FROM Songs")
        all_songs = cursor.fetchall()

        fuzzy_matches = []
        for song in all_songs:
            ratio = fuzz.ratio(query.lower(), song[6].lower())
            if ratio > 60:  # Threshold for fuzzy matching
                fuzzy_matches.append((song[:6], ratio))

        # Sort by similarity
        fuzzy_matches.sort(key=lambda x: x[1], reverse=True)
        results = [match[0] for match in fuzzy_matches[:10]]  # Top 10 matches

    conn.close()

    return jsonify([{
        'id'      : r[0],
        'artist'  : r[1],
        'title'   : r[2],
        'album'   : r[3],
        'path'    : r[4],
        'filename': r[5]
    } for r in results])


@app.route('/get_song_metadata/<path:file_path>')
def get_song_metadata(file_path):
    metadata = get_audio_metadata(file_path)
    if metadata:
        # Convert picture to base64 if exists
        if metadata['picture']:
            metadata['picture'] = base64.b64encode(metadata['picture']).decode(
                'utf-8')
        return jsonify(metadata)
    return jsonify({'error': 'Could not read metadata'})


@app.route('/serve_audio/<path:file_path>')
def serve_audio(file_path):
    return send_file(file_path)


@app.route('/settings')
def settings():
    return render_template('settings.html', settings=SETTINGS)


@app.route('/save_settings', methods=['POST'])
def save_settings():
    global SETTINGS
    SETTINGS['server_port'] = int(request.form.get('server_port', 5000))
    SETTINGS['crossfade_time'] = int(request.form.get('crossfade_time', 4))
    return redirect(url_for('index'))


if __name__ == '__main__':
    init_database()
    app.run(host='0.0.0.0', port=SETTINGS['server_port'], debug=True)
