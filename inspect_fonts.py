import json, os, sys
sys.path.insert(0, r"D:\Repos\voicebox-pdf-reader")
import fitz
s=json.load(open(os.path.join(os.environ["APPDATA"],"VoiceboxPDFReader","settings.json"),encoding="utf-8"))
doc=fitz.open(s["pdf_path"])
p=int(s.get("start_page") or 1)
page=doc[p-1]
for block in page.get_text("dict").get("blocks",[]):
    for line in block.get("lines",[]):
        parts=[]
        for span in line.get("spans",[]):
            t=span.get("text","").strip()
            if t:
                parts.append((t,span.get("font"),span.get("size"),span.get("flags")))
        if parts:
            safe=str(parts).encode("ascii","replace").decode()
            print(safe[:500])
