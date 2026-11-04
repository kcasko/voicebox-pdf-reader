"""Shows how Read Aloud will read PDFs, to check them by eye or by ear.

    .venv\\Scripts\\python tests\\reading_report.py                    the generated cases and their scores
    .venv\\Scripts\\python tests\\reading_report.py FOLDER report.txt   every PDF in a folder, written to a file

The report for a folder includes document text, so keep it with the PDFs it came from.
"""

import os
import re
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

from reading_corpus import CASES, load_textmodel, score, spoken_words

from pdfdesk.document import PdfDocument

SHORT_CHUNK = 12
LEFTOVER = re.compile(r"https?://|\[\d+\]|\(\w+ et al")


def generated():
    folder = tempfile.mkdtemp(prefix="pdfdesk-corpus-")
    results = []
    for name, make in CASES.items():
        path = os.path.join(folder, name + ".pdf")
        expected = make(path)
        document = PdfDocument(path)
        result = score(expected, spoken_words(document))
        results.append(result)
        print(f"{result * 100:6.1f}%  {name}")
        document.close()
    print(f"{sum(results) / len(results) * 100:6.1f}%  average of {len(results)} generated cases")


def real(folder, out_path):
    tm = load_textmodel()
    with open(out_path, "w", encoding="utf-8") as out:
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith(".pdf"):
                continue
            try:
                document = PdfDocument(os.path.join(folder, name))
            except Exception as e:
                out.write(f"\n===== {name}: could not open: {e}\n")
                continue
            builder = tm.ChunkBuilder(document, tm.find_furniture(document), True)
            for index in range(len(document)):
                builder.feed(index)
            chunks = builder.finish()
            short = sum(1 for c in chunks if len(c.spoken) < SHORT_CHUNK)
            leftover = sum(1 for c in chunks if LEFTOVER.search(c.spoken))
            out.write(f"\n===== {name}: {len(document)} pages, {len(chunks)} sentences, {short} very short, {leftover} with leftover references\n")
            for chunk in chunks:
                out.write(f"[p{chunk.page + 1}] {chunk.spoken}\n")
            document.close()
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    app = QApplication.instance() or QApplication([])
    if len(sys.argv) == 3:
        real(sys.argv[1], sys.argv[2])
    else:
        generated()
