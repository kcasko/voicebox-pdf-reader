from pathlib import Path
p=Path(r"D:\Repos\voicebox-pdf-reader\reader.py")
s=p.read_text(encoding="utf-8")
start=s.index("VOICE_OPTIONS = {")
end=s.index("}\n\nSPEED_OPTIONS", start)+1
voices='''VOICE_OPTIONS = {
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
}'''
s=s[:start]+voices+s[end:]
s=s.replace('            self.pause_btn.configure(state="disabled")\n            self.paused = False',
            '            self.root.after(0, lambda: self.pause_btn.configure(state="disabled"))\n            self.paused = False')
s=s.replace('            self.pause_btn.configure(state="disabled")\n            self.ui(status="Error", detail=str(e))',
            '            self.root.after(0, lambda: self.pause_btn.configure(state="disabled"))\n            self.ui(status="Error", detail=str(e))')
p.write_text(s,encoding="utf-8")
print("patched")
