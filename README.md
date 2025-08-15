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
  404.html template
  500.html template
   ``` 
### Setup Instructions:

**Create project structure:**
```sh
media_server/
├── ecoserver.py (main application)
├── openfile.py (music folder selector script)
└── templates/
    └── index.html
    └── settings.html
    └── 404.html
    └── 500.html
   ``` 
**Install dependencies:**
```sh
pip install flask mutagen fuzzywuzzy python-levenshtein
   ``` 
**Run the application:**
```sh
python ecoserver.py
   ``` 

**Key Features Implemented:**

- **Smart Menu:** Hides "Scan Library" when not on localhost
- **Audio Metadata:** Extracts artist, title, album, year, duration, and album art
- **Crossfading:** Seamless transition between songs with configurable timing
- **Search:** Both exact and fuzzy string matching
- **Playlist Support:** Parses M3U and PLS files with relative path resolution
- **Database Integration:** Prevents duplicate entries and maintains library state
- **Web Interface:** Clean, responsive interface with all required functionality

### Complete Audio Player Features:
**Core Player Functionality**

- Dual audio element system for seamless crossfading
- Playlist and search-based song selection
- Metadata display with album art support
- Song jumping and playlist navigation

**Advanced Gap Killer System**

- Real-time audio analysis using Web Audio API
- Configurable silence threshold (-60dB to -20dB, default -46dB)
- Adjustable silence duration (0.5s to 5s, default 2s)
- Smart gap detection that monitors audio levels continuously
- Automatic silence skipping with 10-second forward jumps
- Visual status indicators showing current audio levels and gap killer activity

**Professional Features**

- Crossfade transitions between songs
- Race condition prevention with proper state management
- Event listener tracking to prevent memory leaks
- Error handling for audio analysis failures
- Browser compatibility with AudioContext resumption

**User Controls**

- Enable/disable gap killer toggle
- Real-time threshold adjustment slider
- Minimum silence duration control
- Live status monitoring with color-coded feedback

**Gap Killer Features:**

**Controls Panel**

- **Enable/Disable Toggle:** Turn gap killer on/off
- **Silence Threshold Slider:** Adjustable from -60dB to -20dB (default -46dB)
- **Minimum Silence Duration:** Adjustable from 0.5 to 5 seconds (default 2 seconds)
- **Real-time Status Indicator:** Shows current audio levels and gap killer activity

**How It Works**

- **Audio Analysis:** Uses Web Audio API to continuously monitor audio levels in real-time
- **Silence Detection:** Compares audio levels against the -46dB threshold every 100ms
- **Smart Triggering:** Only activates after sustained silence for the specified duration
- **Gap Skipping:** Automatically jumps forward 10 seconds when silence is detected
- **Visual Feedback:** Status indicator shows current audio levels and gap killer activity

**Key Technical Features**

- **Non-intrusive:** Doesn't interfere with crossfading or normal playback
- **Dual Audio Support:** Works with both audio elements during crossfades
- **State Management:** Properly resets when jumping between songs
- **Error Handling:** Gracefully handles Web Audio API initialization issues
- **Real-time Monitoring:** Continuously analyzes audio without affecting performance

**Status Indicators**

- **Green:** "Active - Monitoring audio levels" (normal operation)
- **Yellow:** "Silence detected" or "Silent for X.Xs" (building up to trigger)
- **Dark Green:** "Gap Killer activated - Skipping silence" (actively skipping)
- **Red:** "Disabled" or "Error - Audio analysis unavailable"

The gap killer automatically initializes when you start playing music and provides real-time feedback about audio levels and silence detection. 
It's designed to be completely automatic while giving you full control over sensitivity and timing parameters.
The gap killer will automatically detect when audio drops below -46dB for 2+ seconds and skip forward to find the next audio content, 
making it perfect for removing long silent sections in recordings or live performances. 
The system provides real-time feedback so you can see exactly when it's working and adjust the sensitivity as needed.

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
