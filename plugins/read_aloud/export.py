"""Exports pages to an MP3 file, generating whatever audio isn't cached yet."""

import os
import tempfile
import threading
import wave

import lameenc
from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from .textmodel import ChunkBuilder, find_furniture, pause_after
from .tts import Job, Synthesizer, has_audio

MP3_BIT_RATE = 128
MP3_QUALITY = 2
READ_FRAMES = 65536


def encode_mp3(items, out_path, should_stop=lambda: False):
    """Join (wav path, silence after, in seconds) into one MP3. Returns False if it was stopped."""
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(MP3_BIT_RATE)
    encoder.set_quality(MP3_QUALITY)
    encoder.silence()
    configured = False
    fd, partial = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(out_path)), suffix=".mp3.tmp")
    try:
        with os.fdopen(fd, "wb") as out:
            for path, silence in items:
                if should_stop():
                    return False
                with wave.open(path, "rb") as source:
                    rate, channels, width = source.getframerate(), source.getnchannels(), source.getsampwidth()
                    if not configured:
                        encoder.set_in_sample_rate(rate)
                        encoder.set_channels(channels)
                        configured = True
                    while True:
                        frames = source.readframes(READ_FRAMES)
                        if not frames:
                            break
                        out.write(encoder.encode(frames))
                if silence:
                    out.write(encoder.encode(b"\x00" * int(rate * silence) * channels * width))
            out.write(encoder.flush())
        os.replace(partial, out_path)
        return True
    finally:
        if os.path.exists(partial):
            os.remove(partial)


class Mp3Export(QObject):
    _encoded = Signal(str)  # What went wrong, or empty

    def __init__(self, api, document, pages, voice_id, speed, out_path, cache_dir, skip_references=True):
        super().__init__(api.window)
        self.api = api
        self.document = document
        self.pages = list(pages)
        self.voice_id = voice_id
        self.speed = speed
        self.out_path = out_path
        self.cache_dir = cache_dir
        self.next_page = 0
        self.builder = ChunkBuilder(document, find_furniture(document), skip_references)
        self.jobs = []
        self.done = 0
        self.finished_ok = False
        self._closed = False
        self._stop = threading.Event()
        self.synth = Synthesizer()
        self.synth.ready.connect(self._on_ready)
        self.synth.failed.connect(lambda _path, error: self._fail(f"Voice problem: {error}"))
        self.synth.progress.connect(lambda text: self.progress.setLabelText(text))
        self.progress = QProgressDialog("Preparing text...", "Cancel", 0, len(self.pages), api.window)
        self.progress.setWindowTitle("Export MP3")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.canceled.connect(self._cancel)
        self.timer = QTimer(self, interval=0, timeout=self._build_tick)
        self._encoded.connect(self._on_encoded, Qt.QueuedConnection)

    def start(self):
        self.timer.start()

    def _build_tick(self):
        if self.next_page >= len(self.pages):
            self.timer.stop()
            self._start_audio()
            return
        self.builder.feed(self.pages[self.next_page])
        self.next_page += 1
        self.progress.setValue(self.next_page)

    def _start_audio(self):
        chunks = self.builder.finish()
        if not chunks:
            self._fail("There's no readable text in those pages.")
            return
        self.chunks = chunks
        # Made at the chosen speed, since a voice sounds better saying it that way than being sped up.
        self.jobs = [Job(self.cache_dir, self.voice_id, c.spoken, self.speed) for c in chunks]
        self.progress.setLabelText("Generating voice...")
        self.progress.setRange(0, len(self.jobs))
        self._check_ready()

    def _check_ready(self):
        missing = [job for job in self.jobs if not has_audio(job.path)]
        self.progress.setValue(len(self.jobs) - len(missing))
        if missing:
            self.synth.set_jobs(missing)
        else:
            self.synth.set_jobs([])
            self._encode()

    def _on_ready(self, _path):
        if self.jobs:
            self._check_ready()

    def _encode(self):
        items = [
            (job.path, pause_after(chunk, self.speed))
            for chunk, job in zip(self.chunks, self.jobs)
        ]
        self.jobs = []
        self.progress.setLabelText("Encoding MP3...")
        self.progress.setRange(0, 0)
        threading.Thread(target=self._encode_worker, args=(items,), daemon=True).start()

    def _encode_worker(self, items):
        try:
            encode_mp3(items, self.out_path, self._stop.is_set)
            error = ""
        except Exception as e:
            error = str(e)
        if not self._stop.is_set():
            self._encoded.emit(error)

    def _on_encoded(self, error):
        if self._closed:
            return
        if error:
            self._fail(f"MP3 encoding failed: {error}")
            return
        self.finished_ok = True
        self._cleanup()
        self.api.status(f"Saved {self.out_path}", 8000)
        QMessageBox.information(self.api.window, "Export MP3", f"Saved:\n{self.out_path}")

    def _cancel(self):
        self._stop.set()
        self._cleanup()
        self.api.status("Export canceled.")

    def _fail(self, message):
        if self._closed:
            return
        self._cleanup()
        QMessageBox.warning(self.api.window, "Export MP3", message)

    def _cleanup(self):
        if self._closed:
            return
        self._closed = True
        self.timer.stop()
        self.jobs = []
        self.synth.close()
        self.progress.canceled.disconnect(self._cancel)
        self.progress.close()
        self.deleteLater()
