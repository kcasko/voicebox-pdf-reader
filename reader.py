import ctypes
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import fitz

VOICEBOX = "http://127.0.0.1:17493"
CHUNK_CHARS = 700
PREFETCH = 3
HEADING_PAUSE = 0.35
SETTINGS_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "VoiceboxPDFReader")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
CACHE_DIR = os.path.join(SETTINGS_DIR, "cache")
VOICEBOX_EXE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Voicebox", "voicebox.exe")

VOICE_OPTIONS = {
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

SPEED_OPTIONS = ["0.80x", "0.90x", "1.00x", "1.10x", "1.20x", "1.30x", "1.40x", "1.50x"]


def api_json(path, method="GET", body=None, timeout=30):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(VOICEBOX + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw.decode("utf-8")) if raw else {}


def health_ok():
    try:
        return api_json("/health", timeout=2).get("status") == "healthy"
    except Exception:
        return False


def ensure_voicebox():
    if health_ok():
        return
    try:
        if os.path.exists(VOICEBOX_EXE):
            subprocess.Popen([VOICEBOX_EXE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    for _ in range(20):
        if health_ok():
            return
        time.sleep(1)
    # Existing GUI can survive after its backend dies. Restart it once if needed.
    try:
        subprocess.run(["taskkill", "/IM", "voicebox.exe", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        if os.path.exists(VOICEBOX_EXE):
            subprocess.Popen([VOICEBOX_EXE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(20):
            if health_ok():
                return
            time.sleep(1)
    except Exception:
        pass
    raise RuntimeError("Voicebox could not be started. Open Voicebox and try again.")


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(data):
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def clean_text(text):
    text = text.replace("\xad", "")
    text = re.sub(r"-\s*\n\s*", "", text)
    text = re.sub(r"[\u2022\u25AA\u25E6\u25A0\u25CF]+", ". ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_text(text, limit=CHUNK_CHARS):
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, current = [], ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        pieces = [sentence[i:i + limit] for i in range(0, len(sentence), limit)] if len(sentence) > limit else [sentence]
        for piece in pieces:
            candidate = (current + " " + piece).strip()
            if current and len(candidate) > limit:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def extract_page_chunks(page, limit=CHUNK_CHARS):
    data = page.get_text("dict")
    elements = []
    body_accum = []

    def add_body_line(line_text):
        """Join only words broken by PDF line wrapping; preserve normal hyphens."""
        nonlocal body_accum
        line_text = line_text.strip()
        if not line_text:
            return
        if body_accum:
            prev = body_accum[-1]
            # Typical printed-book hyphenation: "bet-" at line end + "ween" next line.
            # Restrict to alphabetic fragments so real forms like "32-bit" stay untouched.
            m_prev = re.search(r"([A-Za-z]{2,})-$", prev)
            m_next = re.match(r"^([a-z]{2,})(.*)$", line_text)
            if m_prev and m_next:
                body_accum[-1] = prev[:-1] + m_next.group(1)
                rest = m_next.group(2).lstrip()
                if rest:
                    body_accum.append(rest)
                return
        body_accum.append(line_text)

    def flush_body():
        nonlocal body_accum
        if body_accum:
            body = clean_text(" ".join(body_accum))
            if body:
                for chunk in split_text(body, limit):
                    elements.append((chunk, False))
            body_accum = []

    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
            if not spans:
                continue

            first = spans[0]
            first_text = clean_text(first.get("text", ""))
            first_font = first.get("font", "")
            first_flags = int(first.get("flags", 0) or 0)

            is_bold_heading = (
                first_text
                and not first_text.isdigit()
                and len(first_text) <= 100
                and any(ch.isalpha() for ch in first_text)
                and ("bold" in first_font.lower() or bool(first_flags & 16))
            )

            if is_bold_heading:
                flush_body()
                heading = first_text
                if heading and heading[-1] not in ".!?":
                    heading += "."
                elements.append((heading, True))

                remainder = " ".join(
                    span.get("text", "").strip()
                    for span in spans[1:]
                    if span.get("text", "").strip()
                ).strip()
                if remainder:
                    add_body_line(remainder)
            else:
                line_text = " ".join(
                    span.get("text", "").strip()
                    for span in spans
                    if span.get("text", "").strip()
                ).strip()
                if line_text:
                    add_body_line(line_text)

        flush_body()

    if not elements:
        text = clean_text(page.get_text("text"))
        return [(chunk, False) for chunk in split_text(text, limit)] if text else []
    return elements


class App:
    def __init__(self, root, pdf_path=None):
        self.root = root
        self.root.title("Read PDF")
        self.root.geometry("820x470")
        self.settings = load_settings()

        self.stop_flag = False
        self.paused = False
        self.current_gid = None
        self.player = None
        self.tasks = []
        self.generated = {}
        self.producer_error = []
        self.current_index = 0
        self.requested_index = None
        self.export_requested = False
        self.condition = threading.Condition()
        self.session_token = 0

        initial_pdf = pdf_path or self.settings.get("pdf_path", "")
        self.pdf_var = tk.StringVar(value=initial_pdf)
        self.start_var = tk.StringVar(value=str(self.settings.get("start_page", 1)))
        self.end_var = tk.StringVar(value=str(self.settings.get("end_page", "")))
        self.voice_var = tk.StringVar(value=self.settings.get("voice", "Emma"))
        self.speed_var = tk.StringVar(value=self.settings.get("speed", "1.00x"))
        self.auto_resume_var = tk.BooleanVar(value=bool(self.settings.get("auto_resume", True)))
        self.status_var = tk.StringVar(value="Choose a PDF.")
        self.detail_var = tk.StringVar(value="Ready.")

        frm = ttk.Frame(root, padding=14)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="PDF").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.pdf_var, width=86).grid(row=1, column=0, columnspan=6, sticky="ew", pady=(3, 8))
        ttk.Button(frm, text="Browse", command=self.browse).grid(row=1, column=6, padx=(8, 0))

        ttk.Label(frm, text="Start page").grid(row=2, column=0, sticky="w")
        ttk.Label(frm, text="End page").grid(row=2, column=1, sticky="w")
        ttk.Label(frm, text="Voice").grid(row=2, column=2, sticky="w")
        ttk.Label(frm, text="Speed").grid(row=2, column=3, sticky="w")

        ttk.Entry(frm, textvariable=self.start_var, width=9).grid(row=3, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.end_var, width=9).grid(row=3, column=1, sticky="w")
        ttk.Combobox(frm, textvariable=self.voice_var, values=list(VOICE_OPTIONS.keys()), state="readonly", width=11).grid(row=3, column=2, sticky="w", padx=(0, 8))
        ttk.Combobox(frm, textvariable=self.speed_var, values=SPEED_OPTIONS, state="readonly", width=8).grid(row=3, column=3, sticky="w")

        ttk.Checkbutton(frm, text="Resume where I stopped", variable=self.auto_resume_var, command=self.persist).grid(row=3, column=4, columnspan=2, sticky="w", padx=(10, 0))

        ttk.Button(frm, text="Read", command=self.start_reading).grid(row=4, column=0, pady=(14, 0), sticky="ew")
        self.pause_btn = ttk.Button(frm, text="Pause", command=self.toggle_pause, state="disabled")
        self.pause_btn.grid(row=4, column=1, pady=(14, 0), padx=4, sticky="ew")
        ttk.Button(frm, text="<< Previous", command=self.previous_chunk).grid(row=4, column=2, pady=(14, 0), padx=4, sticky="ew")
        ttk.Button(frm, text="Next >>", command=self.next_chunk).grid(row=4, column=3, pady=(14, 0), padx=4, sticky="ew")
        ttk.Button(frm, text="Stop", command=self.stop).grid(row=4, column=4, pady=(14, 0), padx=4, sticky="ew")
        ttk.Button(frm, text="Export MP3", command=self.export_audio).grid(row=4, column=5, columnspan=2, pady=(14, 0), sticky="ew")

        ttk.Separator(frm).grid(row=5, column=0, columnspan=7, sticky="ew", pady=14)
        ttk.Label(frm, textvariable=self.status_var, wraplength=770).grid(row=6, column=0, columnspan=7, sticky="w")
        ttk.Label(frm, textvariable=self.detail_var, wraplength=770).grid(row=7, column=0, columnspan=7, sticky="w", pady=(5, 0))
        self.progress = ttk.Progressbar(frm, mode="determinate")
        self.progress.grid(row=8, column=0, columnspan=7, sticky="ew", pady=(12, 0))

        ttk.Label(frm, text="Kokoro | local Voicebox | buffered playback | settings saved automatically").grid(
            row=9, column=0, columnspan=7, sticky="w", pady=(12, 0)
        )

        for col in range(7):
            frm.columnconfigure(col, weight=1)

        self.voice_var.trace_add("write", lambda *_: self.persist())
        self.speed_var.trace_add("write", lambda *_: self.persist())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        if initial_pdf and os.path.exists(initial_pdf):
            self.load_pdf_info(reset_range=(pdf_path is not None and pdf_path != self.settings.get("pdf_path")))
        else:
            self.status_var.set("Choose a PDF.")

    def persist(self, resume_page=None, resume_chunk=None):
        data = {
            "pdf_path": self.pdf_var.get(),
            "start_page": self.start_var.get(),
            "end_page": self.end_var.get(),
            "voice": self.voice_var.get(),
            "speed": self.speed_var.get(),
            "auto_resume": self.auto_resume_var.get(),
            "resume_page": self.settings.get("resume_page"),
            "resume_chunk": self.settings.get("resume_chunk"),
        }
        if resume_page is not None:
            data["resume_page"] = int(resume_page)
        if resume_chunk is not None:
            data["resume_chunk"] = int(resume_chunk)
        self.settings = data
        save_settings(data)

    def on_close(self):
        self.persist_current_position()
        self.stop_flag = True
        self.terminate_player()
        self.root.destroy()

    def browse(self):
        p = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if p:
            changed = os.path.normcase(p) != os.path.normcase(self.pdf_var.get() or "")
            self.pdf_var.set(p)
            self.load_pdf_info(reset_range=True)
            if changed:
                self.settings["resume_page"] = None
                self.settings["resume_chunk"] = None
            self.persist()

    def load_pdf_info(self, reset_range=False):
        p = self.pdf_var.get()
        try:
            with fitz.open(p) as doc:
                pages = len(doc)
            if reset_range or not self.end_var.get():
                self.start_var.set("1")
                self.end_var.set(str(pages))
            self.status_var.set(f"{os.path.basename(p)} - {pages} pages")
            rp = self.settings.get("resume_page")
            rc = self.settings.get("resume_chunk")
            if self.auto_resume_var.get() and rp:
                self.detail_var.set(f"Saved position: page {rp}, chunk {rc or 1}.")
            else:
                self.detail_var.set("Choose a page range and click Read.")
        except Exception as e:
            self.status_var.set(f"Could not open PDF: {e}")

    def ensure_profile(self):
        ensure_voicebox()
        api_json("/settings/generation", "PUT", {"autoplay_on_generate": False})
        voice_name = self.voice_var.get()
        voice_id = VOICE_OPTIONS.get(voice_name, "bf_emma")
        profiles = api_json("/profiles")
        if isinstance(profiles, dict):
            profiles = profiles.get("items", [])
        for profile in profiles:
            if profile.get("preset_engine") == "kokoro" and profile.get("preset_voice_id") == voice_id:
                return profile["id"]
        body = {
            "name": f"{voice_name} - PDF Reader",
            "description": f"PDF reader voice using Kokoro {voice_name}",
            "language": "en",
            "voice_type": "preset",
            "preset_engine": "kokoro",
            "preset_voice_id": voice_id,
            "default_engine": "kokoro",
        }
        profile = api_json("/profiles", "POST", body)
        return profile["id"]

    def build_tasks(self):
        pdf = self.pdf_var.get()
        with fitz.open(pdf) as doc:
            total = len(doc)
            start = max(1, int(self.start_var.get() or "1"))
            end = min(total, int(self.end_var.get() or str(total)))
            if start > end:
                raise ValueError("Start page must be before end page.")
            tasks = []
            for page_num in range(start, end + 1):
                chunks = extract_page_chunks(doc[page_num - 1])
                for chunk_idx, (chunk, is_heading) in enumerate(chunks, 1):
                    tasks.append({
                        "page": page_num,
                        "chunk": chunk_idx,
                        "chunks_on_page": len(chunks),
                        "text": chunk,
                        "heading": is_heading,
                    })
        return tasks, start, end

    def resume_index_for_tasks(self, tasks):
        if not self.auto_resume_var.get():
            return 0
        rp = self.settings.get("resume_page")
        rc = self.settings.get("resume_chunk")
        if not rp:
            return 0
        for i, task in enumerate(tasks):
            if task["page"] == int(rp) and task["chunk"] == int(rc or 1):
                return i
        return 0

    def cache_path(self, task, voice_name):
        os.makedirs(CACHE_DIR, exist_ok=True)
        key = hashlib.sha1(
            f'{voice_name}|{task["page"]}|{task["chunk"]}|{task["text"]}'.encode("utf-8")
        ).hexdigest()
        return os.path.join(CACHE_DIR, key + ".wav")

    def start_reading(self):
        if not self.pdf_var.get():
            self.browse()
            if not self.pdf_var.get():
                return
        if self.player and self.player.poll() is None:
            return
        self.stop_flag = False
        self.paused = False
        self.pause_btn.configure(text="Pause", state="normal")
        self.session_token += 1
        token = self.session_token
        threading.Thread(target=self.read_worker, args=(token,), daemon=True).start()

    def read_worker(self, token):
        try:
            profile_id = self.ensure_profile()
            tasks, start, end = self.build_tasks()
            if not tasks:
                raise RuntimeError("No readable text was found in that page range.")

            self.tasks = tasks
            self.generated = {}
            self.producer_error = []
            self.export_requested = False
            self.current_index = self.resume_index_for_tasks(tasks)
            self.requested_index = None

            self.ui(
                status=f"Prepared pages {start}-{end}.",
                detail=f"{len(tasks)} chunks. Starting at page {tasks[self.current_index]['page']}, chunk {tasks[self.current_index]['chunk']}.",
                maximum=len(tasks),
                progress=self.current_index,
            )

            producer = threading.Thread(
                target=self.producer_worker,
                args=(token, profile_id),
                daemon=True,
            )
            producer.start()

            idx = self.current_index
            while idx < len(tasks) and not self.stop_flag and token == self.session_token:
                with self.condition:
                    self.current_index = idx
                    self.condition.notify_all()
                    while idx not in self.generated and not self.producer_error and not self.stop_flag:
                        self.condition.wait(timeout=0.5)

                if self.stop_flag or token != self.session_token:
                    break
                if self.producer_error:
                    raise self.producer_error[0]

                with self.condition:
                    if self.requested_index is not None:
                        idx = max(0, min(len(tasks) - 1, self.requested_index))
                        self.requested_index = None
                        continue

                task = tasks[idx]
                wav = self.generated[idx]
                self.persist(resume_page=task["page"], resume_chunk=task["chunk"])

                buffered = sum(1 for j in range(idx + 1, min(len(tasks), idx + PREFETCH + 2)) if j in self.generated)
                self.ui(
                    status=f'Reading page {task["page"]}, chunk {task["chunk"]}/{task["chunks_on_page"]}...',
                    detail=f'{len(self.generated)}/{len(tasks)} chunks generated; {buffered} buffered ahead. Voice: {self.voice_var.get()} at {self.speed_var.get()}.',
                    progress=idx + 1,
                )

                self.play_file(wav)

                if self.stop_flag or token != self.session_token:
                    break

                with self.condition:
                    if self.requested_index is not None:
                        idx = max(0, min(len(tasks) - 1, self.requested_index))
                        self.requested_index = None
                        continue

                if task["heading"]:
                    end_pause = time.time() + HEADING_PAUSE
                    while time.time() < end_pause and not self.stop_flag:
                        with self.condition:
                            if self.requested_index is not None:
                                break
                        time.sleep(0.03)

                with self.condition:
                    if self.requested_index is not None:
                        idx = max(0, min(len(tasks) - 1, self.requested_index))
                        self.requested_index = None
                    else:
                        idx += 1

                if idx < len(tasks):
                    nxt = tasks[idx]
                    self.persist(resume_page=nxt["page"], resume_chunk=nxt["chunk"])

            self.root.after(0, lambda: self.pause_btn.configure(state="disabled"))
            self.paused = False

            if not self.stop_flag and idx >= len(tasks):
                last = tasks[-1]
                self.persist(resume_page=last["page"], resume_chunk=last["chunk"])
                self.ui(
                    status=f"Finished pages {start}-{end}.",
                    detail=f"{len(tasks)} chunks played. You can export the range to MP3.",
                    progress=len(tasks),
                )
        except Exception as e:
            self.root.after(0, lambda: self.pause_btn.configure(state="disabled"))
            self.ui(status="Error", detail=str(e))
            self.root.after(0, lambda msg=str(e): messagebox.showerror("Read PDF", msg))

    def producer_worker(self, token, profile_id):
        idx = self.current_index
        try:
            while idx < len(self.tasks) and not self.stop_flag and token == self.session_token:
                with self.condition:
                    while (
                        idx > self.current_index + PREFETCH
                        and not self.export_requested
                        and not self.stop_flag
                    ):
                        self.condition.wait(timeout=0.5)
                if self.stop_flag or token != self.session_token:
                    break

                task = self.tasks[idx]
                wav = self.cache_path(task, self.voice_var.get())
                if not os.path.exists(wav) or os.path.getsize(wav) < 1000:
                    body = {
                        "profile_id": profile_id,
                        "text": task["text"],
                        "language": "en",
                        "engine": "kokoro",
                        "normalize": True,
                        "max_chunk_chars": CHUNK_CHARS,
                        "crossfade_ms": 50,
                    }
                    gen = api_json("/generate", "POST", body)
                    self.current_gid = gen["id"]
                    while not self.stop_flag:
                        hist = api_json(f"/history/{self.current_gid}")
                        if hist["status"] == "completed":
                            break
                        if hist["status"] == "failed":
                            raise RuntimeError(
                                f'Page {task["page"]}, chunk {task["chunk"]}: {hist.get("error")}'
                            )
                        time.sleep(0.2)
                    if self.stop_flag:
                        break
                    urllib.request.urlretrieve(VOICEBOX + f"/audio/{self.current_gid}", wav)

                with self.condition:
                    self.generated[idx] = wav
                    self.condition.notify_all()
                idx += 1
        except Exception as e:
            with self.condition:
                self.producer_error.append(e)
                self.condition.notify_all()

    def speed_value(self):
        try:
            return float(self.speed_var.get().lower().replace("x", ""))
        except Exception:
            return 1.0

    def play_file(self, wav):
        self.terminate_player()
        speed = self.speed_value()
        cmd = [
            "ffplay",
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "quiet",
            "-af",
            f"atempo={speed}",
            wav,
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.player = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self.paused = False
        self.root.after(0, lambda: self.pause_btn.configure(text="Pause"))
        self.player.wait()
        self.player = None

    def toggle_pause(self):
        if not self.player or self.player.poll() is not None or not self.player.stdin:
            return
        try:
            self.player.stdin.write(b"p\n")
            self.player.stdin.flush()
            self.paused = not self.paused
            self.pause_btn.configure(text="Resume" if self.paused else "Pause")
            self.detail_var.set("Paused." if self.paused else "Resumed.")
        except Exception:
            pass

    def terminate_player(self):
        p = self.player
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=1)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        self.player = None

    def request_jump(self, delta):
        if not self.tasks:
            return
        with self.condition:
            target = max(0, min(len(self.tasks) - 1, self.current_index + delta))
            self.requested_index = target
            self.current_index = target
            self.condition.notify_all()
        self.terminate_player()
        task = self.tasks[target]
        self.persist(resume_page=task["page"], resume_chunk=task["chunk"])
        self.ui(
            status=f'Jumping to page {task["page"]}, chunk {task["chunk"]}/{task["chunks_on_page"]}...',
            detail="Waiting for audio if it is not buffered yet.",
            progress=target + 1,
        )

    def previous_chunk(self):
        self.request_jump(-1)

    def next_chunk(self):
        self.request_jump(1)

    def persist_current_position(self):
        if self.tasks and 0 <= self.current_index < len(self.tasks):
            task = self.tasks[self.current_index]
            self.persist(resume_page=task["page"], resume_chunk=task["chunk"])
        else:
            self.persist()

    def stop(self):
        self.persist_current_position()
        self.stop_flag = True
        self.paused = False
        self.pause_btn.configure(text="Pause", state="disabled")
        self.terminate_player()
        if self.current_gid:
            try:
                api_json(f"/generate/{self.current_gid}/cancel", "POST", {})
            except Exception:
                pass
        with self.condition:
            self.condition.notify_all()
        self.status_var.set("Stopped.")
        self.detail_var.set("Your exact page/chunk position was saved.")

    def export_audio(self):
        if not self.tasks:
            messagebox.showinfo("Export MP3", "Start the reader first so the selected page range is prepared.")
            return
        out = filedialog.asksaveasfilename(
            defaultextension=".mp3",
            filetypes=[("MP3 audio", "*.mp3")],
            initialfile="PDF_Reading.mp3",
        )
        if not out:
            return
        self.export_requested = True
        with self.condition:
            self.condition.notify_all()
        threading.Thread(target=self.export_worker, args=(out,), daemon=True).start()

    def export_worker(self, out):
        try:
            self.ui(detail="Preparing the full selected range for MP3 export...")
            while not self.stop_flag:
                with self.condition:
                    if self.producer_error:
                        raise self.producer_error[0]
                    if len(self.generated) >= len(self.tasks):
                        break
                    self.condition.wait(timeout=0.5)
            if self.stop_flag:
                return

            ordered = [self.generated[i] for i in range(len(self.tasks))]
            silence = os.path.join(CACHE_DIR, "heading_pause.wav")
            if not os.path.exists(silence):
                with wave.open(ordered[0], "rb") as src:
                    channels = src.getnchannels()
                    width = src.getsampwidth()
                    rate = src.getframerate()
                with wave.open(silence, "wb") as dst:
                    dst.setnchannels(channels)
                    dst.setsampwidth(width)
                    dst.setframerate(rate)
                    dst.writeframes(b"\x00" * int(rate * HEADING_PAUSE) * channels * width)

            concat_file = os.path.join(tempfile.gettempdir(), "voicebox_pdf_concat.txt")
            with open(concat_file, "w", encoding="utf-8") as f:
                for i, wav_path in enumerate(ordered):
                    safe = wav_path.replace("'", "'\\''")
                    f.write(f"file '{safe}'\n")
                    if self.tasks[i]["heading"]:
                        safe_silence = silence.replace("'", "'\\''")
                        f.write(f"file '{safe_silence}'\n")

            speed = self.speed_value()
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", concat_file,
                "-filter:a", f"atempo={speed}",
                "-c:a", "libmp3lame", "-q:a", "2", out,
            ]
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(cmd, check=True, creationflags=creationflags)
            self.ui(detail=f"Export complete: {out}")
            self.root.after(0, lambda: messagebox.showinfo("Export MP3", f"Saved:\n{out}"))
        except Exception as e:
            self.root.after(0, lambda msg=str(e): messagebox.showerror("Export MP3", msg))

    def ui(self, status=None, detail=None, progress=None, maximum=None):
        def apply():
            if status is not None:
                self.status_var.set(status)
            if detail is not None:
                self.detail_var.set(detail)
            if maximum is not None:
                self.progress.configure(maximum=maximum)
            if progress is not None:
                self.progress.configure(value=progress)
        self.root.after(0, apply)


if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".pdf") else None
    root = tk.Tk()
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\VoiceboxPDFReader")
    if ctypes.windll.kernel32.GetLastError() == 183:
        root.withdraw()
        messagebox.showwarning("Read PDF", "The PDF reader is already open. Close the other reader window first.")
        root.destroy()
        sys.exit(0)
    app = App(root, pdf)
    root.mainloop()
