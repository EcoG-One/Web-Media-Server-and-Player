# Web-Media-Server-and-Player
**A comprehensive media server and player web application using Python, JavaScript, CSS and HTML**

## Key Features:

- **Database Management:** Automatically creates SQLite database "Music" with "Songs" and "Playlists" tables
- **Flask Web Server:** Complete web application with HTML interface
- **Library Scanning:** Uses your openfile.py script to select folders and scans for audio files and playlists
- **Playlist Support:** Loads and plays .m3u, .m3u8, and .pls playlist files
- **Search Functionality:** Search by artist, song title, or album with fuzzy matching
- **Audio Metadata:** Extracts and displays metadata including album art
- **Crossfading:** Dual audio elements for seamless crossfading between songs
- **Settings:** Configurable server port and crossfade time

**Dependencies Required:**
You'll need to install these Python packages:
   ```sh
pip install flask mutagen fuzzywuzzy python-levenshtein
   ```   
**Additional Files Needed:**
```sh
- Create a templates folder and add:
index.html template
settings.html template
   ``` 
### Setup Instructions:

**Create project structure:**
```sh
media_server/
├── media_server.py (main application)
├── openfile.py (music folder selector script)
└── templates/
    └── index.html
    └── settings.html
   ``` 
**Install dependencies:**
```sh
pip install flask mutagen fuzzywuzzy python-levenshtein
   ``` 
**Run the application:**
```sh
python media_server.py
   ``` 

Key Features Implemented:

- **Smart Menu:** Hides "Scan Library" when not on localhost
- **Audio Metadata:** Extracts artist, title, album, year, duration, and album art
- **Crossfading:** Seamless transition between songs with configurable timing
- **Search:** Both exact and fuzzy string matching
- **Playlist Support:** Parses M3U and PLS files with relative path resolution
- **Database Integration:** Prevents duplicate entries and maintains library state
- **Web Interface:** Clean, responsive interface with all required functionality

*The application will start a web server on port 5000 (configurable) 
and provide a complete media player experience with all the features you requested. 
The interface is intuitive and handles errors gracefully while providing feedback to users.*
