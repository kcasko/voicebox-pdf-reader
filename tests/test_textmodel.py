import importlib.util
import os
import sys

from pdfdesk.document import PdfDocument

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_textmodel():
    spec = importlib.util.spec_from_file_location("read_aloud_textmodel", os.path.join(ROOT, "plugins", "read_aloud", "textmodel.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tm = load_textmodel()


def build(document, furniture=frozenset()):
    builder = tm.ChunkBuilder(document, furniture)
    for index in range(len(document)):
        builder.feed(index)
    return builder.finish()


def test_splits_sentences_and_keeps_abbreviations(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100, "Dr. Smith went to the very old market today. It was closed for the entire day.")]]))
    assert [c.text for c in build(document)] == [
        "Dr. Smith went to the very old market today.",
        "It was closed for the entire day.",
    ]


def test_sentence_continues_across_a_page_break(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100, "This sentence starts on one page and")], [(100, "finishes on the next page.")]]))
    chunks = build(document)
    assert [c.text for c in chunks] == ["This sentence starts on one page and finishes on the next page."]
    assert set(chunks[0].rects) == {0, 1}


def test_rejoins_line_wrap_hyphens_but_keeps_real_ones(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100, "The difference bet-"), (114, "ween a 32-bit word and more.")]]))
    assert build(document)[0].text == "The difference between a 32-bit word and more."


def test_only_fully_bold_short_lines_are_headings(qapp, pdf_factory):
    path = pdf_factory([[(100, "Chapter One", "hebo"), (120, "Normal body text follows the heading here.")]])
    chunks = build(PdfDocument(path))
    assert chunks[0].heading and chunks[0].text == "Chapter One."
    assert not chunks[1].heading


def test_a_bold_word_inside_a_line_is_not_a_heading(qapp, tmp_path):
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Note", fontname="hebo", fontsize=11)
    page.insert_text((102, 100), "that this line keeps going as one sentence.", fontname="helv", fontsize=11)
    path = str(tmp_path / "mixed.pdf")
    doc.save(path)
    chunks = build(PdfDocument(path))
    assert [c.text for c in chunks] == ["Note that this line keeps going as one sentence."]
    assert not chunks[0].heading


def test_running_headers_and_page_numbers_are_skipped(qapp, pdf_factory):
    pages = [[(30, "My Book Title"), (300, f"Body sentence on page number {i} goes here."), (770, str(i))] for i in range(1, 6)]
    document = PdfDocument(pdf_factory(pages))
    furniture = tm.find_furniture(document)
    text = " ".join(c.text for c in build(document, furniture))
    assert "My Book Title" not in text
    assert "goes here. Body" in text
    assert text.count("Body sentence") == 5


def test_long_sentences_split_at_a_pause(qapp, pdf_factory):
    lines = [(100 + 14 * i, "this is one quite long clause of the sentence, and it") for i in range(14)]
    document = PdfDocument(pdf_factory([lines]))
    chunks = build(document)
    assert len(chunks) > 1
    assert all(len(c.text) <= tm.MAX_CHARS + 20 for c in chunks)
    assert chunks[0].text.endswith(",")


def test_finding_a_word_and_highlight_rects(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100, "First sentence is right here. Second sentence is right here too.")]]))
    chunks = build(document)
    second = next(w for w in document.words(0) if w.text == "Second")
    assert tm.first_chunk_at(chunks, 0, second.index) == 1
    assert tm.first_chunk_at(chunks, 5, 0) is None
    assert chunks[1].rects[0][0][0] <= second.rect[0]


def test_partial_page_feed_for_selection(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100, "One two three four five six")]]))
    builder = tm.ChunkBuilder(document)
    builder.feed(0, 2, 3)
    assert builder.finish()[0].text == "three four"


def test_scanned_page_gives_no_chunks(qapp, pdf_factory):
    assert build(PdfDocument(pdf_factory([[]]))) == []
