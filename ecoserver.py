import os
import sys
import sqlite3
import subprocess
import logging
import traceback
from pathlib import Path
from flask import Flask, render_template, request, jsonify, redirect, url_for, \
    send_file, abort
from mutagen import File
import base64
from threading import Thread
from pystray import Icon, MenuItem, Menu
from PIL import Image, ImageDraw
from fuzzywuzzy import fuzz, process
import webbrowser
import signal
import shutil
from plyer import notification
from dotenv import load_dotenv

app = Flask(__name__)

load_dotenv()
secret_key = os.getenv("SECRET_KEY")
SHUTDOWN_SECRET = os.getenv("SHUTDOWN_SECRET")


def run_flask():
    try:
        init_database()
        logger.info(f"Starting Flask server on port 5000")
        app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        logger.error(traceback.format_exc())
        raise


def show_notification(title, message):
    notification.notify(
        title=title,
        message=message,
        app_name='FlaskApp',
        timeout=5  # seconds
    )


# Configure logging
def setup_logging():
    """Setup comprehensive logging configuration"""
    # Create logs directory if it doesn't exist
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Setup root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # File handler for all logs
    file_handler = logging.FileHandler(log_dir / 'ecoserver.log')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    
    # File handler for errors only
    error_handler = logging.FileHandler(log_dir / 'errors.log')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(simple_formatter)
    
    # Add handlers to root logger
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)
    
    # Setup Flask app logger
    app.logger.setLevel(logging.INFO)
    
    # Log startup
    logging.info("=== EcoServer Starting ===")
    logging.info(f"Python version: {os.sys.version}")
    logging.info(f"Working directory: {os.getcwd()}")

# Initialize logging
setup_logging()
logger = logging.getLogger(__name__)

# Global settings
SETTINGS = {
    'crossfade_time': 4,
    'fade_in'       : 0
}


# Database initialization
def init_database():
    """Initialize the database with proper error handling"""
    try:
        logger.info("Initializing database...")
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
        logger.info("Database initialized successfully")
        
    except sqlite3.Error as e:
        logger.error(f"Database initialization failed: {e}")
        logger.error(traceback.format_exc())
        raise
    except Exception as e:
        logger.error(f"Unexpected error during database initialization: {e}")
        logger.error(traceback.format_exc())
        raise


