import os
import sqlite3
from pathlib import Path

APP_DIR = Path.home() / "Web-Media-Server-and-Player"
APP_DIR.mkdir(exist_ok=True)
SETTINGS_FILE = APP_DIR / "settings.json"
DB_PATH = APP_DIR / "music.db"
COVERS_DB_PATH = APP_DIR / "covers.db"


bad_pls = [
    ".NFO.m3u",
    "00. play.m3u",
    "00.info.m3u",
    "CD 1.m3u",
    "CD1.cuetools.flac.cue",
    "CD1.m3u8",
    "CD2.cd2.cuetools.flac.m3u",
    "CD2.m3u",
    "CD2.m3u8",
    "CD3.m3u8",
    "CD4.m3u8",
    "CDImage.ape.cue",
    "CDImage.cue",
    "CDImage.m3u",
    "Cd 1.m3u8",
    "Cd No1.m3u8",
    "Cd No2.m3u8",
    "Play.m3u",
    "Playlist.m3u",
    "Unknown Artist - Unknown Title.cue",
    "Unknown Artist - Unknown Title.m3u",
    "Unknown Artist - Unknown Title.m3u8",
    "Use This To Burn.cue",
    "Use This To Burn.m3u",
    "cue (Disc 1).CUE",
    "cue (Disc 2).CUE",
    "flac.cue",
    "flac.m3u",
    "image.cue",
    "play.m3u",
    "playlist.m3u",
    "CUE+APE.cue",
]

bad_dirs = []
pattern = [
    "disc *",
    "cd*",
    "cd *",
    "disk *",
    "part *",
    "volume *",
    "cd0*",
    "cd 0*",
    "cd no*",
    "cue+ape",
]
for n in range(1, 7):
    for p in pattern:
        bad_dirs.append(p.replace("*", str(n)))
bad_dirs = list(set(bad_dirs))


try:
    print("Renaming bad playlist paths...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Populate the column for each song
    cursor.execute("SELECT id, path, PL_name FROM Playlists")
    rows = cursor.fetchall()
    renamed = 0
    for row in rows:
        song_id, pl_path, pl_name = row
        try:
            if pl_name in bad_pls and pl_path and os.path.exists(pl_path):
                path = os.path.abspath(pl_path)
                #   file_path = os.path.join(root, file)
                pl_ext = Path(path).suffix.lower()
                new_name = path.split("\\")[-2]
                if new_name.lower() in bad_dirs:
                    new_name = path.split("\\")[-3] + " - " + new_name
                new_name += pl_ext
                new_path = os.path.join(os.path.dirname(path), new_name)
                os.rename(pl_path, new_path)
                cursor.execute(
                    "UPDATE Playlists SET path = ?, PL_name = ? WHERE id = ?",
                    (new_path, new_name, song_id),
                )
                print(new_path)
                #  os.rename(pl_path, path.parent.absolute())
                renamed += 1
        except Exception as e:
            print(f"ERROR: Error renaming {pl_path}: {e}")
    conn.commit()
    conn.close()
    print(f"Rename complete. Renamed {renamed} playlists and their db records.")
except Exception as e:
    print(f"ERROR: Rename failed: {e}")
