import os
import sqlite3
import subprocess
import threading
from pathlib import Path
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file
from mutagen import File
from mutagen.id3 import ID3, APIC
import base64
from fuzzywuzzy import fuzz, process
import json

app = Flask(__name__)

# Global settings
SETTINGS = {
    'server_port': 5000,
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
            'artist': '',
            'title': '',
            'album': '',
            'year': '',
            'duration': 0,
            'picture': None
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
    audio_extensions = {'.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac', '.wma'}
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
        # Run openfile.py script
        result = subprocess.run(['python', 'openfile.py'], capture_output=True, text=True)
        folder_path = result.stdout.strip()
        
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
    cursor.execute("SELECT path, PL_name FROM Playlists WHERE id = ?", (playlist_id,))
    playlist_data = cursor.fetchone()
    conn.close()
    
    if not playlist_data:
        return jsonify({'error': 'Playlist not found'})
    
    playlist_path, playlist_name = playlist_data
    playlist_files = parse_playlist_file(playlist_path)
    
    return jsonify({
        'success': True,
        'playlist': playlist_files,
        'name': playlist_name
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
    cursor.execute(f"SELECT id, artist, song_title, album, path, file_name FROM Songs WHERE {column} LIKE ?", (f'%{query}%',))
    results = cursor.fetchall()
    
    # If no results, try fuzzy matching
    if not results:
        cursor.execute(f"SELECT id, artist, song_title, album, path, file_name, {column} FROM Songs")
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
        'id': r[0],
        'artist': r[1],
        'title': r[2],
        'album': r[3],
        'path': r[4],
        'filename': r[5]
    } for r in results])

@app.route('/get_song_metadata/<path:file_path>')
def get_song_metadata(file_path):
    metadata = get_audio_metadata(file_path)
    if metadata:
        # Convert picture to base64 if exists
        if metadata['picture']:
            metadata['picture'] = base64.b64encode(metadata['picture']).decode('utf-8')
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

