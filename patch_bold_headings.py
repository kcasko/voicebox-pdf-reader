from pathlib import Path
import re

p=Path(r"D:\Repos\voicebox-pdf-reader\reader.py")
s=p.read_text(encoding="utf-8")

start=s.index("def extract_page_chunks(")
end=s.index("\ndef split_text(", start)

new=r'''def extract_page_chunks(page, limit=CHUNK_CHARS):
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
'''

s=s[:start]+new+s[end:]
p.write_text(s,encoding="utf-8")
print("bold-span heading parser installed")
