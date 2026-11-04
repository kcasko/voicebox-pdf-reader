import json, os, sys
sys.path.insert(0, r"D:\Repos\voicebox-pdf-reader")
import fitz, reader
s=json.load(open(os.path.join(os.environ["APPDATA"],"VoiceboxPDFReader","settings.json"),encoding="utf-8"))
doc=fitz.open(s["pdf_path"])
p=int(s.get("start_page") or 1)
print("PAGE",p)
chunks=reader.extract_page_chunks(doc[p-1])
for i,(txt,is_heading) in enumerate(chunks[:30],1):
    safe=txt.encode("ascii","replace").decode()
    print(f"{i:02d} heading={is_heading} len={len(txt)} :: {safe[:240]}")
