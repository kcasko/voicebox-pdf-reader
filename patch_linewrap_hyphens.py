from pathlib import Path
p=Path(r"D:\Repos\voicebox-pdf-reader\reader.py")
s=p.read_text(encoding="utf-8")

needle='''    elements = []
    body_accum = []

    def flush_body():
'''
replacement='''    elements = []
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
'''
if needle not in s:
    raise SystemExit("insert point not found")
s=s.replace(needle,replacement,1)
s=s.replace('''                if remainder:
                    body_accum.append(remainder)
''','''                if remainder:
                    add_body_line(remainder)
''')
s=s.replace('''                if line_text:
                    body_accum.append(line_text)
''','''                if line_text:
                    add_body_line(line_text)
''')
p.write_text(s,encoding="utf-8")
print("line-wrap dehyphenation installed")
