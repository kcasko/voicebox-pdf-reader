from pathlib import Path

p = Path(r"D:\Repos\voicebox-pdf-reader\reader.py")
s = p.read_text(encoding="utf-8")

old = '''def clean_text(text):
    text = re.sub(r"-\\s*\\n\\s*", "", text)
    text = re.sub(r"[•▪◦]+", ". ", text)
    text = re.sub(r"\\s*\\n\\s*", " ", text)
    text = re.sub(r"\\s+", " ", text)
    return text.strip()

def split_text(text, limit=CHUNK_CHARS):
'''

new = '''def clean_text(text):
    text = re.sub(r"-\\s*\\n\\s*", "", text)
    text = re.sub(r"[•▪◦]+", ". ", text)
    text = re.sub(r"\\s*\\n\\s*", " ", text)
    text = re.sub(r"\\s+", " ", text)
    return text.strip()

def extract_page_chunks(page, limit=CHUNK_CHARS):
    data = page.get_text("dict")
    spans = []
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if text:
                    spans.append((text, float(span.get("size", 0))))

    if not spans:
        text = clean_text(page.get_text("text"))
        return [(chunk, False) for chunk in split_text(text, limit)] if text else []

    sizes = sorted(size for _, size in spans if size > 0)
    body_size = sizes[len(sizes) // 2] if sizes else 10.0
    heading_threshold = body_size * 1.18

    elements = []
    for block in data.get("blocks", []):
        block_lines = []
        for line in block.get("lines", []):
            line_text = " ".join(
                span.get("text", "").strip()
                for span in line.get("spans", [])
                if span.get("text", "").strip()
            ).strip()
            if not line_text:
                continue
            max_size = max(
                [float(span.get("size", 0)) for span in line.get("spans", [])] or [0]
            )
            is_heading = (
                max_size >= heading_threshold
                and len(line_text) <= 100
                and any(ch.isalpha() for ch in line_text)
            )
            block_lines.append((line_text, is_heading))

        if not block_lines:
            continue

        body_accum = []
        for line_text, is_heading in block_lines:
            if is_heading:
                if body_accum:
                    body = clean_text(" ".join(body_accum))
                    for chunk in split_text(body, limit):
                        elements.append((chunk, False))
                    body_accum = []
                heading = clean_text(line_text)
                if heading and heading[-1] not in ".!?":
                    heading += "."
                elements.append((heading, True))
            else:
                body_accum.append(line_text)

        if body_accum:
            body = clean_text(" ".join(body_accum))
            for chunk in split_text(body, limit):
                elements.append((chunk, False))

    return elements

def split_text(text, limit=CHUNK_CHARS):
'''

if old not in s:
    raise SystemExit("clean_text block not found")
s = s.replace(old, new)

old_tasks = '''                tasks = []
                page_chunk_counts = {}
                for page_num in range(start, end + 1):
                    text = clean_text(doc[page_num - 1].get_text("text"))
                    chunks = split_text(text) if len(text) >= 20 else []
                    page_chunk_counts[page_num] = len(chunks)
                    for chunk_idx, chunk in enumerate(chunks, 1):
                        tasks.append((page_num, chunk_idx, len(chunks), chunk))
'''

new_tasks = '''                tasks = []
                page_chunk_counts = {}
                for page_num in range(start, end + 1):
                    chunks = extract_page_chunks(doc[page_num - 1])
                    page_chunk_counts[page_num] = len(chunks)
                    for chunk_idx, (chunk, is_heading) in enumerate(chunks, 1):
                        tasks.append((page_num, chunk_idx, len(chunks), chunk, is_heading))
'''

if old_tasks not in s:
    raise SystemExit("tasks block not found")
s = s.replace(old_tasks, new_tasks)

s = s.replace(
    'for page_num, chunk_idx, chunks_on_page, chunk in tasks:',
    'for page_num, chunk_idx, chunks_on_page, chunk, is_heading in tasks:'
)

s = s.replace(
    'audio_queue.put(\\n                                (page_num, chunk_idx, chunks_on_page, wav)\\n                            )',
    'audio_queue.put(\\n                                (page_num, chunk_idx, chunks_on_page, wav, is_heading)\\n                            )'
)

s = s.replace(
    'page_num, chunk_idx, chunks_on_page, wav = item',
    'page_num, chunk_idx, chunks_on_page, wav, is_heading = item'
)

s = s.replace(
    'winsound.PlaySound(wav, winsound.SND_FILENAME)\\n                    done += 1',
    'winsound.PlaySound(wav, winsound.SND_FILENAME)\\n                    if is_heading and not self.stop_flag:\\n                        time.sleep(0.35)\\n                    done += 1'
)

p.write_text(s, encoding="utf-8")
print("heading-aware narration patch applied")
