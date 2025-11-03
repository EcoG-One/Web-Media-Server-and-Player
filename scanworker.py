
import os
import sqlite3
from PySide6.QtCore import QMutex, QObject, Signal
from mutagen import File
from pathlib import Path
from PIL import Image
from io import BytesIO
import base64


APP_DIR = Path.home() / "Web-Media-Server-and-Player"
APP_DIR.mkdir(exist_ok=True)
DB_PATH = APP_DIR / 'music.db'
COVERS_DB_PATH = APP_DIR / 'covers.db'
audio_extensions = {'.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac', '.wma'}
playlist_extensions = {'.m3u', '.m3u8', '.cue', '.json'}

class ScanWorker(QObject):
    started = Signal(str)  # directory
    folder_scanned = Signal(str)  # root folder path
    finished = Signal(list, list, int)  # audio_files, playlist_files, scan_errors
    error = Signal(str)  # error message
    warning = Signal(str)  # warning message
    status = Signal(str)  # status message

    def __init__(self, directory):
        super().__init__()
        self.directory = directory
        self.audio_extensions = set(audio_extensions)
        self.playlist_extensions = set(playlist_extensions)
        self._stopped = False
        self.mutex = QMutex()

    def stop(self):
        self._stopped = True

    def run(self):
        try:
            self.started.emit(self.directory)

            if not os.path.exists(self.directory):
                self.error.emit(
                    f"Directory does not exist: {self.directory}")
                self.finished.emit([], [], 0)
                return

            if not os.path.isdir(self.directory):
                self.error.emit(
                    f"Path is not a directory: {self.directory}")
                self.finished.emit([], [], 0)
                return

            audio_files = []
            playlist_files = []
            scan_errors = 0

            for root, dirs, files in os.walk(self.directory):
                if self._stopped:
                    break
                # emit progress update
                self.folder_scanned.emit(root)

                for file in files:
                    if self._stopped:
                        break
                    try:
                        file_path = os.path.join(root, file)
                        file_ext = Path(file).suffix.lower()

                        if file_ext in self.audio_extensions:
                            audio_files.append(file_path)
                        elif file_ext in self.playlist_extensions:
                            playlist_files.append(file_path)

                    except Exception as e:
                        scan_errors += 1
                        # non-blocking warning signal
                        self.warning.emit(
                            f"Error processing file {file}: {e}")
            try:
                added_songs, added_covers = self.add_songs_to_database(
                    audio_files)
                added_playlists = self.add_playlists_to_database(
                    playlist_files)
                success_msg = (
                    f'Added {added_songs} songs, {added_playlists} playlists, '
                    f'{added_covers} albums to the database and encountered {scan_errors} errors.')
                self.status.emit(success_msg)
            #  QMessageBox.information(self, 'info', success_msg)
            except Exception as e:
                self.error.emit(f"Error adding to database: {e}")
                return
            self.finished.emit(added_songs, added_playlists, scan_errors)

        except Exception as e:
            self.error.emit(
                f"Error scanning directory {self.directory}: {e}")
            self.finished.emit([], [], 1)


    def get_audio_metadata(self, file_path):
        """Extract metadata from audio file with comprehensive error handling"""
        try:
            self.status.emit(f"Extracting metadata from: {file_path}")

            if not os.path.exists(file_path):
                self.warning.emit(f"File does not exist: {file_path}")
                return None

            audio_file = File(file_path)
            if audio_file is None:
                self.warning.emit(f"Could not read audio file: {file_path}. Make sure the file exists.")
                return None

            metadata = {
                'artist'  : 'Unknown Artist',
                'album_artist': 'Unknown Album Artist',
                'title'   : 'Unknown Title',
                'album'   : 'Unknown Album',
                'year'    : 'Unknown Year',
                'duration': 0,
                'lyrics'  : '',
                'codec'   : '',
                'picture' : None,
                'transition_duration' : 4.0
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
                self.warning.emit(
                    f"Error reading artist metadata from {file_path}: {str(e)}")

            try:
                if 'TPE2' in audio_file:  # Album artist (ID3)
                    metadata['album_artist'] = str(audio_file['TPE2'])
                elif 'ALBUMARTIST' in audio_file:
                    metadata['album_artist'] = str(
                        audio_file['ALBUMARTIST'][0])
                elif 'albumartist' in audio_file:
                    metadata['album_artist'] = str(
                        audio_file['albumartist'][0])
                elif 'aART' in audio_file:  # MP4 atom for album artist
                    metadata['album_artist'] = str(audio_file['aART'][0])
                else:
                    # fallback: use artist if album artist not present
                    if metadata['artist']:
                        metadata['album_artist'] = metadata['artist']
            except Exception as e:
                self.warning.emit(
                    f"Error reading album artist metadata from {file_path}: {str(e)}")
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
                else:
                    metadata['title'] = os.path.splitext(
                        os.path.basename(file_path))[0]
            except Exception as e:
                self.warning.emit(
                    f"Error reading title metadata from {file_path}: {str(e)}")

            try:
                if 'TALB' in audio_file:  # Album
                    metadata['album'] = str(audio_file['TALB'])
                elif 'ALBUM' in audio_file:
                    metadata['album'] = str(audio_file['ALBUM'][0])
                elif '©alb' in audio_file:
                    metadata['album'] = str(audio_file['©alb'][0])
            except Exception as e:
                self.warning.emit(
                    f"Error reading album metadata from {file_path}: {str(e)}")

            try:
                if 'TDRC' in audio_file:  # Year
                    metadata['year'] = str(audio_file['TDRC'])
                elif 'DATE' in audio_file:
                    metadata['year'] = str(audio_file['DATE'][0])
                elif '©day' in audio_file:
                    metadata['year'] = str(audio_file['©day'][0])
            except Exception as e:
                self.warning.emit(
                    f"Error reading year metadata from {file_path}: {str(e)}")

            # Duration
            try:
                if audio_file.info:
                    metadata['duration'] = int(audio_file.info.length)
            except Exception as e:
                self.warning.emit(f"Error reading duration from {file_path}: {str(e)}")

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
                    # MP4/AAC
                    elif hasattr(audio_file, 'tags') and hasattr(
                        audio_file.tags, 'get'):
                        if audio_file.tags.get('\xa9lyr'):
                            metadata['lyrics'] = \
                            audio_file.tags['\xa9lyr'][0]
                        # MP3 (ID3)
                    elif hasattr(audio_file, 'tags') and audio_file.tags:
                        # USLT (unsynchronized lyrics) is the standard for ID3
                        for k in audio_file.tags.keys():
                            if k.startswith('USLT') or k.startswith('SYLT'):
                                metadata['lyrics'] = str(audio_file.tags[k])
                            if k.lower() in ('lyrics', 'unsyncedlyrics',
                                             'lyric'):
                                metadata['lyrics'] = str(audio_file.tags[k])
                    else:
                        metadata['lyrics'] = "--"
                # If still no lyrics, try fetching from online source removed for brevity
            except Exception as e:
                self.warning.emit(f"Error reading lyrics from {file_path}: {str(e)}")

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
                self.warning.emit(f"Error reading codec from {file_path}: {str(e)}")

            # Album art
            try:
                if 'APIC:' in audio_file:
                    metadata['picture'] = audio_file['APIC:'].data
                elif hasattr(audio_file, 'pictures') and audio_file.pictures:
                    metadata['picture'] = audio_file.pictures[0].data
                elif 'covr' in audio_file:
                    metadata['picture'] = audio_file['covr'][0]
            except Exception as e:
                self.warning.emit(
                    f"Error reading album art from {file_path}: {str(e)}")

            # Transition Duration removed for brevity


            self.status.emit(f"Successfully extracted metadata from: {file_path}", 3000)
            return metadata

        except Exception as e:
            self.warning.emit(f"Error extracting metadata from {file_path}: {str(e)}")
            return None


    def get_album_art(self, path):
        img_data = None
        try:
            audio = File(path)
            if audio is not None and hasattr(audio, 'tags'):
                tags = audio.tags
                if 'APIC:' in tags:
                    img_data = tags['APIC:'].data
                elif hasattr(tags, 'get') and tags.get('covr'):
                    img_data = tags['covr'][0]
                elif hasattr(audio, 'pictures') and audio.pictures:
                    img_data = audio.pictures[0].data
            if img_data:
                try:
                    album_art = base64.b64encode(img_data).decode('utf-8')
                except Exception as e:
                    self.warning.emit(f"Error encoding album art: {str(e)}")
                    album_art = None
                return album_art
        except Exception as e:
            self.warning.emit("Artwork extraction error:" + str(e))


    def add_songs_to_database(self, audio_files):
        """Add audio files to database with error handling"""
        try:
            self.status.emit(
                f"Adding {len(audio_files)} audio files to database")
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            added_songs = 0
            added_covers = 0
            errors = 0
            size = 256, 256
            cursor.execute(f'ATTACH DATABASE "{COVERS_DB_PATH}" AS Covers')

            for file_path in audio_files:
                try:
                    # Check if file already exists
                    cursor.execute("SELECT id FROM Songs WHERE path = ?",
                                   (file_path,))
                    if cursor.fetchone():
                        self.status.emit(
                            f"File already in database: {file_path}")
                        continue

                    metadata = self.get_audio_metadata(file_path)
                    if metadata:
                        file_name = os.path.basename(file_path)
                        cursor.execute('''
                               INSERT INTO Songs (path, file_name, artist, album_artist, song_title, duration, album, year)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                           ''', (
                            file_path,
                            file_name,
                            metadata['artist'],
                            metadata['album_artist'],
                            metadata['title'],
                            metadata['duration'],
                            metadata['album'],
                            metadata['year']
                        ))
                        added_songs += 1
                        self.status.emit(
                            f"Added song: {metadata['artist']} - {metadata['title']}")
                        cursor.execute(
                            "SELECT Covers.album FROM Covers WHERE Covers.album = ?",
                            (metadata['album'],))
                        if cursor.fetchone():
                            self.status.emit(
                                f"Cover already in database: {metadata['album']}")
                            continue
                        img = self.get_album_art(file_path)
                        if img is None:
                            cover = None
                        else:
                            im = Image.open(BytesIO(base64.b64decode(img)))
                            im.thumbnail(size)
                            im_file = BytesIO()
                            im.save(im_file, format="JPEG")
                            im_bytes = im_file.getvalue()  # im_bytes: image in binary format.
                            cover = base64.b64encode(im_bytes).decode('utf-8')
                        cursor.execute(
                            '''INSERT INTO Covers (album, album_artist, cover) VALUES (?, ?, ?)''',
                            (metadata['album'], metadata['album_artist'], cover))
                        added_covers += 1
                    else:
                        self.warning.emit(f"Could not extract metadata from: {file_path}")
                        errors += 1

                except sqlite3.Error as e:
                    self.warning.emit(f"Database error adding song {file_path}: {e}")
                    errors += 1
                except Exception as e:
                    self.warning.emit(f"Unexpected error adding song {file_path}: {e}")
                    errors += 1

            conn.commit()
            conn.close()

            self.status.emit(f"Successfully added {added_songs} songs and {added_covers} covers to database and encountered {errors} errors")
            return added_songs, added_covers

        except Exception as e:
            self.warning.emit(f"Error adding songs to database: {str(e)}")


    def add_playlists_to_database(self, playlist_files):
        """Add playlist files to database with error handling"""
        try:
            self.status.emit(f"Adding {len(playlist_files)} playlists to database")

            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            added_playlists = 0
            errors = 0

            for file_path in playlist_files:
                try:
                    # Check if playlist already exists
                    cursor.execute("SELECT id FROM Playlists WHERE path = ?",
                                   (file_path,))
                    if cursor.fetchone():
                        self.status.emit(
                            f"Playlist already in database: {file_path}")
                        continue

                    pl_name = os.path.basename(file_path)
                    cursor.execute('''
                        INSERT INTO Playlists (path, PL_name)
                        VALUES (?, ?)
                    ''', (file_path, pl_name))
                    added_playlists += 1
                    self.status.emit(f"Added playlist: {pl_name}")

                except sqlite3.Error as e:
                    self.status.emit(
                        f"Database error adding playlist {file_path}: {str(e)}")
                    errors += 1
                except Exception as e:
                    self.status.emit(
                        f"Unexpected error adding playlist {file_path}: {str(e)}")
                    errors += 1

            conn.commit()
            conn.close()

            self.status.emit(f"Successfully added {added_playlists} playlists to database")
            if errors > 0:
                self.warning.emit(f"Encountered {errors} errors while adding playlists")

            return added_playlists

        except Exception as e:
            self.warning.emit(f"Error adding playlists to database: {str(e)}")