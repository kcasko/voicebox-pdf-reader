"""Generated PDFs with a known correct reading, and a score for how close Read Aloud gets.

Generated files only show that known problems stay fixed. Real PDFs behave differently, so
reading_report.py can also list what would be spoken for any folder of PDFs.
"""

import difflib
import importlib.util
import os
import re
import sys

import pymupdf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def load_textmodel():
    name = "read_aloud_textmodel"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "plugins", "read_aloud", "textmodel.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


LEFT = "The study began in the spring of that year with a small group of volunteers from the town. Each person kept a daily record of their sleep and their mood for six weeks."
RIGHT = "The results surprised the whole team when they were finally published. Most people slept longer than they had reported at the start, and few of them noticed the change."


def _box(page, rect, text, size=10, font="helv"):
    page.insert_textbox(pymupdf.Rect(rect), text, fontsize=size, fontname=font)


def right_first(path):
    doc = pymupdf.open()
    page = doc.new_page()
    _box(page, (315, 72, 560, 400), RIGHT)
    _box(page, (50, 72, 295, 400), LEFT)
    doc.save(path)
    return [LEFT, RIGHT]


def interleaved(path):
    doc = pymupdf.open()
    page = doc.new_page()
    left = LEFT.split(". ")
    right = RIGHT.split(". ")
    _box(page, (50, 72, 295, 150), left[0] + ".")
    _box(page, (315, 72, 560, 150), right[0] + ".")
    _box(page, (50, 160, 295, 240), left[1])
    _box(page, (315, 160, 560, 240), right[1])
    doc.save(path)
    return [LEFT, RIGHT]


def interleaved_lines(path):
    doc = pymupdf.open()
    page = doc.new_page()
    left = ["Left column sentence one is here.", "Left column sentence two follows it.", "Left column sentence three ends it."]
    right = ["Right column sentence one is here.", "Right column sentence two follows it.", "Right column sentence three ends it."]
    for row in range(3):
        page.insert_text((60, 100 + row * 16), left[row], fontsize=10)
        page.insert_text((330, 100 + row * 16), right[row], fontsize=10)
    doc.save(path)
    return left + right


def title_and_columns(path):
    doc = pymupdf.open()
    page = doc.new_page()
    _box(page, (315, 150, 560, 500), RIGHT)
    _box(page, (50, 150, 295, 500), LEFT)
    _box(page, (50, 60, 560, 90), "A Long Study of Sleep and Mood in One Small Town", 16, "hebo")
    _box(page, (50, 95, 560, 135), "This abstract runs right across the whole width of the page above both of the columns below it.", 10)
    doc.save(path)
    return ["A Long Study of Sleep and Mood in One Small Town.", "This abstract runs right across the whole width of the page above both of the columns below it.", LEFT, RIGHT]


def single_column(path):
    doc = pymupdf.open()
    page = doc.new_page()
    _box(page, (72, 72, 540, 300), LEFT + " " + RIGHT, 11)
    doc.save(path)
    return [LEFT + " " + RIGHT]


def table_stays_in_rows(path):
    doc = pymupdf.open()
    page = doc.new_page()
    rows = [("Item", "Qty", "Price"), ("Apples", "3", "1.50"), ("Oranges", "12", "10.25")]
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            page.insert_text((72 + c * 180, 100 + r * 18), cell, fontsize=10)
    doc.save(path)
    return ["Item Qty Price Apples 3 1.50 Oranges 12 10.25"]


def citations(path):
    doc = pymupdf.open()
    page = doc.new_page()
    _box(page, (72, 72, 540, 300), "Sleep improves memory [12] as earlier work has shown (Smith et al., 2020; Lee, 2019). Details are at https://example.com/paper for anyone interested. Jones (2021) disagreed with this finding.", 11)
    doc.save(path)
    return ["Sleep improves memory as earlier work has shown. Details are at for anyone interested. Jones disagreed with this finding."]


def sentence_rules(path):
    doc = pymupdf.open()
    page = doc.new_page()
    _box(page, (72, 72, 540, 300), "The new law was passed by the U.S. Army and written by J. R. Tolkien in his long essay. The next section of the analysis of Eq. 2 shows the result clearly.", 11)
    doc.save(path)
    return ["The new law was passed by the U.S. Army and written by J. R. Tolkien in his long essay. The next section of the analysis of equation 2 shows the result clearly."]


def numbers(path):
    doc = pymupdf.open()
    page = doc.new_page()
    _box(page, (72, 72, 540, 300), "The bill came to $1,234.56 on 3/4/2024 at 5:30 and rose by 12% overnight.", 11)
    doc.save(path)
    return ["The bill came to 1,234 dollars and 56 cents on March 4, 20 24 at 5 30 and rose by 12 percent overnight."]


def footnote_and_references(path):
    doc = pymupdf.open()
    page = doc.new_page()
    _box(page, (72, 72, 540, 200), LEFT + " " + "The team wrote up what it found and shared the results with everyone taking part.", 11)
    page.insert_text((72, 730), "1 This small note explains where the funding for the study came from.", fontsize=8)
    page.insert_text((72, 300), "References", fontname="hebo", fontsize=14)
    page.insert_text((72, 325), "Smith J. and Lee K. A paper about sleep, Journal of Sleep, volume nine.", fontsize=11)
    doc.save(path)
    return [LEFT + " The team wrote up what it found and shared the results with everyone taking part."]


CASES = {
    "right_first": right_first,
    "interleaved": interleaved,
    "interleaved_lines": interleaved_lines,
    "title_and_columns": title_and_columns,
    "single_column": single_column,
    "table_stays_in_rows": table_stays_in_rows,
    "citations": citations,
    "sentence_rules": sentence_rules,
    "numbers": numbers,
    "footnote_and_references": footnote_and_references,
}


def spoken_words(document, skip_references=True):
    tm = load_textmodel()
    builder = tm.ChunkBuilder(document, tm.find_furniture(document), skip_references)
    for index in range(len(document)):
        builder.feed(index)
    return " ".join(chunk.spoken for chunk in builder.finish())


def score(expected, actual):
    """Similarity from 0 to 1, comparing words and their order."""
    def words(text):
        return re.findall(r"[\w'’]+", text.lower())

    return difflib.SequenceMatcher(None, words(" ".join(expected)), words(actual), autojunk=False).ratio()
