import sqlite3
import os
from mutagen import File
from pathlib import Path
import base64
from PIL import Image
from io import BytesIO

def init_database():
    """Initialize the database with proper error handling"""
    try:
        print("Initializing database...")
        conn = sqlite3.connect('music.db')
        cursor = conn.cursor()

        # Create Songs table (including album_artist column)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS Songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path CHAR(255) NOT NULL,
                file_name CHAR(120) NOT NULL,
                artist CHAR(120) NOT NULL,
                album_artist CHAR(120),
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

        conn = sqlite3.connect('covers.db')
        cursor = conn.cursor()

        # Create Album Art table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS Covers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                album CHAR(120) NOT NULL,
                album_artist CHAR(120) NOT NULL,
                cover TEXT
            )
        ''')

        conn.commit()
        conn.close()
        print("Database initialized successfully")

    except sqlite3.Error as e:
        print(f"Database initialization failed: {str(e)}")
        raise
    except Exception as e:
        print(f"Unexpected error during database initialization: {str(e)}")
        raise


def scan_for_audio_files(directory):
    """Scan directory for audio files and playlists with error handling"""
    try:
        print(f"Scanning directory: {directory}")

        if not os.path.exists(directory):
            print(f"Directory does not exist: {directory}")
            return [], []

        if not os.path.isdir(directory):
            print(f"Path is not a directory: {directory}")
            return [], []

        audio_extensions = {'.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac',
                            '.wma'}
        playlist_extensions = {'.m3u', '.m3u8', '.cue'}

        audio_files = []
        playlist_files = []
        scan_errors = 0

        for root, dirs, files in os.walk(directory):
            print(f"Scanning folder: {root}")

            for file in files:
                try:
                    file_path = os.path.join(root, file)
                    file_ext = Path(file).suffix.lower()

                    if file_ext in audio_extensions:
                        audio_files.append(file_path)
                    elif file_ext in playlist_extensions:
                        playlist_files.append(file_path)

                except Exception as e:
                    print(f"Error processing file {file}: {str(e)}")
                    scan_errors += 1

        print(
            f"Scan complete. Found {len(audio_files)} audio files and {len(playlist_files)} playlists")
        if scan_errors > 0:
            print(f"Encountered {scan_errors} errors during scanning")

        return audio_files, playlist_files

    except Exception as e:
        print(f"Error scanning directory {directory}: {str(e)}")
        return [], []


def get_audio_metadata(file_path):
    """Extract metadata from audio file with comprehensive error handling"""
    try:
        print(f"Extracting metadata from: {file_path}")

        if not os.path.exists(file_path):
            print(f"File does not exist: {file_path}")
            return None

        audio_file = File(file_path)
        if audio_file is None:
            print(f"Could not read audio file: {file_path}")
            return None

        metadata = {
            'artist'             : '',
            'album_artist'       : '',
            'title'              : '',
            'album'              : '',
            'year'               : '',
            'duration'           : 0,
            'lyrics'             : '',
            'codec'              : '',
            'picture'            : None,
            'transition_duration': 5.0
        }

        # Get basic metadata - ARTIST
        try:
            if 'TPE1' in audio_file:  # Artist (ID3)
                metadata['artist'] = str(audio_file['TPE1'])
            elif 'ARTIST' in audio_file:
                metadata['artist'] = str(audio_file['ARTIST'][0])
            elif '©ART' in audio_file:
                metadata['artist'] = str(audio_file['©ART'][0])
        except Exception as e:
            print(
                f"Error reading artist metadata from {file_path}: {e}")

        # Get album artist (common tags: TPE2 (ID3), ALBUMARTIST, albumartist, aART (MP4))
        try:
            if 'TPE2' in audio_file:  # Album artist (ID3)
                metadata['album_artist'] = str(audio_file['TPE2'])
            elif 'ALBUMARTIST' in audio_file:
                metadata['album_artist'] = str(audio_file['ALBUMARTIST'][0])
            elif 'albumartist' in audio_file:
                metadata['album_artist'] = str(audio_file['albumartist'][0])
            elif 'aART' in audio_file:  # MP4 atom for album artist
                metadata['album_artist'] = str(audio_file['aART'][0])
            else:
                # fallback: use artist if album artist not present
                if metadata['artist']:
                    metadata['album_artist'] = metadata['artist']
        except Exception as e:
            print(
                f"Error reading album artist metadata from {file_path}: {e}")
            # fallback to artist
            if metadata['artist']:
                metadata['album_artist'] = metadata['artist']

        try:
            if 'TIT2' in audio_file:  # Title
                metadata['title'] = str(audio_file['TIT2'])
            elif 'TITLE' in audio_file:
                metadata['title'] = str(audio_file['TITLE'][0])
            elif '©nam' in audio_file:
                metadata['title'] = str(audio_file['©nam'][0])
        except Exception as e:
            print(
                f"Error reading title metadata from {file_path}: {e}")

        try:
            if 'TALB' in audio_file:  # Album
                metadata['album'] = str(audio_file['TALB'])
            elif 'ALBUM' in audio_file:
                metadata['album'] = str(audio_file['ALBUM'][0])
            elif '©alb' in audio_file:
                metadata['album'] = str(audio_file['©alb'][0])
        except Exception as e:
            print(
                f"Error reading album metadata from {file_path}: {e}")

        try:
            if 'TDRC' in audio_file:  # Year
                metadata['year'] = str(audio_file['TDRC'])
            elif 'DATE' in audio_file:
                metadata['year'] = str(audio_file['DATE'][0])
            elif '©day' in audio_file:
                metadata['year'] = str(audio_file['©day'][0])
        except Exception as e:
            print(
                f"Error reading year metadata from {file_path}: {e}")

        # Duration
        try:
            if audio_file.info:
                metadata['duration'] = int(audio_file.info.length)
        except Exception as e:
            print(f"Error reading duration from {file_path}: {e}")

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
                elif hasattr(audio_file, 'tags') and hasattr(audio_file.tags,
                                                             'get'):
                    if audio_file.tags.get('\xa9lyr'):
                        metadata['lyrics'] = audio_file.tags['\xa9lyr'][0]
                else:
                    metadata['lyrics'] = "--"

        except Exception as e:
            print(f"Error reading lyrics from {file_path}: {e}")

        # Codec
        try:
            codec = audio_file.mime[0] if hasattr(audio_file,
                                                  'mime') and audio_file.mime else audio_file.__class__.__name__

            # Sample rate and bitrate
            sample_rate = getattr(audio_file.info, 'sample_rate', None)
            bits = getattr(audio_file.info, 'bits_per_sample', None)
            bitrate = getattr(audio_file.info, 'bitrate', None)
            if codec == 'audio/mp3':
                metadata['codec'] = codec + ' ' + str(
                    sample_rate / 1000) + 'kHz ' + str(
                    round(bitrate / 1000)) + 'kbps'
            else:
                metadata['codec'] = codec + ' ' + str(
                    sample_rate / 1000) + 'kHz/' + str(
                    round(bits)) + 'bits  ' + str(
                    round(bitrate / 1000)) + 'kbps'
        except Exception as e:
            print(f"Error reading codec from {file_path}: {e}")

        # Album art
        try:
            if 'APIC:' in audio_file:
                metadata['picture'] = audio_file['APIC:'].data
            elif hasattr(audio_file, 'pictures') and audio_file.pictures:
                metadata['picture'] = audio_file.pictures[0].data
            elif 'covr' in audio_file:
                metadata['picture'] = audio_file['covr'][0]
        except Exception as e:
            print(f"Error reading album art from {file_path}: {e}")

        try:
            metadata["transition_duration"] = 4
        except Exception as e:
            print(
                f"Error detecting transition duration from {file_path}: {e}")

        print(f"Successfully extracted metadata from: {file_path}")
        return metadata

    except Exception as e:
        print(f"Error extracting metadata from {file_path}: {e}")
        return None



def add_songs_to_database(audio_files):
    """Add audio files to database with error handling"""
    try:
        print(f"Adding {len(audio_files)} audio files to database")

        conn = sqlite3.connect('music.db')
        cursor = conn.cursor()
        added_songs = 0
        errors = 0

        for file_path in audio_files:
            try:
                # Check if file already exists
                cursor.execute("SELECT id FROM Songs WHERE path = ?",
                               (file_path,))
                if cursor.fetchone():
                    print(f"File already in database: {file_path}")
                    continue

                metadata = get_audio_metadata(file_path)
                if metadata:
                    file_name = os.path.basename(file_path)
                    # Insert including album_artist (may be empty)
                    cursor.execute('''
                        INSERT INTO Songs (path, file_name, artist, album_artist, song_title, duration, album, year)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        file_path,
                        file_name,
                        metadata.get('artist', ''),
                        metadata.get('album_artist', ''),
                        metadata.get('title', ''),
                        metadata.get('duration', 0),
                        metadata.get('album', ''),
                        metadata.get('year', '')
                    ))
                    added_songs += 1
                    print(
                        f"Added song: {metadata.get('artist','')} - {metadata.get('title','')}")
                else:
                    print(
                        f"Could not extract metadata from: {file_path}")
                    errors += 1

            except sqlite3.Error as e:
                print(f"Database error adding song {file_path}: {e}")
                errors += 1
            except Exception as e:
                print(f"Unexpected error adding song {file_path}: {e}")
                errors += 1

        conn.commit()
        conn.close()

        print(f"Successfully added {added_songs} songs to database")
        if errors > 0:
            print(f"Encountered {errors} errors while adding songs")

        return added_songs

    except Exception as e:
        print(f"Error adding songs to database: {e}")
        return 0


