"""Built-in Kokoro voices, and a background worker that turns text into audio files."""

import ctypes
import hashlib
import os
import sys
import threading
import urllib.request
import wave

from PySide6.QtCore import QObject, Signal

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
MODEL_FILES = {
    "kokoro-v1.0.onnx": "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}
DOWNLOAD_BLOCK = 1024 * 1024
PEAK_LEVEL = 0.95
CACHE_LIMIT_BYTES = 2 * 1024**3

VOICES = {
    "Emma": "bf_emma",
    "Sarah": "af_sarah",
    "Nicole": "af_nicole",
    "Alice": "bf_alice",
    "Isabella": "bf_isabella",
    "Lily": "bf_lily",
    "Bella": "af_bella",
    "Heart": "af_heart",
    "Nova": "af_nova",
    "Sky": "af_sky",
    "Jessica": "af_jessica",
    "Michael": "am_michael",
    "Daniel": "bm_daniel",
    "George": "bm_george",
    "Lewis": "bm_lewis",
    "Adam": "am_adam",
    "Liam": "am_liam",
}


class VoiceError(Exception):
    pass


def language_for(voice_id):
    return "en-gb" if voice_id.startswith("b") else "en-us"


def fetch_model(folder=MODEL_DIR, base_url=MODEL_URL, files=MODEL_FILES, on_progress=None):
    """Download any missing model file. Only needed the first time on a new machine."""
    os.makedirs(folder, exist_ok=True)
    for name, expected in files.items():
        path = os.path.join(folder, name)
        if os.path.exists(path):
            continue
        partial = path + ".part"
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(base_url + name, timeout=60) as response, open(partial, "wb") as out:
                total = int(response.headers.get("Content-Length") or 0)
                received = 0
                while True:
                    block = response.read(DOWNLOAD_BLOCK)
                    if not block:
                        break
                    out.write(block)
                    digest.update(block)
                    received += len(block)
                    if on_progress and total:
                        on_progress(f"Downloading the voices, one time only: {name}, {received * 100 // total}%")
            if digest.hexdigest() != expected:
                raise VoiceError(f"The download of {name} was damaged. Try again.")
            os.replace(partial, path)
        except OSError as e:
            raise VoiceError(f"Couldn't download the voices. This needs internet the first time. ({e})") from e
        finally:
            if os.path.exists(partial):
                os.remove(partial)


_engine = None
_engine_lock = threading.Lock()


def voice_threads():
    """How many CPU threads the voices should use: one per core this process may run on."""
    total = os.cpu_count() or 1
    allowed = total
    if sys.platform == "win32":
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.GetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
        process_mask, system_mask = ctypes.c_size_t(), ctypes.c_size_t()
        if kernel.GetProcessAffinityMask(kernel.GetCurrentProcess(), ctypes.byref(process_mask), ctypes.byref(system_mask)):
            allowed = bin(process_mask.value).count("1") or total
    # Most CPUs show two logical processors per core, and sharing a core doesn't speed the voices up.
    return allowed if allowed < total else max(1, total // 2)


def _load_engine(on_progress):
    global _engine
    if _engine is None:
        fetch_model(on_progress=on_progress)
        on_progress("Loading the voices...")
        # Imported here so the app still opens instantly.
        import onnxruntime
        from kokoro_onnx import Kokoro

        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = voice_threads()
        options.inter_op_num_threads = 1
        # Busy-waiting between sentences wastes battery and fights the rest of the app for the CPU.
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        session = onnxruntime.InferenceSession(
            os.path.join(MODEL_DIR, "kokoro-v1.0.onnx"), options, providers=["CPUExecutionProvider"]
        )
        _engine = Kokoro.from_session(session, os.path.join(MODEL_DIR, "voices-v1.0.bin"))
    return _engine


def write_wav(samples, rate, path):
    """Save float samples as 16-bit audio at a consistent volume."""
    import numpy

    peak = float(numpy.abs(samples).max()) if len(samples) else 0.0
    if peak <= 0:
        raise VoiceError("No audio was generated for this text.")
    scaled = numpy.clip(samples * (PEAK_LEVEL / peak), -1.0, 1.0)
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((scaled * 32767).astype(numpy.int16).tobytes())


def audio_path(cache_dir, voice_id, text):
    key = hashlib.sha1(f"{voice_id}|{text}".encode("utf-8")).hexdigest()
    return os.path.join(cache_dir, key + ".wav")


def has_audio(path):
    return os.path.exists(path) and os.path.getsize(path) > 1000


def prune_cache(cache_dir, limit=CACHE_LIMIT_BYTES):
    """Delete the least recently used audio once the cache passes its size limit."""
    entries = []
    for entry in os.scandir(cache_dir):
        if entry.name.endswith(".wav"):
            info = entry.stat()
            entries.append((info.st_mtime, info.st_size, entry.path))
    total = sum(size for _, size, _ in entries)
    for _, size, path in sorted(entries):
        if total <= limit:
            break
        try:
            os.remove(path)
            total -= size
        except OSError:
            pass


class Job:
    __slots__ = ("path", "voice_id", "text")

    def __init__(self, cache_dir, voice_id, text):
        self.path = audio_path(cache_dir, voice_id, text)
        self.voice_id = voice_id
        self.text = text


class Synthesizer(QObject):
    """Works through the wanted list in order; replacing the list redirects it right away."""

    ready = Signal(str)
    failed = Signal(str, str)
    progress = Signal(str)

    def __init__(self):
        super().__init__()
        self._condition = threading.Condition()
        self._jobs = []
        self._closed = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_jobs(self, jobs):
        with self._condition:
            self._jobs = list(jobs)
            self._condition.notify_all()

    def close(self):
        with self._condition:
            self._closed = True
            self._jobs = []
            self._condition.notify_all()

    def _next_job(self):
        with self._condition:
            while not self._closed:
                for job in self._jobs:
                    if not has_audio(job.path):
                        return job
                self._condition.wait()
        return None

    def _emit(self, signal, *args):
        try:
            signal.emit(*args)
        except RuntimeError:
            pass  # The plugin was turned off while this was in flight.

    def _run(self):
        while True:
            job = self._next_job()
            if job is None:
                return
            try:
                self._generate(job)
                self._emit(self.ready, job.path)
            except Exception as e:
                # Drop it so the worker doesn't retry forever; the controller decides what's next.
                with self._condition:
                    self._jobs = [j for j in self._jobs if j.path != job.path]
                self._emit(self.failed, job.path, str(e))

    def _generate(self, job):
        # One engine is shared with MP3 export, and it handles one sentence at a time.
        with _engine_lock:
            if has_audio(job.path):
                return
            engine = _load_engine(lambda text: self._emit(self.progress, text))
            samples, rate = engine.create(job.text, voice=job.voice_id, speed=1.0, lang=language_for(job.voice_id))
            partial = job.path + ".part"
            write_wav(samples, rate, partial)
            os.replace(partial, job.path)