def get_audio_metadata(file_path):
    """Extract metadata from audio file with comprehensive error handling"""
    try:
        logger.debug(f"Extracting metadata from: {file_path}")
        
        if not os.path.exists(file_path):
            logger.warning(f"File does not exist: {file_path}")
            return None
            
        audio_file = File(file_path)
        if audio_file is None:
            logger.warning(f"Could not read audio file: {file_path}")
            return None

        metadata = {
            'artist'  : '',
            'title'   : '',
            'album'   : '',
            'year'    : '',
            'duration': 0,
            'lyrics'  : '',
            'codec'   : '',
            'picture' : None
        }

        # Get basic metadata
        try:
            if 'TPE1' in audio_file:  # Artist
                metadata['artist'] = str(audio_file['TPE1'])
            elif 'ARTIST' in audio_file:
                metadata['artist'] = str(audio_file['ARTIST'][0])
            elif '©ART' in audio_file:
                metadata['artist'] = str(audio_file['©ART'][0])
        except Exception as e:
            logger.warning(f"Error reading artist metadata from {file_path}: {e}")

        try:
            if 'TIT2' in audio_file:  # Title
                metadata['title'] = str(audio_file['TIT2'])
            elif 'TITLE' in audio_file:
                metadata['title'] = str(audio_file['TITLE'][0])
            elif '©nam' in audio_file:
                metadata['title'] = str(audio_file['©nam'][0])
        except Exception as e:
            logger.warning(f"Error reading title metadata from {file_path}: {e}")

        try:
            if 'TALB' in audio_file:  # Album
                metadata['album'] = str(audio_file['TALB'])
            elif 'ALBUM' in audio_file:
                metadata['album'] = str(audio_file['ALBUM'][0])
            elif '©alb' in audio_file:
                metadata['album'] = str(audio_file['©alb'][0])
        except Exception as e:
            logger.warning(f"Error reading album metadata from {file_path}: {e}")

        try:
            if 'TDRC' in audio_file:  # Year
                metadata['year'] = str(audio_file['TDRC'])
            elif 'DATE' in audio_file:
                metadata['year'] = str(audio_file['DATE'][0])
            elif '©day' in audio_file:
                metadata['year'] = str(audio_file['©day'][0])
        except Exception as e:
            logger.warning(f"Error reading year metadata from {file_path}: {e}")

        # Duration
        try:
            if audio_file.info:
                metadata['duration'] = int(audio_file.info.length)
        except Exception as e:
            logger.warning(f"Error reading duration from {file_path}: {e}")
            
        # Lyrics
        try:
            lrc_path = os.path.splitext(file_path)[0] + ".lrc"
            if os.path.exists(lrc_path):
                with open(lrc_path, encoding='utf-8-sig') as f:
                    metadata['lyrics'] = f.read()
            else:
                # FLAC/Vorbis
                if audio_file.__class__.__name__ == 'FLAC':
                    for key in audio_file:
                        if key.lower() in ('lyrics', 'unsyncedlyrics',
                                           'lyric'):
                            metadata['lyrics'] = audio_file[key][0]
                    # MP3 (ID3)
                elif hasattr(audio_file, 'tags') and audio_file.tags:
                    # USLT (unsynchronized lyrics) is the standard for ID3
                    for k in audio_file.tags.keys():
                        if k.startswith('USLT') or k.startswith('SYLT'):
                            metadata['lyrics'] = str(audio_file.tags[k])
                        if k.lower() in ('lyrics', 'unsyncedlyrics', 'lyric'):
                            metadata['lyrics'] = str(audio_file.tags[k])
                    # MP4/AAC
                elif hasattr(audio_file, 'tags') and hasattr(audio_file.tags, 'get'):
                    if audio_file.tags.get('\xa9lyr'):
                        metadata['lyrics'] = audio_file.tags['\xa9lyr'][0]
                else:
                    metadata['lyrics'] = "--"
        except Exception as e:
            logger.warning(f"Error reading lyrics from {file_path}: {e}")

        # Codec
        try:
            codec = audio_file.mime[0] if hasattr(audio_file,
                                             'mime') and audio_file.mime else audio_file.__class__.__name__

            # Sample rate and bitrate
            sample_rate = getattr(audio_file.info, 'sample_rate', None)
            bits = getattr(audio_file.info, 'bits_per_sample', None)
            bitrate = getattr(audio_file.info, 'bitrate', None)
            if codec == 'audio/mp3':
                metadata['codec'] = codec + ' ' + str(sample_rate / 1000) + 'kHz ' + str(
                    round(bitrate / 1000)) + 'kbps'
            else:
                metadata['codec'] = codec + ' ' + str(sample_rate / 1000) + 'kHz/' + str(
                    round(bits)) + 'bits  ' + str(
                    round(bitrate / 1000)) + 'kbps'
        except Exception as e:
            logger.warning(f"Error reading codec from {file_path}: {e}")

        # Album art
        try:
            if 'APIC:' in audio_file:
                metadata['picture'] = audio_file['APIC:'].data
            elif hasattr(audio_file, 'pictures') and audio_file.pictures:
                metadata['picture'] = audio_file.pictures[0].data
            elif 'covr' in audio_file:
                metadata['picture'] = audio_file['covr'][0]
        except Exception as e:
            logger.warning(f"Error reading album art from {file_path}: {e}")

        logger.debug(f"Successfully extracted metadata from: {file_path}")
        return metadata
        
    except Exception as e:
        logger.error(f"Error extracting metadata from {file_path}: {e}")
        logger.error(traceback.format_exc())
        return None

