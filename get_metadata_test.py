import sqlite3
from mutagen import File
from mediafile import MediaFile
import time
import os
import subprocess
from pathlib import Path

audio_extensions = {'.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac', '.wma'}

def init_database(db_path):
    """Initialize the database with proper error handling"""
    try:
        print("Initializing database...")
        conn = sqlite3.connect(db_path)
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

        conn.commit()
        conn.close()


    except sqlite3.Error as e:
        print(f"Database initialization failed: {e}")
        raise
    except Exception as e:
        print(f"Unexpected error during database initialization: {e}")
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

        audio_files = []
        scan_errors = 0

        for root, dirs, files in os.walk(directory):
            print(f"Scanning folder: {root}")

            for file in files:
                try:
                    file_path = os.path.join(root, file)
                    file_ext = Path(file).suffix.lower()

                    if file_ext in audio_extensions:
                        audio_files.append(file_path)

                except Exception as e:
                    print(f"Error processing file {file}: {e}")
                    scan_errors += 1

        print(
            f"Scan complete. Found {len(audio_files)} audio files")
        if scan_errors > 0:
            print(f"Encountered {scan_errors} errors during scanning")

        return audio_files

    except Exception as e:
        print(f"Error scanning directory {directory}: {e}")
        return [], []


def add_songs_to_database(audio_files, db_path):
    """Add audio files to database with error handling"""
    try:
        print(f"Adding {len(audio_files)} audio files to database")

        conn = sqlite3.connect(db_path)
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
                if db_path == 'test_mediafile.db':
                    metadata = get_audio_metadata(file_path)
                else:
                    metadata = get_basic_metadata(file_path)
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


def scan_library():

    try:
        result = subprocess.run(["openfile.exe"], capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print("Error running openfile.exe")
            print({'error': 'Error running openfile.exe'})
            return
        folder_path = result.stdout.strip("\n")
        print(f"Selected folder: {folder_path}")

        if not folder_path or folder_path == "No file selected.":
            print("No folder selected for scanning")
            print({'error': 'No folder selected'})
            return

        if not os.path.isdir(folder_path):
            print(f"Invalid folder path: {folder_path}")
            print({'error': 'Invalid folder path'})
            return
    except subprocess.TimeoutExpired:
        print("Timeout waiting for folder selection")

    return folder_path



def get_basic_metadata(file_path):
    audio_file = File(file_path)
    if audio_file is None:
        print(
            f"Could not read audio file: {file_path}. Make sure the file exists.")
        return None

    metadata = {
        'artist': '',
        'album_artist': '',
        'song_title': '',
        'album': '',
        'year': '',
        'duration': 0
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
        print(
            f"Error reading artist metadata from {file_path}: {str(e)}")

    try:
        if 'TPE2' in audio_file:  # Album Artist
            metadata['album_artist'] = str(audio_file['TPE2'])
        elif 'ALBUMARTIST' in audio_file:
            metadata['album_artist'] = str(audio_file['ALBUMARTIST'][0])
        elif 'albumartist' in audio_file:
            metadata['album_artist'] = str(audio_file['albumartist'][0])
        elif '©ART' in audio_file:
            metadata['album_artist'] = str(audio_file['©ART'][0])
        else:
            # fallback: use artist if album artist not present
            if metadata['artist']:
                metadata['album_artist'] = metadata['artist']
    except Exception as e:
        print(
            f"Error reading album artist metadata from {file_path}: {str(e)}")

    try:
        if 'TIT2' in audio_file:  # Title
            metadata['song_title'] = str(audio_file['TIT2'])
        elif 'TITLE' in audio_file:
            metadata['song_title'] = str(audio_file['TITLE'][0])
        elif '©nam' in audio_file:
            metadata['song_title'] = str(audio_file['©nam'][0])
        else:
            # fallback: use file name if title not present
            metadata['song_title'] = os.path.basename(file_path)
    except Exception as e:
        print(
            f"Error reading title metadata from {file_path}: {str(e)}")

    try:
        if 'TALB' in audio_file:  # Album
            metadata['album'] = str(audio_file['TALB'])
        elif 'ALBUM' in audio_file:
            metadata['album'] = str(audio_file['ALBUM'][0])
        elif '©alb' in audio_file:
            metadata['album'] = str(audio_file['©alb'][0])
    except Exception as e:
        print(
            f"Error reading album metadata from {file_path}: {str(e)}")

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


    return metadata



def get_audio_metadata(file_path):

    """Extract metadata from an audio file using MediaFile."""
    metadata = {
        'artist'      : '',
        'album_artist': '',
        'song_title'  : '',
        'album'       : '',
        'year'        : '',
        'duration'    : 0
    }
    file = MediaFile(file_path)
    try:
        title = file.title
        artist = file.artist
        album = file.album
        albumartist = file.albumartist

        if file.length:
            duration = f"{(file.length // 60):.0f}:" + "{:06.3F}".format(file.length % 60)
        else:
            duration = '---'
        if file.year:
            year = str(file.year)
        else:
            year = '---'
        if file.original_year:
            original_year = str(file.original_year)
            year = original_year

        metadata = {
            'artist'            : artist or 'Unknown Artist',
            'album_artist'      : albumartist or artist or 'Unknown Album Artist',
            'song_title'        : title or os.path.basename(file_path),
            'album'             : album or 'Unknown Album',
            'year'              : year or '---',
            'duration'          : duration
        }
    except Exception as e:
        print(f"Error extracting metadata from {file_path}: {str(e)}")

    return metadata



def main():
    folder_path = scan_library()
    if folder_path:
        print("Starting library scan")
        audio_files = scan_for_audio_files(folder_path)
        start_time = time.time()
        try:
            init_database('test_mediafile.db')
            # Add to database
            added_songs = add_songs_to_database(audio_files, 'test_mediafile.db')

            success_msg = f'Successfully added {added_songs} songs to the database.'
            print(success_msg)

        except Exception as e:
            print(f"Error during library scan: {e}")
        print("--- %s  test_mediafile ---" % (time.time() - start_time))
        try:
            init_database('test_mutagen.db')
            # Add to database
            added_songs = add_songs_to_database(audio_files, 'test_mutagen.db')

            success_msg = f'Successfully added {added_songs} songs to the database.'
            print(success_msg)

        except Exception as e:
            print(f"Error during library scan: {e}")
        print("--- %s test_mutagen ---" % (time.time() - start_time))
        start_time = time.time()



if __name__ == "__main__":
  main()


