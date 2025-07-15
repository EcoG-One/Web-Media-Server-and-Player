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
- **Logging** Multi-Level Logging System

**Dependencies Required:**
You'll need to install these Python packages:
   ```sh
pip install flask mutagen fuzzywuzzy python-levenshtein
   ```   
**Additional Files Needed:**
```sh
Create a templates folder and add:
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
python ecoserver.py
   ``` 

Key Features Implemented:

- **Smart Menu:** Hides "Scan Library" when not on localhost
- **Audio Metadata:** Extracts artist, title, album, year, duration, and album art
- **Crossfading:** Seamless transition between songs with configurable timing
- **Search:** Both exact and fuzzy string matching
- **Playlist Support:** Parses M3U and PLS files with relative path resolution
- **Database Integration:** Prevents duplicate entries and maintains library state
- **Web Interface:** Clean, responsive interface with all required functionality

🔧 Logging Features:
1. **Multi-Level Logging System**
Debug logs: Detailed function calls and data processing
Info logs: General operation status and user actions
Warning logs: Non-critical issues that don't break functionality
Error logs: Critical errors with full stack traces
2. **Multiple Log Destinations**
logs/ecoserver.log: Complete application logs (all levels)
logs/errors.log: Error-only logs for quick troubleshooting
Console output: Real-time monitoring during development
3. **Enhanced Error Handling**
Database operations: Proper SQLite error handling
File operations: Checks for file existence and permissions
Metadata extraction: Graceful handling of corrupt audio files
Network requests: Timeout handling for external processes
Flask routes: Global exception handlers for web requests
4. **Detailed Error Context**
Function names and line numbers in logs
Full stack traces for debugging
Request information (IP addresses, URLs)
Performance metrics (file counts, processing times)
5. **Key Monitoring Points**
Library scanning progress and errors
Database operations success/failure
File accessibility issues
Metadata extraction problems
Playlist parsing errors
Search operation performance

📁 Log Files Created:
The application will automatically create a logs/ directory with:
```sh
ecoserver.log - Complete application activity
errors.log - Critical errors only
```
🚀 Additional Benefits:

- **Startup logging** - Records Python version, working directory
- **Request tracking** - Logs all incoming HTTP requests
- **Performance monitoring** - Tracks file processing times
- **Security logging** - Records localhost vs. remote access attempts
- **Graceful degradation** - Application continues running even with non-critical errors

The enhanced logging provides detailed insights into what's happening under the hood. 
This will make it much easier to diagnose issues, monitor performance, and maintain the application in production.

*The application will start a web server on port 5000 (configurable) 
and provide a complete media player experience with all the features mentioned above. 
The interface is intuitive and handles errors gracefully while providing feedback to users.*