def get_album_art(file_path):
    logger.debug(f"Extracting metadata from: {file_path}")

    if not os.path.exists(file_path):
        logger.warning(f"File does not exist: {file_path}")
        return None
    album_art = None
    audio_file = File(file_path)
    if audio_file is None:
        logger.warning(f"Could not read audio file: {file_path}")
        return None
    try:
        if 'APIC:' in audio_file:
            album_art = audio_file['APIC:'].data
        elif hasattr(audio_file, 'pictures') and audio_file.pictures:
            album_art = audio_file.pictures[0].data
        elif 'covr' in audio_file:
            album_art = audio_file['covr'][0]
    except Exception as e:
        logger.warning(f"Error reading album art from {file_path}: {e}")
    logger.debug(f"Successfully extracted album art from: {file_path}")
    try:
        album_art = base64.b64encode(album_art).decode('utf-8')
    except Exception as e:
        logger.warning(f"Error encoding album art: {e}")
        album_art = None
    return album_art


def scan_for_audio_files(directory):
    """Scan directory for audio files and playlists with error handling"""
    try:
        logger.info(f"Scanning directory: {directory}")
        
        if not os.path.exists(directory):
            logger.error(f"Directory does not exist: {directory}")
            return [], []
            
        if not os.path.isdir(directory):
            logger.error(f"Path is not a directory: {directory}")
            return [], []
            
        audio_extensions = {'.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac', '.wma'}
        playlist_extensions = {'.m3u', '.m3u8', '.pls'}

        audio_files = []
        playlist_files = []
        scan_errors = 0

        for root, dirs, files in os.walk(directory):
            logger.debug(f"Scanning folder: {root}")
            
            for file in files:
                try:
                    file_path = os.path.join(root, file)
                    file_ext = Path(file).suffix.lower()

                    if file_ext in audio_extensions:
                        audio_files.append(file_path)
                    elif file_ext in playlist_extensions:
                        playlist_files.append(file_path)
                        
                except Exception as e:
                    logger.warning(f"Error processing file {file}: {e}")
                    scan_errors += 1

        logger.info(f"Scan complete. Found {len(audio_files)} audio files and {len(playlist_files)} playlists")
        if scan_errors > 0:
            logger.warning(f"Encountered {scan_errors} errors during scanning")
            
        return audio_files, playlist_files
        
    except Exception as e:
        logger.error(f"Error scanning directory {directory}: {e}")
        logger.error(traceback.format_exc())
        return [], []


def add_songs_to_database(audio_files):
    """Add audio files to database with error handling"""
    try:
        logger.info(f"Adding {len(audio_files)} audio files to database")
        
        conn = sqlite3.connect('Music.db')
        cursor = conn.cursor()
        added_songs = 0
        errors = 0

        for file_path in audio_files:
            try:
                # Check if file already exists
                cursor.execute("SELECT id FROM Songs WHERE path = ?", (file_path,))
                if cursor.fetchone():
                    logger.debug(f"File already in database: {file_path}")
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
                    logger.debug(f"Added song: {metadata['artist']} - {metadata['title']}")
                else:
                    logger.warning(f"Could not extract metadata from: {file_path}")
                    errors += 1
                    
            except sqlite3.Error as e:
                logger.error(f"Database error adding song {file_path}: {e}")
                errors += 1
            except Exception as e:
                logger.error(f"Unexpected error adding song {file_path}: {e}")
                errors += 1

        conn.commit()
        conn.close()
        
        logger.info(f"Successfully added {added_songs} songs to database")
        if errors > 0:
            logger.warning(f"Encountered {errors} errors while adding songs")
            
        return added_songs
        
    except Exception as e:
        logger.error(f"Error adding songs to database: {e}")
        logger.error(traceback.format_exc())
        return 0


