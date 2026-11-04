"""Playback: decides which sentence is next, keeps audio prepared ahead, and follows along in the page."""

import glob
import os
import shutil
import tempfile
import time

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer

from .textmodel import ChunkBuilder, find_furniture, first_chunk_at
from .tts import VOICES, Job, Synthesizer, has_audio, prune_cache

PREFETCH = 4
BUILD_AHEAD = 40
HEADING_PAUSE_MS = 350
FOLLOW_QUIET_SECONDS = 8
RESUME_PAGE_DISTANCE = 1
EMPTY_PAGES_BEFORE_HINT = 5
NO_TEXT_HINT = "No readable text here. For a scanned PDF, run Tools > Make Searchable (OCR) first."
HIGHLIGHT = QColor(255, 214, 90, 110)
OVERLAY = "read-aloud"
PRIVATE_PREFIX = "private-"


def position_key(document):
    return os.path.normcase(document.path) if document.path else None


class ReadAloudController(QObject):
    state_changed = Signal()
    message = Signal(str)
    now_reading = Signal(str, int)  # sentence and page; empty and -1 when nothing is being read
    resume_offered = Signal(int)  # the page of an earlier place, or -1 when there's nothing to offer

    def __init__(self, api):
        super().__init__()
        self.api = api
        self.cache_dir = os.path.join(api.data_dir, "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        # Left behind if the app was killed while a protected PDF was being read.
        for folder in glob.glob(os.path.join(glob.escape(self.cache_dir), PRIVATE_PREFIX + "*")):
            shutil.rmtree(folder, ignore_errors=True)
        self._private_dir = None
        prune_cache(self.cache_dir)
        self.voice_name = api.settings.get("voice", "Emma")
        if self.voice_name not in VOICES:
            self.voice_name = "Emma"
        speed = api.settings.get("speed", 1.0)
        self.speed = float(speed) if isinstance(speed, (int, float)) and 0.25 <= speed <= 4 else 1.0
        self.follow = bool(api.settings.get("follow", True))
        self.skip_references = bool(api.settings.get("skip_references", True))
        self._partial = False
        self._offer = None
        self.state = "idle"  # idle, waiting, playing, paused
        self.document = None
        self.chunks = []
        self.index = 0
        self._builder = None
        self._next_page = 0
        self._last_page = None
        self._built_all = True
        self._furniture = {}
        self._seek = None
        self._selection_only = False

        self.synth = Synthesizer()
        self.synth.ready.connect(self._on_audio_ready)
        self.synth.failed.connect(self._on_audio_failed)
        self.synth.progress.connect(self.message)
        self.audio = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio)
        if hasattr(self.player, "setPitchCompensation"):
            self.player.setPitchCompensation(True)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.player.errorOccurred.connect(self._on_player_error)
        self._devices = QMediaDevices(self)
        self._devices.audioOutputsChanged.connect(self._on_outputs_changed)
        self._build_timer = QTimer(self, interval=0, timeout=self._build_tick)
        self._pause_timer = QTimer(self, singleShot=True, timeout=self._advance)

    def shutdown(self):
        self.stop()
        self.synth.close()
        self._remove_private_audio()

    def _on_outputs_changed(self):
        # Unplugged headphones would otherwise leave the audio going nowhere.
        self.audio.setDevice(QMediaDevices.defaultAudioOutput())

    # Where audio is kept
    def cache_for(self, document):
        """Audio of a protected PDF lives only until it closes, in a folder of its own."""
        if not document.is_protected:
            return self.cache_dir
        if self._private_dir is None or not os.path.isdir(self._private_dir):
            self._private_dir = tempfile.mkdtemp(prefix=PRIVATE_PREFIX, dir=self.cache_dir)
        return self._private_dir

    def _remove_private_audio(self):
        if self._private_dir:
            self.player.setSource(QUrl())
            shutil.rmtree(self._private_dir, ignore_errors=True)
            self._private_dir = None

    def clear_saved_data(self):
        """Forget all saved audio and reading places."""
        self.stop()
        self._remove_private_audio()
        for path in glob.glob(os.path.join(glob.escape(self.cache_dir), "*.wav")):
            try:
                os.remove(path)
            except OSError:
                pass
        self.api.settings.pop("positions", None)
        self.api.save_settings()
        self._offer_resume(None)

    # Commands
    def toggle(self):
        view = self.api.current_view()
        if self.state != "idle" and view and view.document is not self.document:
            # F5 is about the PDF in front of you, not one reading in a hidden tab.
            self._save_position()
            self.play_saved_or_current()
            return
        if self.state == "playing":
            self.pause()
        elif self.state == "paused":
            self.resume()
        elif self.state == "waiting":
            self.pause()
        else:
            self.play_saved_or_current()

    def play_saved_or_current(self):
        view = self.api.current_view()
        if not view:
            self.message.emit("Open a PDF first.")
            return
        saved = self._saved_position(view.document)
        if saved and abs(saved[0] - view.current_page) <= RESUME_PAGE_DISTANCE:
            self.read_from(view.document, saved[0], saved[1])
        else:
            # You've moved on from the saved place, so read what's on screen and offer the way back.
            self.read_from(view.document, view.current_page, 0)
            if saved:
                self._offer_resume((view.document, saved[0], saved[1]))

    def _offer_resume(self, offer):
        self._offer = offer
        self.resume_offered.emit(offer[1] if offer else -1)

    def resume_offer(self):
        if self._offer:
            document, page, word = self._offer
            self.read_from(document, page, word)

    def read_from(self, document, page, word=0, last_page=None):
        self.stop()
        self._offer_resume(None)
        prune_cache(self.cache_dir)
        self.document = document
        self.chunks = []
        self.index = 0
        self._last_page = len(document) - 1 if last_page is None else last_page
        # Reading one part of a PDF isn't reading it, so the saved place stays as it was.
        self._partial = self._last_page < len(document) - 1
        self._builder = self._new_builder(document)
        self._next_page = page
        self._built_all = False
        self._seek = (page, word)
        self._set_state("waiting")
        self.message.emit("Preparing text...")
        self._build_timer.start()

    def read_selection(self, view):
        selection = view.selection()
        if not selection:
            return
        (first_page, first_word), (last_page, last_word) = selection
        self.stop()
        self.document = view.document
        self._builder = self._new_builder(view.document)
        for page in range(first_page, last_page + 1):
            self._builder.feed(
                page,
                first_word if page == first_page else 0,
                last_word if page == last_page else None,
            )
        self.chunks = self._builder.finish()
        self._built_all = True
        self._seek = None
        self.index = 0
        self._selection_only = True
        self._set_state("waiting")
        self._pump()

    def pause(self):
        self._pause_timer.stop()
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        self._set_state("paused")
        self.message.emit("Paused.")

    def resume(self):
        if self.player.playbackState() == QMediaPlayer.PausedState:
            self.player.play()
            self._set_state("playing")
            self._announce()
        else:
            self._set_state("waiting")
            self._pump()

    def stop(self):
        self._build_timer.stop()
        self._pause_timer.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        self.synth.set_jobs([])
        self._clear_overlay()
        self._selection_only = False
        self._partial = False
        self.now_reading.emit("", -1)
        self._set_state("idle")

    def next(self):
        self._jump(1)

    def previous(self):
        self._jump(-1)

    def _jump(self, delta):
        if self.state == "idle" or not self.chunks:
            return
        target = self.index + delta
        if target < 0:
            if not self._rewind():
                target = 0
            else:
                return
        elif target >= len(self.chunks) and self._built_all:
            return
        self._move_to(target)

    def _rewind(self):
        """Step back past where reading started by building the earlier page."""
        first = self.chunks[0]
        if first.page == 0 or self._selection_only:
            return False
        page = first.page - 1
        builder = self._new_builder(self.document)
        for index in range(page, first.page + 1):
            builder.feed(index)
        found = first_chunk_at(builder.chunks, first.page, first.word)
        self._builder = builder
        self.chunks = builder.chunks
        self._next_page = first.page + 1
        self._built_all = False
        before = (len(builder.chunks) if found is None else found) - 1
        self._move_to(max(before, 0))
        self._build_timer.start()
        return True

    def _move_to(self, index):
        self._pause_timer.stop()
        self.player.stop()
        self.index = index
        self._set_state("waiting")
        self._pump()

    def set_voice(self, name):
        if name not in VOICES or name == self.voice_name:
            return
        self.voice_name = name
        self.api.settings["voice"] = name
        self.api.save_settings()
        if self.state in ("playing", "waiting"):
            self._move_to(self.index)
        elif self.state == "paused":
            # Resuming must not carry on in the old voice.
            self.player.stop()

    def set_speed(self, speed):
        self.speed = speed
        self.player.setPlaybackRate(speed)
        self.api.settings["speed"] = speed
        self.api.save_settings()

    def set_follow(self, follow):
        self.follow = follow
        self.api.settings["follow"] = follow
        self.api.save_settings()

    def set_skip_references(self, skip):
        self.skip_references = skip
        self.api.settings["skip_references"] = skip
        self.api.save_settings()
        if self.state in ("playing", "waiting") and self.index < len(self.chunks) and not self._selection_only:
            chunk = self.chunks[self.index]
            self.read_from(self.document, chunk.page, chunk.word)

    # Document events
    def on_document_changed(self, document, structural):
        if structural:
            self._furniture.pop(document, None)
            if document is self.document and self.state != "idle":
                self.stop()
                self.message.emit("Stopped because the pages changed.")

    def on_document_closed(self, document):
        self._furniture.pop(document, None)
        if document is self.document:
            self._save_position()
            self.stop()
            self.document = None
        if document.is_protected and not any(v.document.is_protected and v.document is not document for v in self.api.views()):
            self._remove_private_audio()

    def _new_builder(self, document):
        if document not in self._furniture:
            self._furniture[document] = find_furniture(document)
        return ChunkBuilder(document, self._furniture[document], self.skip_references)

    # Text
    def _build_tick(self):
        if self._builder is None or self.document is None:
            self._build_timer.stop()
            return
        if self._next_page > self._last_page:
            self.chunks = self._builder.finish()
            self._built_all = True
            self._build_timer.stop()
            self._after_build()
            return
        if len(self.chunks) - self.index > BUILD_AHEAD and self._seek is None:
            self._build_timer.stop()
            return
        self._builder.feed(self._next_page)
        self.chunks = self._builder.chunks
        self._next_page += 1
        if not self.chunks and self._seek is not None and self._next_page - self._seek[0] == EMPTY_PAGES_BEFORE_HINT:
            # Keep looking, but don't leave someone waiting in silence on a long scanned PDF.
            self.message.emit(NO_TEXT_HINT)
        self._after_build()

    def _after_build(self):
        if self._seek is not None:
            found = first_chunk_at(self.chunks, *self._seek)
            if found is None and not self._built_all:
                return
            self._seek = None
            if found is None:
                if self.chunks:
                    found = len(self.chunks) - 1
                else:
                    self._set_state("idle")
                    self.message.emit(NO_TEXT_HINT)
                    return
            self.index = found
            self._pump()
        elif self.state == "waiting":
            self._pump()
        else:
            self._queue_audio()

    def _resume_building(self):
        if not self._built_all and not self._build_timer.isActive():
            self._build_timer.start()

    # Audio
    def _job(self, chunk):
        return Job(self.cache_for(self.document), VOICES[self.voice_name], chunk.spoken)

    def _queue_audio(self):
        wanted = self.chunks[self.index : self.index + PREFETCH + 1]
        self.synth.set_jobs([self._job(chunk) for chunk in wanted])

    def _pump(self):
        """Play the current sentence if its audio is ready, otherwise wait for it."""
        if self.state != "waiting" or self._seek is not None:
            return
        self._resume_building()
        if self.index >= len(self.chunks):
            if self._built_all:
                self._finished()
            return
        self._queue_audio()
        self._show_chunk()
        path = self._job(self.chunks[self.index]).path
        if not has_audio(path):
            self.message.emit("Generating voice...")
            return
        try:
            os.utime(path)
        except OSError:
            pass
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.setPlaybackRate(self.speed)
        self.player.play()
        self._set_state("playing")
        self._save_position()
        self._announce()

    def _announce(self):
        chunk = self.chunks[self.index]
        total = "" if not self._built_all else f" of {len(self.chunks)}"
        self.message.emit(f"Reading page {chunk.page + 1}, sentence {self.index + 1}{total}.")

    def _on_audio_ready(self, path):
        if self.state == "waiting":
            self._pump()

    def _on_audio_failed(self, path, error):
        if self.state in ("waiting", "playing") and self.index < len(self.chunks):
            # A sentence further ahead failing is only a problem once reading gets there.
            if self._job(self.chunks[self.index]).path == path:
                self.stop()
                self.message.emit(f"Voice problem: {error}")

    def _on_media_status(self, status):
        if status != QMediaPlayer.EndOfMedia or self.state != "playing":
            return
        chunk = self.chunks[self.index]
        if chunk.heading:
            self._pause_timer.start(round(HEADING_PAUSE_MS / max(self.speed, 0.1)))
        else:
            self._advance()

    def _on_player_error(self, _error, text):
        if self.state != "idle":
            self.stop()
            self.message.emit(f"Audio playback problem: {text}")

    def _advance(self):
        if self.state != "playing":
            return
        self.index += 1
        self._set_state("waiting")
        self._pump()

    def _finished(self):
        self._clear_position()
        self.stop()
        self.message.emit("Finished reading.")

    # Follow along
    def _show_chunk(self):
        view = self.api.view_for(self.document)
        if view is None or self.index >= len(self.chunks):
            return
        chunk = self.chunks[self.index]
        self.now_reading.emit(chunk.text, chunk.page)
        view.set_overlay(OVERLAY, chunk.rects, HIGHLIGHT)
        quiet = time.monotonic() - view.last_user_scroll > FOLLOW_QUIET_SECONDS
        if self.follow and quiet and self.api.current_view() is view:
            view.reveal_rect(chunk.page, chunk.rects[chunk.page][0])

    def page_fraction(self):
        """How far through its page the current sentence is, from 0 to 1."""
        if self.index >= len(self.chunks):
            return 0.0
        page = self.chunks[self.index].page
        on_page = [i for i, chunk in enumerate(self.chunks) if chunk.page == page]
        return on_page.index(self.index) / len(on_page)

    def _clear_overlay(self):
        if self.document is not None:
            view = self.api.view_for(self.document)
            if view:
                view.set_overlay(OVERLAY, None)

    # Saved position, kept per PDF
    def _saved_position(self, document):
        key = position_key(document)
        positions = self.api.settings.get("positions")
        saved = positions.get(key) if key and isinstance(positions, dict) else None
        if isinstance(saved, list) and len(saved) == 2 and all(isinstance(n, int) for n in saved) and 0 <= saved[0] < len(document):
            return saved
        return None

    def _save_position(self):
        """Return True if there was a place to save."""
        key = position_key(self.document) if self.document else None
        if key and not self._selection_only and not self._partial and self.index < len(self.chunks):
            chunk = self.chunks[self.index]
            if not isinstance(self.api.settings.get("positions"), dict):
                self.api.settings["positions"] = {}
            self.api.settings["positions"][key] = [chunk.page, chunk.word]
            self.api.save_settings()
            return True
        return False

    def _clear_position(self):
        key = position_key(self.document) if self.document else None
        if key and not self._selection_only and not self._partial:
            self.api.settings.get("positions", {}).pop(key, None)
            self.api.save_settings()

    def _set_state(self, state):
        if state != self.state:
            self.state = state
            self.state_changed.emit()
