"""Exports a page range to an MP3 file, generating whatever audio isn't cached yet."""

import os
import shutil
import tempfile
import wave

from PySide6.QtCore import QObject, QProcess, QTimer, Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog

import imageio_ffmpeg

from .textmodel import ChunkBuilder, find_furniture
from .tts import Job, Synthesizer, has_audio

HEADING_SILENCE_SECONDS = 0.35


class Mp3Export(QObject):
    def __init__(self, api, document, first_page, last_page, voice_id, speed, out_path, cache_dir):
        super().__init__(api.window)
        self.api = api
        self.document = document
        self.first_page = first_page
        self.last_page = last_page
        self.voice_id = voice_id
        self.speed = speed
        self.out_path = out_path
        self.cache_dir = cache_dir
        self.next_page = first_page
        self.builder = ChunkBuilder(document, find_furniture(document))
        self.jobs = []
        self.done = 0
        self.temp_dir = None
        self.finished_ok = False
        self.synth = Synthesizer()
        self.synth.ready.connect(self._on_ready)
        self.synth.failed.connect(lambda _path, error: self._fail(f"Voice problem: {error}"))
        self.synth.progress.connect(lambda text: self.progress.setLabelText(text))
        self.progress = QProgressDialog("Preparing text...", "Cancel", 0, last_page - first_page + 1, api.window)
        self.progress.setWindowTitle("Export MP3")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.canceled.connect(self._cancel)
        self.timer = QTimer(self, interval=0, timeout=self._build_tick)
        self.process = None

    def start(self):
        self.timer.start()

    def _build_tick(self):
        if self.next_page > self.last_page:
            self.timer.stop()
            self._start_audio()
            return
        self.builder.feed(self.next_page)
        self.next_page += 1
        self.progress.setValue(self.next_page - self.first_page)

    def _start_audio(self):
        chunks = self.builder.finish()
        if not chunks:
            self._fail("There's no readable text in those pages.")
            return
        self.chunks = chunks
        self.jobs = [Job(self.cache_dir, self.voice_id, c.text) for c in chunks]
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

    def _write_silence(self, source, path):
        with wave.open(source, "rb") as src:
            channels, width, rate = src.getnchannels(), src.getsampwidth(), src.getframerate()
        with wave.open(path, "wb") as dst:
            dst.setnchannels(channels)
            dst.setsampwidth(width)
            dst.setframerate(rate)
            dst.writeframes(b"\x00" * int(rate * HEADING_SILENCE_SECONDS) * channels * width)

    def _encode(self):
        self.jobs_done = list(self.jobs)
        self.jobs = []
        self.progress.setLabelText("Encoding MP3...")
        self.progress.setRange(0, 0)
        self.temp_dir = tempfile.mkdtemp(prefix="pdfdesk-export-")
        silence = os.path.join(self.temp_dir, "silence.wav")
        self._write_silence(self.jobs_done[0].path, silence)
        listing = os.path.join(self.temp_dir, "files.txt")
        with open(listing, "w", encoding="utf-8") as f:
            for chunk, job in zip(self.chunks, self.jobs_done):
                f.write("file '" + job.path.replace("\\", "/").replace("'", "'\\''") + "'\n")
                if chunk.heading:
                    f.write("file '" + silence.replace("\\", "/").replace("'", "'\\''") + "'\n")
        self.process = QProcess(self)
        self.process.finished.connect(self._on_encoded)
        self.process.errorOccurred.connect(lambda _e: self._fail("The MP3 encoder couldn't be started."))
        self.process.start(
            imageio_ffmpeg.get_ffmpeg_exe(),
            [
                "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", listing,
                "-filter:a", f"atempo={self.speed}",
                "-c:a", "libmp3lame", "-q:a", "2", self.out_path,
            ],
        )

    def _on_encoded(self, code, _status):
        if code != 0:
            error = bytes(self.process.readAllStandardError()).decode("utf-8", "replace")
            self._fail(f"MP3 encoding failed: {error.strip()}")
            return
        self.finished_ok = True
        self._cleanup()
        self.api.status(f"Saved {self.out_path}", 8000)
        QMessageBox.information(self.api.window, "Export MP3", f"Saved:\n{self.out_path}")

    def _cancel(self):
        if self.process and self.process.state() != QProcess.NotRunning:
            self.process.finished.disconnect(self._on_encoded)
            self.process.kill()
            self.process.waitForFinished(2000)
            if os.path.exists(self.out_path):
                os.remove(self.out_path)
        self._cleanup()
        self.api.status("Export canceled.")

    def _fail(self, message):
        self._cleanup()
        QMessageBox.warning(self.api.window, "Export MP3", message)

    def _cleanup(self):
        self.timer.stop()
        self.jobs = []
        self.synth.close()
        self.progress.canceled.disconnect(self._cancel)
        self.progress.close()
        if self.temp_dir:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            self.temp_dir = None
        self.deleteLater()