def add_playlists_to_database(playlist_files):
    """Add playlist files to database with error handling"""
    try:
        logger.info(f"Adding {len(playlist_files)} playlists to database")
        
        conn = sqlite3.connect('Music.db')
        cursor = conn.cursor()
        added_playlists = 0
        errors = 0

        for file_path in playlist_files:
            try:
                # Check if playlist already exists
                cursor.execute("SELECT id FROM Playlists WHERE path = ?", (file_path,))
                if cursor.fetchone():
                    logger.debug(f"Playlist already in database: {file_path}")
                    continue

                pl_name = os.path.basename(file_path)
                cursor.execute('''
                    INSERT INTO Playlists (path, PL_name)
                    VALUES (?, ?)
                ''', (file_path, pl_name))
                added_playlists += 1
                logger.debug(f"Added playlist: {pl_name}")
                
            except sqlite3.Error as e:
                logger.error(f"Database error adding playlist {file_path}: {e}")
                errors += 1
            except Exception as e:
                logger.error(f"Unexpected error adding playlist {file_path}: {e}")
                errors += 1

        conn.commit()
        conn.close()
        
        logger.info(f"Successfully added {added_playlists} playlists to database")
        if errors > 0:
            logger.warning(f"Encountered {errors} errors while adding playlists")
            
        return added_playlists
        
    except Exception as e:
        logger.error(f"Error adding playlists to database: {e}")
        logger.error(traceback.format_exc())
        return 0


def is_localhost(request):
    """Check if request is from localhost"""
    try:
        is_local = request.remote_addr in ['127.0.0.1', '::1', 'localhost']
        logger.debug(f"Request from {request.remote_addr}, localhost: {is_local}")
        return is_local
    except Exception as e:
        logger.error(f"Error checking localhost: {e}")
        return False


def parse_playlist_file(playlist_path):
    """Parse playlist file and return list of media files with error handling"""
    try:
        logger.info(f"Parsing playlist: {playlist_path}")
        
        if not os.path.exists(playlist_path):
            logger.error(f"Playlist file does not exist: {playlist_path}")
            return []
            
        playlist = []
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
                    with open(playlist_path, 'r', encoding=result.encoding) as f:
                        lines = f.readlines()
                except Exception as e:
                    logger.error(str(e))
                    return playlist

        for line in lines:
            line_count += 1
            try:
               # line = line.strip('ufeff01')
                line = line.strip()
                line = line.strip('.\\')
                if not sys.platform.startswith("win"):
                    line = line.replace("\\","/" )
                if line and not line.startswith(('#', '﻿#')):
                    # Convert relative path to absolute path
                    if not os.path.isabs(line):
                        line = os.path.join(playlist_dir, line)

                    if os.path.exists(line):
                        playlist.append(line)
                        logger.debug(f"Added to playlist: {line}")
                    else:
                        logger.warning(f"File not found in playlist (line {line_count}): {line}")

            except Exception as e:
                logger.warning(f"Error processing playlist line {line_count}: {e}")
                    
        logger.info(f"Parsed playlist with {len(playlist)} valid files")
        return playlist
        
    except Exception as e:
        logger.error(f"Error parsing playlist {playlist_path}: {e}")
        logger.error(traceback.format_exc())
        return []


# Flask error handlers
@app.errorhandler(404)
def not_found_error(error):
    logger.warning(f"404 error: {request.url}")
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {error}")
    logger.error(traceback.format_exc())
    return render_template('500.html'), 500

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {e}")
    logger.error(traceback.format_exc())
    return jsonify({'error': 'Internal server error'}), 500


