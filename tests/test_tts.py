import hashlib
import importlib.util
import os
import sys
import wave

import numpy
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("read_aloud_tts", os.path.join(ROOT, "plugins", "read_aloud", "tts.py"))
tts = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tts
spec.loader.exec_module(tts)


def test_voices_use_the_matching_accent():
    assert tts.language_for("bf_emma") == "en-gb"
    assert tts.language_for("bm_george") == "en-gb"
    assert tts.language_for("af_sarah") == "en-us"
    assert tts.language_for("am_adam") == "en-us"


def test_audio_is_saved_per_voice():
    assert tts.audio_path("c", "bf_emma", "Hello.") != tts.audio_path("c", "af_sarah", "Hello.")


def test_wav_is_normalized_and_readable(tmp_path):
    path = str(tmp_path / "out.wav")
    tts.write_wav(numpy.array([0.0, 0.25, -0.5], dtype=numpy.float32), 24000, path)
    with wave.open(path) as f:
        assert (f.getframerate(), f.getnchannels(), f.getsampwidth()) == (24000, 1, 2)
        samples = numpy.frombuffer(f.readframes(3), dtype=numpy.int16)
    assert abs(samples).max() == pytest.approx(32767 * tts.PEAK_LEVEL, abs=2)


def test_silent_audio_is_an_error(tmp_path):
    with pytest.raises(tts.VoiceError):
        tts.write_wav(numpy.zeros(10, dtype=numpy.float32), 24000, str(tmp_path / "out.wav"))


def _served_file(tmp_path, content):
    source = tmp_path / "server"
    source.mkdir()
    (source / "model.bin").write_bytes(content)
    return source.as_uri() + "/"


def test_model_download_verifies_the_file(tmp_path):
    url = _served_file(tmp_path, b"model data")
    target = tmp_path / "models"
    good = {"model.bin": hashlib.sha256(b"model data").hexdigest()}
    tts.fetch_model(str(target), url, good)
    assert (target / "model.bin").read_bytes() == b"model data"
    # A file that's already there isn't fetched again.
    tts.fetch_model(str(target), "file:///does-not-exist/", good)


def test_damaged_download_leaves_nothing_behind(tmp_path):
    url = _served_file(tmp_path, b"corrupted")
    target = tmp_path / "models"
    with pytest.raises(tts.VoiceError):
        tts.fetch_model(str(target), url, {"model.bin": "0" * 64})
    assert os.listdir(target) == []


def test_failed_download_explains_itself(tmp_path):
    with pytest.raises(tts.VoiceError, match="internet"):
        tts.fetch_model(str(tmp_path), "file:///does-not-exist/", {"model.bin": "0" * 64})
