# Lightweight wrapper around python-vlc to play files and emit Qt-friendly signals.
# Cross-platform: works on Windows, macOS, Linux when libvlc is installed.
# Requires: pip install python-vlc
from PySide6.QtCore import QObject, Signal, QTimer

try:
    import vlc

    HAVE_VLC = True
except Exception:
    vlc = None
    HAVE_VLC = False


class VlcFallbackPlayer(QObject):
    # Signals similar to QMediaPlayer style
    positionChanged = Signal(int)  # ms
    durationChanged = Signal(int)  # ms
    playbackStateChanged = Signal(str)  # 'playing' or 'paused' or 'stopped'
    ended = Signal()

    def __init__(self, parent=None, poll_interval_ms=200):
        super().__init__(parent)
        self.instance = None
        self.player = None
        self._media = None
        self._duration = 0
        self._poll = QTimer(self)
        self._poll.setInterval(poll_interval_ms)
        self._poll.timeout.connect(self._poll_state)
        if HAVE_VLC:
            # Create a single instance to reuse
            try:
                self.instance = vlc.Instance()
            except Exception:
                self.instance = None

    def _ensure_player(self):
        if not HAVE_VLC or self.instance is None:
            raise RuntimeError("python-vlc (libvlc) not available")
        if self.player is None:
            self.player = self.instance.media_player_new()

    def play(self, media_path_or_url: str):
        """
        Start playback of given path or URL. Stops any existing playback first.
        """
        if not HAVE_VLC:
            raise RuntimeError("python-vlc (libvlc) not available")
        self.stop()
        self._ensure_player()
        # Create new media
        self._media = self.instance.media_new(media_path_or_url)
        self.player.set_media(self._media)
        # Try to parse meta/length (it may return -1 until playback)
        try:
            self.player.play()
        except Exception as e:
            raise RuntimeError(f"Failed to start playback: {e}")
        # start polling to pick up duration/position and ended state
        self._poll.start()
        self.playbackStateChanged.emit("playing")

    def pause(self):
        if self.player:
            self.player.pause()
            # playbackStateChanged may be ambiguous; check is_playing
            state = "playing" if self.is_playing() else "paused"
            self.playbackStateChanged.emit(state)

    def resume(self):
        if self.player:
            self.player.play()
            self.playbackStateChanged.emit("playing")

    def stop(self):
        if self.player:
            try:
                self.player.stop()
            except Exception as e:
                print("namaste")  # pass
        self._poll.stop()
        self.playbackStateChanged.emit("stopped")

    def is_playing(self):
        if not self.player:
            return False
        try:
            # returns 1 if playing
            return bool(self.player.is_playing())
        except Exception:
            return False

    def set_position(self, ms: int):
        if self.player:
            try:
                self.player.set_time(int(ms))
            except Exception:
                # fallback: if set_time not supported ignore
                pass

    def position(self) -> int:
        if self.player:
            try:
                t = self.player.get_time()
                return t if t is not None and t >= 0 else 0
            except Exception:
                return 0
        return 0

    def duration(self) -> int:
        if self.player:
            try:
                d = self.player.get_length()
                return d if d is not None and d >= 0 else 0
            except Exception:
                return 0
        return 0

    def set_volume(self, v: float):
        """
        v: 0.0 .. 1.0
        """
        if self.player:
            try:
                vol = max(0, min(100, int(v * 100)))
                self.player.audio_set_volume(vol)
            except Exception:
                pass

    def _poll_state(self):
        """
        Poll position/duration and ended state; emit signals to UI.
        """
        if not self.player:
            return
        try:
            pos = self.position()
            dur = self.duration()
            if dur and dur != self._duration:
                self._duration = dur
                self.durationChanged.emit(dur)
            self.positionChanged.emit(pos)
            # If ended
            # Use player.get_state() to detect VLC Ended status
            try:
                st = self.player.get_state()
                # vlc.State.Ended is an enum; compare by name to avoid import errors if fallback
                if hasattr(vlc, "State") and st == vlc.State.Ended:
                    # stop poll to prevent repeated ended signals
                    self._poll.stop()
                    self.ended.emit()
                # Also emit paused/playing transitions
                if hasattr(vlc, "State"):
                    if st in (vlc.State.Playing,):
                        self.playbackStateChanged.emit("playing")
                    elif st in (vlc.State.Paused,):
                        self.playbackStateChanged.emit("paused")
            except Exception:
                # If we cannot get state, just continue
                pass
        except Exception:
            pass
