import sqlite3
from PIL import Image
from io import BytesIO
import base64


size = 256, 256
results = None

try:
    conn = sqlite3.connect('Art.db')
    cursor = conn.cursor()
    cursor.execute("SELECT album, cover FROM Covers GROUP BY album")
    results = cursor.fetchall()
    conn.commit()
    conn.close()
except sqlite3.Error as e:
    print(f"Database error getting Albums from database: {str(e)}")

except Exception as e:
    print(f"Unexpected error getting Albums from database: {str(e)}")


conn = sqlite3.connect('Covers.db')
cursor = conn.cursor()

# Create Album Art table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS Covers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        album CHAR(120) NOT NULL,
        cover TEXT
    )
''')
print("Database initialized successfully")

if results:
    for result in results:
        album = result[0]
        img = result[1]
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

conn.commit()
conn.close()
print("Covers Database updated successfully")

