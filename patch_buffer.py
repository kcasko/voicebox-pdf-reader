from pathlib import Path

p = Path(r"D:\Repos\voicebox-pdf-reader\reader.py")
s = p.read_text(encoding="utf-8")
s = s.replace("import ctypes, json, os, re, sys, tempfile, threading, time, urllib.request, winsound",
              "import ctypes, json, os, queue, re, sys, tempfile, threading, time, urllib.request, winsound")

start = s.index("    def read_worker(self):")
end = s.index("\nif __name__ == \"__main__\":")

new_method = r'''    def read_worker(self):
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
                    text = clean_text(doc[page_num - 1].get_text("text"))
                    chunks = split_text(text) if len(text) >= 20 else []
                    page_chunk_counts[page_num] = len(chunks)
                    for chunk_idx, chunk in enumerate(chunks, 1):
                        tasks.append((page_num, chunk_idx, len(chunks), chunk))

                total_chunks = len(tasks)
                if total_chunks == 0:
                    raise RuntimeError("No readable text was found in that page range.")

                self.ui(
                    status=f"Prepared pages {start}–{end}.",
                    detail=f"{total_chunks} chunks queued. Buffering the first audio...",
                    maximum=total_chunks,
                    progress=0
                )

                audio_queue = queue.Queue(maxsize=3)
                producer_error = []
                produced = {"count": 0}

                def producer():
                    try:
                        for page_num, chunk_idx, chunks_on_page, chunk in tasks:
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
                                (page_num, chunk_idx, chunks_on_page, wav)
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

                    page_num, chunk_idx, chunks_on_page, wav = item

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
                        status=f"Finished pages {start}–{end}.",
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
'''
s = s[:start] + new_method + s[end:]
p.write_text(s, encoding="utf-8")
print("patched")