# Flask routes with error handling
@app.route('/')
def index():
    try:
        logger.info("Serving index page")
        return render_template('index.html',
                               settings=SETTINGS, is_localhost=is_localhost(request))
    except Exception as e:
        logger.error(f"Error serving index page: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Error loading page'}), 500


@app.route('/scan_library', methods=['POST'])
def scan_library():
    try:
        data = request.get_json()
        if data:
            folder_path = data
            logger.info(f"Received folder: {folder_path}")
        if folder_path == None:
            # Run openfile.py (or openfile.exe if app will be converted to
            # windows executable) to select music library folder
           # result = subprocess.run(['python', 'openfile.py'], capture_output=True, text=True)
            result = subprocess.run(["openfile.exe"], capture_output=True, text=True, timeout=50)
            folder_path = result.stdout.strip("\n")

            logger.info(f"Selected folder: {folder_path}")

            if not folder_path or folder_path == "No file selected.":
                logger.warning("No folder selected for scanning")
                return jsonify({'error': 'No folder selected'})

            if not os.path.isdir(folder_path):
                logger.error(f"Invalid folder path: {folder_path}")
                return jsonify({'error': 'Invalid folder path'})
    except subprocess.TimeoutExpired:
            logger.error("Timeout waiting for folder selection")
            return jsonify({'error': 'Timeout waiting for folder selection'})
    try:
        # Scan for audio files and playlists
        logger.info("Starting library scan")
        audio_files, playlist_files = scan_for_audio_files(folder_path)

        # Add to database
        added_songs = add_songs_to_database(audio_files)
        added_playlists = add_playlists_to_database(playlist_files)

        success_msg = f'Successfully added {added_songs} songs and {added_playlists} playlists to the database.'
        logger.info(success_msg)

        return jsonify({
            'success': True,
            'message': success_msg
        })

    except Exception as e:
        logger.error(f"Error during library scan: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)})


@app.route('/get_playlists')
def get_playlists():
    try:
        logger.info("Getting playlists")
        
        conn = sqlite3.connect('Music.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id, PL_name FROM Playlists")
        playlists = cursor.fetchall()
        conn.close()

        logger.info(f"Retrieved {len(playlists)} playlists")
        return jsonify([{'id': p[0], 'name': p[1]} for p in playlists])
        
    except sqlite3.Error as e:
        logger.error(f"Database error getting playlists: {e}")
        return jsonify({'error': 'Database error'}), 500
    except Exception as e:
        logger.error(f"Error getting playlists: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Error retrieving playlists'}), 500


@app.route('/get_all')
def get_all():
    try:
        query = request.args.get('query')

        logger.info(f"Getting all {query}s from db")

        if not query:
            logger.warning("Missing search parameters")
            return jsonify({'error': 'Missing parameters'}), 400

        conn = sqlite3.connect('Music.db')
        cursor = conn.cursor()
        if query == "song_title":
            selection = "SELECT id, artist, song_title, album, path, file_name FROM Songs ORDER BY artist ASC"
        else:
            selection = f"SELECT DISTINCT {query} FROM Songs ORDER BY {query} ASC"
        cursor.execute(selection)
        results = cursor.fetchall()
        conn.close()

        logger.info(f"Retrieved {len(results)} {query}s")
        if query == "song_title":
            return jsonify([{
                'id'      : r[0],
                'artist'  : r[1],
                'title'   : r[2],
                'album'   : r[3],
                'path'    : r[4],
                'filename': r[5]
            } for r in results])
        else:
            return jsonify([{query: r[0]} for r in results])

    except sqlite3.Error as e:
        logger.error(f"Database error getting query: {e}")
        return jsonify({'error': 'Database error'}), 500
    except Exception as e:
        logger.error(f"Error getting query: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Error retrieving query'}), 500


@app.route('/load_playlist/<int:playlist_id>')
def load_playlist(playlist_id):
    try:
        logger.info(f"Loading playlist ID: {playlist_id}")
        
        conn = sqlite3.connect('Music.db')
        cursor = conn.cursor()
        cursor.execute("SELECT path, PL_name FROM Playlists WHERE id = ?", (playlist_id,))
        playlist_data = cursor.fetchone()
        conn.close()

        if not playlist_data:
            logger.warning(f"Playlist not found: {playlist_id}")
            return jsonify({'error': 'Playlist not found'}), 404

        playlist_path, playlist_name = playlist_data
        playlist_files = parse_playlist_file(playlist_path)

        logger.info(f"Loaded playlist '{playlist_name}' with {len(playlist_files)} files")
        return jsonify({
            'success' : True,
            'playlist': playlist_files,
            'name'    : playlist_name
        })
        
    except sqlite3.Error as e:
        logger.error(f"Database error loading playlist {playlist_id}: {e}")
        return jsonify({'error': 'Database error'}), 500
    except Exception as e:
        logger.error(f"Error loading playlist {playlist_id}: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Error loading playlist'}), 500


@app.route('/search_songs')
def search_songs():
    try:
        column = request.args.get('column')
        query = request.args.get('query')
        
        logger.info(f"Searching songs: column={column}, query={query}")

        if not column or not query:
            logger.warning("Missing search parameters")
            return jsonify({'error': 'Missing parameters'}), 400

        conn = sqlite3.connect('Music.db')
        cursor = conn.cursor()

        # First try exact match
        cursor.execute(
            f"SELECT id, artist, song_title, album, path, file_name FROM Songs WHERE {column} LIKE ?",
            (f'%{query}%',))
        results = cursor.fetchall()

        # If no results, try fuzzy matching
        if not results:
            logger.info("No exact matches, trying fuzzy search")
            cursor.execute(
                f"SELECT id, artist, song_title, album, path, file_name, {column} FROM Songs")
            all_songs = cursor.fetchall()

            fuzzy_matches = []
            for song in all_songs:
                try:
                    ratio = fuzz.ratio(query.lower(), song[6].lower())
                    if ratio > 60:  # Threshold for fuzzy matching
                        fuzzy_matches.append((song[:6], ratio))
                except Exception as e:
                    logger.warning(f"Error in fuzzy matching for song {song[0]}: {e}")

            # Sort by similarity
            fuzzy_matches.sort(key=lambda x: x[1], reverse=True)
            results = [match[0] for match in fuzzy_matches[:10]]  # Top 10 matches

        conn.close()
        
        logger.info(f"Search returned {len(results)} results")

        albums = []
        new_results = []
        for result in results:
            if not f'{result[1]} - {result[3]}' in albums:
                albums.append(result[3])
                album_art = get_album_art(result[4])
            else:
                album_art = None
            result_list = list(result)
            result_list.append(album_art)
            new_result = tuple(result_list)
            new_results.append(new_result)

        return jsonify([{
            'id'       : r[0],
            'artist'   : r[1],
            'title'    : r[2],
            'album'    : r[3],
            'path'     : r[4],
            'filename' : r[5],
            'album_art': r[6]
        } for r in new_results])
        
    except sqlite3.Error as e:
        logger.error(f"Database error searching songs: {e}")
        return jsonify({'error': 'Database error'}), 500
    except Exception as e:
        logger.error(f"Error searching songs: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Error searching songs'}), 500


@app.route('/get_song_metadata/<path:file_path>')
def get_song_metadata(file_path):
    try:
        logger.info(f"Getting metadata for: {file_path}")
        
        metadata = get_audio_metadata(file_path)
        if metadata:
            # Convert picture to base64 if exists
            if metadata['picture']:
                try:
                    metadata['picture'] = base64.b64encode(metadata['picture']).decode('utf-8')
                except Exception as e:
                    logger.warning(f"Error encoding album art: {e}")
                    metadata['picture'] = None
                    
            return jsonify(metadata)
        else:
            logger.warning(f"Could not read metadata for: {file_path}")
            return jsonify({'error': 'Could not read metadata'}), 404
            
    except Exception as e:
        logger.error(f"Error getting song metadata for {file_path}: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Error reading metadata'}), 500


@app.route('/serve_audio/<path:file_path>')
def serve_audio(file_path):
    try:
        logger.info(f"Serving audio file: {file_path}")
        
        if not os.path.exists(file_path):
            logger.warning(f"Audio file not found: {file_path}")
            return jsonify({'error': 'File not found'}), 404
            
        return send_file(file_path)
        
    except Exception as e:
        logger.error(f"Error serving audio file {file_path}: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Error serving file'}), 500


@app.route('/settings')
def settings():
    try:
        logger.info("Serving settings page")
        return render_template('settings.html', settings=SETTINGS)
    except Exception as e:
        logger.error(f"Error serving settings page: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Error loading settings'}), 500


@app.route('/save_settings', methods=['POST'])
def save_settings():
    try:
        logger.info("Saving settings")
        
        global SETTINGS
        old_settings = SETTINGS.copy()

        SETTINGS['crossfade_time'] = int(request.form.get('crossfade_time', 4))
        SETTINGS['fade_in'] = int(request.form.get('fade_in', 0))
        
        logger.info(f"Settings updated: {old_settings} -> {SETTINGS}")
        return redirect(url_for('index'))
        
    except ValueError as e:
        logger.error(f"Invalid settings values: {e}")
        return jsonify({'error': 'Invalid settings values'}), 400
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Error saving settings'}), 500

@app.route('/web_ui', methods=['POST'])
def web_ui():
    try:
        if os.environ.get('WERKZEUG_RUN_MAIN') is None:
            webbrowser.open("http://localhost:5000")
            return "Web Interface Lunched Successfully"
    except Exception as e:
        logger.error(f"Error launching Web Interface: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Error launching Web Interface'}), 500

@app.route('/desk_ui', methods=['POST'])
def desk_ui():
    try:
        subprocess.run(["advanced_audio_player.exe"], timeout=3)
        return "Remote Desktop Interface Lunched Successfully"
    except Exception as e:
        logger.error(f"Error launching Desktop Interface: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Error launching Desktop Interface'}), 500


def shutdown_server():
    from werkzeug import Request
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()

@app.route("/shutdown", methods=["POST"])
def shutdown(icon):
    # Restrict to localhost only
   # if request.remote_addr not in ("127.0.0.1", "::1"):
    #    abort(403, "Forbidden: only localhost may request shutdown")

    # Check for secret token (in header or JSON body)
    token = request.headers.get("X-API-Key") or request.json.get("token") if request.is_json else None
    if token != SHUTDOWN_SECRET:
        abort(401, "Unauthorized: invalid shutdown token")
    icon.stop()
    # Try Werkzeug shutdown first
    func = request.environ.get("werkzeug.server.shutdown")
    if func is not None:
        func()
        return "Server shutting down (Werkzeug)..."

    # Fallback for Windows: kill process
    pid = os.getpid()
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        os.system(f"taskkill /PID {pid} /F")
    return f"Server killed (pid {pid})"

@app.route('/start', methods=['POST'])
def start():
    try:
        data = request.json
        path = data.replace('/', '\\')
        subprocess.Popen(r'explorer /select,"' + path + '"', shell=True)
        return jsonify("Song Revealed on Server")
    except Exception as e:
        logger.error(f"Error launching Desktop Interface: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Error Revealing Song'}), 500


def open_browser(icon, item):
    webbrowser.open("http://localhost:5000")

def open_player():
    try:
        subprocess.run(["advanced_audio_player.exe"], timeout=3)
        show_notification("Success", "Desktop Player/Client Lunched Successfully")
    except Exception as e:
        show_notification("Error!", f"Error launching Desktop Interface: {str(e)}")
        logger.error(f"Error launching Desktop Interface: {e}")
        logger.error(traceback.format_exc())

def add_to_startup():
    startup_path = os.path.join(os.getenv('APPDATA'), 'Microsoft\\Windows\\Start Menu\\Programs\\Startup')
    script_path = os.path.abspath(__file__)
    shortcut_path = os.path.join(startup_path, 'FlaskApp.lnk')

    if not os.path.exists(shortcut_path):
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = sys.executable
        shortcut.Arguments = f'"{script_path}"'
        shortcut.WorkingDirectory = os.path.dirname(script_path)
        shortcut.IconLocation = sys.executable
        shortcut.save()
        show_notification("Success", "Ecoserver successfully added to Auto-Start on System Boot")
    else:
        show_notification("Information",
                          "Ecoserver is already set to Auto-Start on System Boot")

def create_image():
    # Create a simple icon for the tray
    image = Image.new('RGB', (64, 64), color=(0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, 48, 48), fill=(255, 255, 255))
    return image

def on_quit(icon, item):
    icon.stop()
    sys.exit()

def setup_tray():
    icon = Icon("Ecoserver", title="Ecoserver is running")
    icon.icon = create_image()
    icon.menu = Menu(MenuItem("Open in browser", open_browser),
                     MenuItem("Open Desktop Player", open_player),
                     MenuItem("Auto-Start on System Boot", add_to_startup),
                     MenuItem("Quit", on_quit))
    icon.run()


if __name__ == '__main__':
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    show_notification("Ecoserver", "Ecoserver is now running in the background.")

    setup_tray()

