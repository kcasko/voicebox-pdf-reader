import ctypes, json, os, queue, re, sys, tempfile, threading, time, urllib.request, winsound
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import fitz

VOICEBOX = "http://127.0.0.1:17493"
READER_PROFILE = "e62bb14c-af38-4cb8-a64a-a337e60909d3"
ENGINE = "kokoro"
VOICE_NAME = "Emma"
CHUNK_CHARS = 700
SETTINGS_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "VoiceboxPDFReader")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")

def api_json(path, method="GET", body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(VOICEBOX + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

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
    text = re.sub(r"-\s*\n\s*", "", text)
    text = re.sub(r"[\u2022\u25AA\u25E6\u25A0\u25CF]+", ". ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def extract_page_chunks(page, limit=CHUNK_CHARS):
    data = page.get_text("dict")
    elements = []
    body_accum = []

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
            spans = [
                span for span in line.get("spans", [])
                if span.get("text", "").strip()
            ]
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

                heading = first_text.replace("\xad", "")
                if heading and heading[-1] not in ".!?":
                    heading += "."
                elements.append((heading, True))

                remainder = " ".join(
                    span.get("text", "").strip()
                    for span in spans[1:]
                    if span.get("text", "").strip()
                ).strip()
                if remainder:
                    body_accum.append(remainder)
            else:
                line_text = " ".join(
                    span.get("text", "").strip()
                    for span in spans
                    if span.get("text", "").strip()
                ).strip()
                if line_text:
                    body_accum.append(line_text)

        flush_body()

    if not elements:
        text = clean_text(page.get_text("text"))
        return [(chunk, False) for chunk in split_text(text, limit)] if text else []

    return elements

def split_text(text, limit=CHUNK_CHARS):
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, current = [], ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        pieces = [sentence[i:i+limit] for i in range(0, len(sentence), limit)] if len(sentence) > limit else [sentence]
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

class App:
    def __init__(self, root, pdf_path=None):
        self.root = root
        self.root.title("Read PDF with Emma")
        self.root.geometry("700x350")
        self.stop_flag = False
        self.current_gid = None
        self.settings = load_settings()

        initial_pdf = pdf_path or self.settings.get("pdf_path", "")
        self.pdf_var = tk.StringVar(value=initial_pdf)
        self.start_var = tk.StringVar(value=str(self.settings.get("start_page", 1)))
        self.end_var = tk.StringVar(value=str(self.settings.get("end_page", "")))
        self.status_var = tk.StringVar(value="Choose a PDF.")
        self.detail_var = tk.StringVar(value=f"Ready. Voice: {VOICE_NAME} ({ENGINE}).")

        frm = ttk.Frame(root, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="PDF").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.pdf_var, width=70).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(3,8))
        ttk.Button(frm, text="Browse", command=self.browse).grid(row=1, column=3, padx=(8,0))

        ttk.Label(frm, text="Start page").grid(row=2, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.start_var, width=10).grid(row=3, column=0, sticky="w")
        ttk.Label(frm, text="End page").grid(row=2, column=1, sticky="w")
        ttk.Entry(frm, textvariable=self.end_var, width=10).grid(row=3, column=1, sticky="w")
        ttk.Button(frm, text="Read with Emma", command=self.start_reading).grid(row=3, column=2, padx=8)
        ttk.Button(frm, text="Stop", command=self.stop).grid(row=3, column=3)

        ttk.Separator(frm).grid(row=4, column=0, columnspan=4, sticky="ew", pady=14)
        ttk.Label(frm, textvariable=self.status_var, wraplength=650).grid(row=5, column=0, columnspan=4, sticky="w")
        ttk.Label(frm, textvariable=self.detail_var, wraplength=650).grid(row=6, column=0, columnspan=4, sticky="w", pady=(5,0))
        self.progress = ttk.Progressbar(frm, mode="determinate")
        self.progress.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(12,0))
        ttk.Label(frm, text="Emma | Kokoro | local Voicebox | settings saved automatically").grid(row=8, column=0, columnspan=4, sticky="w", pady=(12,0))
        frm.columnconfigure(2, weight=1)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        if initial_pdf and os.path.exists(initial_pdf):
            self.load_pdf_info(reset_range=(pdf_path is not None and pdf_path != self.settings.get("pdf_path")))
        else:
            self.status_var.set("Choose a PDF.")

    def persist(self):
        save_settings({
            "pdf_path": self.pdf_var.get(),
            "start_page": self.start_var.get(),
            "end_page": self.end_var.get(),
            "voice": VOICE_NAME,
            "engine": ENGINE
        })

    def on_close(self):
        self.persist()
        self.stop_flag = True
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
        self.root.destroy()

    def browse(self):
        p = filedialog.askopenfilename(filetypes=[("PDF files","*.pdf")])
        if p:
            self.pdf_var.set(p)
            self.load_pdf_info(reset_range=True)
            self.persist()

    def load_pdf_info(self, reset_range=False):
        p = self.pdf_var.get()
        try:
            with fitz.open(p) as doc:
                pages = len(doc)
            if reset_range or not self.end_var.get():
                self.start_var.set("1")
                self.end_var.set(str(pages))
            self.status_var.set(f"{os.path.basename(p)} â€” {pages} pages")
            self.detail_var.set("Choose a page range and click Read with Emma.")
        except Exception as e:
            self.status_var.set(f"Could not open PDF: {e}")

    def stop(self):
        self.stop_flag = True
        if self.current_gid:
            try:
                api_json(f"/generate/{self.current_gid}/cancel", "POST", {})
            except Exception:
                pass
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
        self.status_var.set("Stopping...")
        self.detail_var.set("The current generation is being cancelled.")

    def start_reading(self):
        if not self.pdf_var.get():
            self.browse()
            if not self.pdf_var.get():
                return
        self.persist()
        self.stop_flag = False
        threading.Thread(target=self.read_worker, daemon=True).start()

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

    def read_worker(self):
        pdf = self.pdf_var.get()
        try:
            api_json("/settings/generation", "PUT", {"autoplay_on_generate": False})
            health = api_json("/health")
            if health.get("status") != "healthy":
                raise RuntimeError("Voicebox backend is not healthy.")

            with fitz.open(pdf) as doc:
                total = len(doc)
                start = max(1, int(self.start_var.get() or "1"))
                end = min(total, int(self.end_var.get() or str(total)))
                if start > end:
                    raise ValueError("Start page must be before end page.")

                tasks = []
                page_chunk_counts = {}
                for page_num in range(start, end + 1):
                    chunks = extract_page_chunks(doc[page_num - 1])
                    page_chunk_counts[page_num] = len(chunks)
                    for chunk_idx, (chunk, is_heading) in enumerate(chunks, 1):
                        tasks.append((page_num, chunk_idx, len(chunks), chunk, is_heading))

                total_chunks = len(tasks)
                if total_chunks == 0:
                    raise RuntimeError("No readable text was found in that page range.")

                self.ui(
                    status=f"Prepared pages {start}â€“{end}.",
                    detail=f"{total_chunks} chunks queued. Buffering the first audio...",
                    maximum=total_chunks,
                    progress=0
                )

                audio_queue = queue.Queue(maxsize=3)
                producer_error = []
                produced = {"count": 0}

                def producer():
                    try:
                        for page_num, chunk_idx, chunks_on_page, chunk, is_heading in tasks:
                            if self.stop_flag:
                                break

                            self.ui(
                                detail=f"Buffering ahead: {produced['count']}/{total_chunks} chunks generated."
                            )

                            body = {
                                "profile_id": READER_PROFILE,
                                "text": chunk,
                                "language": "en",
                                "engine": ENGINE,
                                "normalize": True,
                                "max_chunk_chars": CHUNK_CHARS,
                                "crossfade_ms": 50
                            }

                            gen = api_json("/generate", "POST", body)
                            self.current_gid = gen["id"]

                            while not self.stop_flag:
                                hist = api_json(f"/history/{self.current_gid}")
                                if hist["status"] == "completed":
                                    break
                                if hist["status"] == "failed":
                                    raise RuntimeError(
                                        f"Page {page_num}, chunk {chunk_idx}: {hist.get('error')}"
                                    )
                                time.sleep(0.25)

                            if self.stop_flag:
                                break

                            wav = os.path.join(
                                tempfile.gettempdir(),
                                f"voicebox_pdf_{page_num}_{chunk_idx}.wav"
                            )
                            urllib.request.urlretrieve(
                                VOICEBOX + f"/audio/{self.current_gid}", wav
                            )
                            produced["count"] += 1
                            audio_queue.put(
                                (page_num, chunk_idx, chunks_on_page, wav, is_heading)
                            )
                    except Exception as e:
                        producer_error.append(e)
                    finally:
                        audio_queue.put(None)

                producer_thread = threading.Thread(target=producer, daemon=True)
                producer_thread.start()

                done = 0
                last_page = None

                while not self.stop_flag:
                    item = audio_queue.get()
                    if item is None:
                        break

                    page_num, chunk_idx, chunks_on_page, wav, is_heading = item

                    self.ui(
                        status=f"Reading page {page_num}, chunk {chunk_idx}/{chunks_on_page}...",
                        detail=f"{produced['count']}/{total_chunks} chunks generated; {audio_queue.qsize()} buffered ahead.",
                        progress=done + 1
                    )

                    winsound.PlaySound(None, winsound.SND_PURGE)
                    winsound.PlaySound(wav, winsound.SND_FILENAME)
                    done += 1

                    if last_page is not None and page_num != last_page:
                        self.start_var.set(str(page_num))
                        self.root.after(0, self.persist)
                    last_page = page_num

                producer_thread.join(timeout=2)
                self.current_gid = None

                if producer_error:
                    raise producer_error[0]

                if self.stop_flag:
                    self.ui(
                        status="Stopped.",
                        detail=f"{done}/{total_chunks} chunks played."
                    )
                else:
                    self.start_var.set(str(end))
                    self.ui(
                        status=f"Finished pages {start}â€“{end}.",
                        detail=f"{done}/{total_chunks} chunks played.",
                        progress=total_chunks
                    )

                self.root.after(0, self.persist)

        except Exception as e:
            self.current_gid = None
            self.ui(status="Error", detail=str(e))
            self.root.after(
                0,
                lambda: messagebox.showerror("Read PDF with Emma", str(e))
            )

if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".pdf") else None
    root = tk.Tk()
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\VoiceboxPDFReaderEmma")
    if ctypes.windll.kernel32.GetLastError() == 183:
        root.withdraw()
        messagebox.showwarning("Read PDF with Emma", "The PDF reader is already open. Close the other reader window first.")
        root.destroy()
        sys.exit(0)
    app = App(root, pdf)
    root.mainloop()