def get_album_art(file_path):
    print(f"Extracting metadata from: {file_path}")

    if not os.path.exists(file_path):
        print(f"File does not exist: {file_path}")
        return None
    album_art = None
    audio_file = File(file_path)
    if audio_file is None:
        print(f"Could not read audio file: {file_path}")
        return None
    try:
        if 'APIC:' in audio_file:
            album_art = audio_file['APIC:'].data
        elif hasattr(audio_file, 'pictures') and audio_file.pictures:
            album_art = audio_file.pictures[0].data
        elif 'covr' in audio_file:
            album_art = audio_file['covr'][0]
    except Exception as e:
        print(f"Error reading album art from {file_path}: {e}")
    print(f"Successfully extracted album art from: {file_path}")
    try:
        album_art = base64.b64encode(album_art).decode('utf-8')
    except Exception as e:
        print(f"Error encoding album art: {e}")
        album_art = None
    return album_art

def add_covers_to_database():
    """Add album art files to database with error handling"""
    size = 256, 256
    try:
        added_covers = 0
        errors = 0
        results = None
        try:
            conn = sqlite3.connect('music.db')
            cursor = conn.cursor()
            # Select a song per album
            cursor.execute("SELECT album, path FROM Songs GROUP BY album")
            results = cursor.fetchall()
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            print(f"Database error getting Albums from database: {e}")
            errors += 1
        except Exception as e:
            print(f"Unexpected error getting Albums from database: {e}")
            errors += 1

        if results:
            print(f"Adding {len(results)} covers to database")
            try:
                conn = sqlite3.connect('covers.db')
                cursor = conn.cursor()
                for result in results:
                    album = result[0]
                    img = get_album_art(result[1])
                    if img is None:
                        cover = None
                    else:
                        im = Image.open(BytesIO(base64.b64decode(img)))
                        im.thumbnail(size)
                        im_file = BytesIO()
                        im.save(im_file, format="JPEG")
                        im_bytes = im_file.getvalue()  # im_bytes: image in binary format.
                        cover = base64.b64encode(im_bytes).decode('utf-8')
                    cursor.execute('''
                        INSERT INTO Covers (album, cover) 
                        VALUES (?,?)''', (album, cover))
                    added_covers += 1
                    print(
                        f"Added cover from album: {album}")
                else:
                    print(
                        f"Could not get album art from album: {album}")
                    errors += 1
                conn.commit()
                conn.close()
            except sqlite3.Error as e:
                print(f"Database error adding album art from album: {album}: {e}")
                errors += 1
            except Exception as e:
                print(f"Unexpected error adding album art from album: {album}: {e}")
                errors += 1

            print(f"Successfully added {added_covers} songs to database")
            if errors > 0:
                print(f"Encountered {errors} errors while adding songs")

            return added_covers

    except Exception as e:
        print(f"Error adding covers to database: {e}")
        return 0


