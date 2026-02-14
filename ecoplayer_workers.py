import asyncio

import aiohttp
from PySide6.QtCore import QMutex, QThread, Signal


class LocalMetaWorker(QThread):
    """
    Runs local audio metadata extraction off the GUI thread.
    Expects an extractor callable that takes a single file_path arg and
    returns the metadata dict (same structure as get_audio_metadata).
    """

    work_completed = Signal(dict)  # Emits {'retrieved_metadata': metadata}
    work_error = Signal(str)
    work_message = Signal(str)

    def __init__(self, file_path: str, extractor_callable):
        super().__init__()
        self.file_path = file_path
        self.extractor_callable = extractor_callable
        self.mutex = QMutex()

    def run(self):
        try:
            metadata = self.extractor_callable(self.file_path)
            self.work_completed.emit({"retrieved_metadata": metadata})
        except Exception as e:
            self.work_error.emit(str(e))


class Worker(QThread):
    """
    Worker thread for asynchronous remote tasks.
    """

    work_completed = Signal(dict)
    work_error = Signal(str)

    def __init__(self, folder_path, api_url):
        super().__init__()
        self.mutex = QMutex()
        self.folder_path = folder_path
        self.api_url = api_url

    def run(self):
        result = None
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)

            if self.api_url.endswith("scan_library"):
                result = loop.run_until_complete(self.scan_library_async())
            elif self.api_url.endswith("start"):
                result = loop.run_until_complete(self.reveal_remote_song_async())
            elif self.folder_path is None:
                result = loop.run_until_complete(self.get_playlists_async())
            elif isinstance(self.folder_path, dict):
                result = loop.run_until_complete(self.search_async())
            elif isinstance(self.folder_path, tuple):
                result = loop.run_until_complete(self.purge_library_async())
            elif self.folder_path == "meta":
                result = loop.run_until_complete(self.get_metadata_async())
            elif self.folder_path in {"song_title", "artist", "album"}:
                result = loop.run_until_complete(self.get_songs_async())
            elif self.folder_path == "pl":
                result = loop.run_until_complete(self.get_pl_async())
            elif self.folder_path == "server":
                result = loop.run_until_complete(self.check_server_async())
            else:
                raise ValueError(f"Unknown folder_path value: {self.folder_path}")

            self.work_completed.emit(result)

        except Exception as e:
            self.work_error.emit(str(e))
            self.mutex.unlock()
        finally:
            loop.close()

    async def scan_library_async(self):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.api_url, json={"folder_path": self.folder_path}
            ) as response:
                if response.status == 200:
                    return await response.json()
                raise Exception(f"Scan failed: {response.status}")

    async def purge_library_async(self):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.api_url}/purge_library",
                json={"folder_path": self.folder_path[1]},
            ) as response:
                if response.status == 200:
                    return await response.json()
                raise Exception(f"Purge failed: {response.status}")

    async def search_async(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(self.api_url, params=self.folder_path) as response:
                if response.status == 200:
                    search_result = await response.json()
                    return {"search_result": search_result}
                raise Exception(f"Search failed: {response.status}")

    async def get_playlists_async(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.api_url}/get_playlists", timeout=5
            ) as response:
                if response.status == 200:
                    retrieved_playlists = await response.json()
                    return {"retrieved_playlists": retrieved_playlists}
                raise Exception(f"Failed to fetch playlists: {response.status}")

    async def get_songs_async(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                self.api_url, params={"query": self.folder_path}
            ) as response:
                if response.status == 200:
                    retrieved = await response.json()
                    return {"retrieved": retrieved}
                raise Exception(f"Failed to fetch songs: {response.status}")

    async def get_pl_async(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(self.api_url) as response:
                if response.status == 200:
                    retrieved_playlist = await response.json()
                    return {"pl": retrieved_playlist}
                raise Exception(f"Failed to fetch playlist: {response.status}")

    async def get_metadata_async(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(self.api_url) as response:
                if response.status == 200:
                    retrieved_metadata = await response.json()
                    return {"retrieved_metadata": retrieved_metadata}
                if response.status == 404:
                    retrieved_metadata = {
                        "album": "",
                        "artist": "",
                        "codec": "audio/flac 44.1kHz/16bits  860kbps",
                        "duration": 0,
                        "lyrics": "",
                        "picture": None,
                        "title": "Not Found",
                        "year": "",
                    }
                    return {"retrieved_metadata": retrieved_metadata}
                raise Exception(f"Failed to fetch metadata: {response.status}")

    async def check_server_async(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://{self.api_url}:5000", timeout=3
            ) as response:
                if response.status == 200:
                    status = response.status
                    return {"status": status, "API_URL": self.api_url}
                raise Exception(f"Server check failed: {response.status}")

    async def reveal_remote_song_async(self):
        async with aiohttp.ClientSession() as session:
            async with session.post(self.api_url, json=self.folder_path) as response:
                if response.status == 200:
                    answer = await response.json()
                    return {"answer": answer}
                raise Exception(f"Failed to fetch songs: {response.status}")
