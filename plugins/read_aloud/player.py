"""Plays one sentence after another through a single open audio stream.

Starting a new player for each sentence restarts the sound device at every join, which can be heard
as a pop. Here the stream stays open and carries silence between sentences, so a join is just quiet.
"""

import wave

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices, QMediaPlayer

TICK_MS = 15
BUFFER_SECONDS = 0.5
QUEUE_SECONDS = 0.25
SILENCE_QUEUE_SECONDS = 0.05
SAMPLE_BYTES = 2


def _new_sink(audio_format, device):
    return QAudioSink(device, audio_format)


class SentencePlayer(QObject):
    mediaStatusChanged = Signal(object)
    errorOccurred = Signal(object, str)

    def __init__(self, parent=None, sink_factory=_new_sink):
        super().__init__(parent)
        self._sink_factory = sink_factory
        self._device = None
        self._sink = None
        self._io = None
        self._rate = 0
        self._volume = 1.0
        self._source = QUrl()
        self._pcm = b""
        self._offset = 0
        self._written = 0
        self._start_bytes = None
        self._state = QMediaPlayer.StoppedState
        self._speed = 1.0
        self._ended = False
        self._timer = QTimer(self, interval=TICK_MS, timeout=self._tick)

    # Settings
    def setVolume(self, volume):
        self._volume = volume
        if self._sink:
            self._sink.setVolume(volume)

    def setDevice(self, device):
        """Move to another output, such as when headphones are unplugged."""
        self._device = device
        if self._sink:
            remaining = self._pcm[self._offset :]
            self._close_sink()
            self._pcm, self._offset = remaining, 0
            if self._state != QMediaPlayer.StoppedState:
                self._open_sink()

    # The speed is built into the audio, so this only records what was asked for.
    def setPlaybackRate(self, rate):
        self._speed = rate

    def playbackRate(self):
        return self._speed

    # What the rest of the app reads
    def source(self):
        return self._source

    def playbackState(self):
        return self._state

    def position(self):
        """Milliseconds into the current sentence."""
        if self._start_bytes is None or not self._sink or not self._rate:
            return 0
        heard = self._sink.processedUSecs() - self._usecs(self._start_bytes)
        return max(0, heard // 1000)

    def _usecs(self, count):
        return count * 1_000_000 // (self._rate * SAMPLE_BYTES)

    # Commands
    def setSource(self, url):
        self._source = url
        self._pcm, self._offset = b"", 0
        self._start_bytes = None
        self._ended = False
        if url.isEmpty():
            return
        try:
            with wave.open(url.toLocalFile(), "rb") as source:
                rate = source.getframerate()
                if source.getnchannels() != 1 or source.getsampwidth() != SAMPLE_BYTES:
                    raise ValueError("unexpected audio format")
                self._pcm = source.readframes(source.getnframes())
        except (OSError, EOFError, ValueError, wave.Error) as e:
            self.errorOccurred.emit(None, str(e))
            return
        if self._sink and rate != self._rate:
            self._close_sink()
        self._rate = rate

    def play(self):
        if self._state == QMediaPlayer.PausedState and self._sink:
            self._sink.resume()
        elif not self._sink and not self._open_sink():
            return
        self._state = QMediaPlayer.PlayingState
        self._timer.start()

    def pause(self):
        if self._sink:
            self._sink.suspend()
        self._state = QMediaPlayer.PausedState
        self._timer.stop()

    def stop(self):
        self._timer.stop()
        self._close_sink()
        self._pcm, self._offset = b"", 0
        self._start_bytes = None
        self._state = QMediaPlayer.StoppedState

    # The stream
    def _open_sink(self):
        audio_format = QAudioFormat()
        audio_format.setSampleRate(self._rate or 24000)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.Int16)
        device = self._device or QMediaDevices.defaultAudioOutput()
        if device is not None and hasattr(device, "isNull") and device.isNull():
            self.errorOccurred.emit(None, "No sound output was found.")
            return False
        self._rate = audio_format.sampleRate()
        self._sink = self._sink_factory(audio_format, device)
        self._sink.setBufferSize(int(self._rate * SAMPLE_BYTES * BUFFER_SECONDS))
        self._sink.setVolume(self._volume)
        self._io = self._sink.start()
        self._written = 0
        if self._io is None:
            self.errorOccurred.emit(None, "The sound output couldn't be started.")
            self._close_sink()
            return False
        return True

    def _close_sink(self):
        if self._sink:
            self._sink.stop()
        self._sink = self._io = None
        self._written = 0

    def _tick(self):
        if not self._sink:
            return
        speaking = self._offset < len(self._pcm)
        # Keep little silence queued, or the next sentence would have to wait behind it.
        queue = int(self._rate * SAMPLE_BYTES * (QUEUE_SECONDS if speaking else SILENCE_QUEUE_SECONDS))
        played = self._sink.processedUSecs() * self._rate * SAMPLE_BYTES // 1_000_000
        room = min(queue - max(0, self._written - played), self._sink.bytesFree())
        room -= room % SAMPLE_BYTES
        if room > 0:
            if self._offset < len(self._pcm):
                if self._start_bytes is None:
                    self._start_bytes = self._written
                data = self._pcm[self._offset : self._offset + room]
                self._offset += len(data)
            else:
                # Silence keeps the stream open until the next sentence is ready.
                data = bytes(room)
            sent = self._io.write(data)
            self._written += sent if isinstance(sent, int) and sent >= 0 else len(data)
        if self._start_bytes is not None and not self._ended and self._offset >= len(self._pcm):
            if self._sink.processedUSecs() >= self._usecs(self._start_bytes + len(self._pcm)):
                self._ended = True
                self.mediaStatusChanged.emit(QMediaPlayer.EndOfMedia)