def add_playlists_to_database(playlist_files):
    """Add playlist files to database with error handling"""
    try:
        print(f"Adding {len(playlist_files)} playlists to database")

        conn = sqlite3.connect('music.db')
        cursor = conn.cursor()
        added_playlists = 0
        errors = 0

        for file_path in playlist_files:
            try:
                # Check if playlist already exists
                cursor.execute("SELECT id FROM Playlists WHERE path = ?",
                               (file_path,))
                if cursor.fetchone():
                    print(f"Playlist already in database: {file_path}")
                    continue

                pl_name = os.path.basename(file_path)
                cursor.execute('''
                    INSERT INTO Playlists (path, PL_name)
                    VALUES (?, ?)
                ''', (file_path, pl_name))
                added_playlists += 1
                print(f"Added playlist: {pl_name}")

            except sqlite3.Error as e:
                print(
                    f"Database error adding playlist {file_path}: {e}")
                errors += 1
            except Exception as e:
                print(
                    f"Unexpected error adding playlist {file_path}: {e}")
                errors += 1

        conn.commit()
        conn.close()

        print(
            f"Successfully added {added_playlists} playlists to database")
        if errors > 0:
            print(
                f"Encountered {errors} errors while adding playlists")

        return added_playlists

    except Exception as e:
        print(f"Error adding playlists to database: {e}")
        return 0


try:
    # Scan for audio files and playlists
    print("Starting library scan")
    audio_files, playlist_files = scan_for_audio_files("/share/Music/0.AtoZ")

    # Add to database
    added_songs = add_songs_to_database(audio_files)
    added_playlists = add_playlists_to_database(playlist_files)

    success_msg = f'Successfully added {added_songs} songs and {added_playlists} playlists to the database.'
    print(success_msg)

except Exception as e:
    print(f"Error during library scan: {str(e)}")
