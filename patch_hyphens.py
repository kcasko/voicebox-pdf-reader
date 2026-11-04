from pathlib import Path
p=Path(r"D:\Repos\voicebox-pdf-reader\reader.py")
s=p.read_text(encoding="utf-8")

old='''def clean_text(text):
    text = text.replace("\xad", "")
    text = re.sub(r"-\\s*\\n\\s*", "", text)
    text = re.sub(r"[\\u2022\\u25AA\\u25E6\\u25A0\\u25CF]+", ". ", text)
    text = re.sub(r"\\s*\\n\\s*", " ", text)
    text = re.sub(r"\\s+", " ", text)
    return text.strip()
'''

new='''def clean_text(text):
    # Normalize PDF hyphen variants and remove soft hyphens.
    text = text.replace("\xad", "")
    text = text.replace("\u2010", "-").replace("\u2011", "-").replace("\u2212", "-")

    # Repair words split by PDF line wrapping:
    #   "bet-\\nween" -> "between"
    #   "bet- ween"    -> "between"
    text = re.sub(r"(?<=[A-Za-z])-\\s*\\n\\s*(?=[a-z])", "", text)
    text = re.sub(r"(?<=[A-Za-z])-\\s+(?=[a-z])", "", text)

    # Bullets and line joins.
    text = re.sub(r"[\\u2022\\u25AA\\u25E6\\u25A0\\u25CF]+", ". ", text)
    text = re.sub(r"\\s*\\n\\s*", " ", text)
    text = re.sub(r"\\s+", " ", text)

    # Kokoro generally reads compounds more naturally without the literal hyphen.
    # Examples: "32-bit" -> "32 bit", "pre-installed" -> "pre installed".
    # Keep minus signs/ranges with surrounding spaces untouched.
    text = re.sub(r"(?<=[A-Za-z0-9])-(?=[A-Za-z])", " ", text)

    return text.strip()
'''
if old not in s:
    raise SystemExit("clean_text block not found")
s=s.replace(old,new)
p.write_text(s,encoding="utf-8")
print("hyphen normalization installed")