# HTML Templates
@app.route('/templates/index.html')
def serve_index_template():
    return '''
<!DOCTYPE html>
<html>
<head>
    <title>Media Player</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .menu { margin-bottom: 20px; }
        .menu button { margin: 5px; padding: 10px 20px; font-size: 16px; }
        .content { margin-top: 20px; }
        .hidden { display: none; }
        .audio-player { margin: 20px 0; }
        .metadata { margin: 20px 0; }
        .album-art { max-width: 200px; max-height: 200px; }
        .search-results { margin: 10px 0; }
        .search-result { padding: 10px; border: 1px solid #ccc; margin: 5px 0; cursor: pointer; }
        .search-result:hover { background-color: #f0f0f0; }
        .playlist-item { padding: 10px; border: 1px solid #ccc; margin: 5px 0; cursor: pointer; }
        .playlist-item:hover { background-color: #f0f0f0; }
    </style>
</head>
<body>
    <h1>Media Player</h1>
    
    <div class="menu">
        {% if is_localhost %}
        <button onclick="scanLibrary()">Scan Library</button>
        {% endif %}
        <button onclick="showPlayFromPlaylist()">Play from Playlist</button>
        <button onclick="showPlayFile()">Play a File</button>
        <button onclick="showSettings()">Settings</button>
    </div>
    
    <div id="content" class="content">
        <div id="status"></div>
        
        <div id="playlist-section" class="hidden">
            <h3>Select Playlist</h3>
            <div id="playlist-list"></div>
        </div>
        
        <div id="search-section" class="hidden">
            <h3>Search Songs</h3>
            <select id="search-column">
                <option value="artist">Artist</option>
                <option value="song_title">Song Title</option>
                <option value="album">Album</option>
            </select>
            <input type="text" id="search-input" placeholder="Enter search term...">
            <button onclick="searchSongs()">Search</button>
            <div id="search-results"></div>
        </div>
        
        <div id="player-section" class="hidden">
            <div class="audio-player">
                <audio id="audio1" controls></audio>
                <audio id="audio2" controls></audio>
            </div>
            <div id="metadata" class="metadata"></div>
        </div>
    </div>
    
    <script>
        let currentAudio = 1;
        let playlist = [];
        let currentIndex = 0;
        let crossfadeTime = 4;
        
        function scanLibrary() {
            document.getElementById('status').innerHTML = 'Scanning library...';
            fetch('/scan_library', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        document.getElementById('status').innerHTML = data.message;
                    } else {
                        document.getElementById('status').innerHTML = 'Error: ' + data.error;
                    }
                });
        }
        
        function showPlayFromPlaylist() {
            hideAllSections();
            document.getElementById('playlist-section').classList.remove('hidden');
            loadPlaylists();
        }
        
        function showPlayFile() {
            hideAllSections();
            document.getElementById('search-section').classList.remove('hidden');
        }
        
        function showSettings() {
            window.location.href = '/settings';
        }
        
        function hideAllSections() {
            document.getElementById('playlist-section').classList.add('hidden');
            document.getElementById('search-section').classList.add('hidden');
            document.getElementById('player-section').classList.add('hidden');
        }
        
        function loadPlaylists() {
            fetch('/get_playlists')
                .then(response => response.json())
                .then(data => {
                    const listDiv = document.getElementById('playlist-list');
                    listDiv.innerHTML = '';
                    data.forEach(playlist => {
                        const div = document.createElement('div');
                        div.className = 'playlist-item';
                        div.textContent = playlist.name;
                        div.onclick = () => loadPlaylist(playlist.id);
                        listDiv.appendChild(div);
                    });
                });
        }
        
        function loadPlaylist(playlistId) {
            fetch(`/load_playlist/${playlistId}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        playlist = data.playlist;
                        currentIndex = 0;
                        showPlayerSection();
                        playCurrentSong();
                    } else {
                        document.getElementById('status').innerHTML = 'Error: ' + data.error;
                    }
                });
        }
        
        function searchSongs() {
            const column = document.getElementById('search-column').value;
            const query = document.getElementById('search-input').value;
            
            if (!query) return;
            
            fetch(`/search_songs?column=${column}&query=${encodeURIComponent(query)}`)
                .then(response => response.json())
                .then(data => {
                    const resultsDiv = document.getElementById('search-results');
                    resultsDiv.innerHTML = '';
                    
                    if (data.error) {
                        resultsDiv.innerHTML = 'Error: ' + data.error;
                        return;
                    }
                    
                    data.forEach(song => {
                        const div = document.createElement('div');
                        div.className = 'search-result';
                        div.innerHTML = `<strong>${song.artist}</strong> - ${song.title} (${song.album})`;
                        div.onclick = () => playSingleSong(song.path);
                        resultsDiv.appendChild(div);
                    });
                });
        }
        
        function playSingleSong(filePath) {
            playlist = [filePath];
            currentIndex = 0;
            showPlayerSection();
            playCurrentSong();
        }
        
        function showPlayerSection() {
            hideAllSections();
            document.getElementById('player-section').classList.remove('hidden');
        }
        
        function playCurrentSong() {
            if (currentIndex >= playlist.length) return;
            
            const currentSong = playlist[currentIndex];
            const audio = document.getElementById(`audio${currentAudio}`);
            
            audio.src = `/serve_audio/${encodeURIComponent(currentSong)}`;
            audio.play();
            
            // Load metadata
            fetch(`/get_song_metadata/${encodeURIComponent(currentSong)}`)
                .then(response => response.json())
                .then(data => {
                    if (!data.error) {
                        displayMetadata(data);
                    }
                });
            
            // Setup next song
            setupNextSong();
        }
        
        function setupNextSong() {
            const currentAudioElement = document.getElementById(`audio${currentAudio}`);
            
            currentAudioElement.addEventListener('timeupdate', function() {
                const timeLeft = this.duration - this.currentTime;
                if (timeLeft <= crossfadeTime && currentIndex + 1 < playlist.length) {
                    preloadNextSong();
                }
            });
            
            currentAudioElement.addEventListener('ended', function() {
                playNextSong();
            });
        }
        
        function preloadNextSong() {
            if (currentIndex + 1 >= playlist.length) return;
            
            const nextAudio = currentAudio === 1 ? 2 : 1;
            const nextSong = playlist[currentIndex + 1];
            
            document.getElementById(`audio${nextAudio}`).src = `/serve_audio/${encodeURIComponent(nextSong)}`;
        }
        
        function playNextSong() {
            currentIndex++;
            if (currentIndex >= playlist.length) return;
            
            currentAudio = currentAudio === 1 ? 2 : 1;
            const audio = document.getElementById(`audio${currentAudio}`);
            
            audio.play();
            
            // Load metadata for new song
            const currentSong = playlist[currentIndex];
            fetch(`/get_song_metadata/${encodeURIComponent(currentSong)}`)
                .then(response => response.json())
                .then(data => {
                    if (!data.error) {
                        displayMetadata(data);
                    }
                });
            
            setupNextSong();
        }
        
        function displayMetadata(metadata) {
            const metadataDiv = document.getElementById('metadata');
            let html = '<h3>Now Playing</h3>';
            
            if (metadata.picture) {
                html += `<img src="data:image/jpeg;base64,${metadata.picture}" class="album-art"><br>`;
            }
            
            html += `<strong>Artist:</strong> ${metadata.artist}<br>`;
            html += `<strong>Title:</strong> ${metadata.title}<br>`;
            html += `<strong>Album:</strong> ${metadata.album}<br>`;
            html += `<strong>Year:</strong> ${metadata.year}<br>`;
            html += `<strong>Duration:</strong> ${Math.floor(metadata.duration / 60)}:${(metadata.duration % 60).toString().padStart(2, '0')}`;
            
            metadataDiv.innerHTML = html;
        }
    </script>
</body>
</html>
    '''

if __name__ == '__main__':
    init_database()
    app.run(host='0.0.0.0', port=SETTINGS['server_port'], debug=True)
