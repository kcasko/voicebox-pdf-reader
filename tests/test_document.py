import os

import pymupdf
import pytest

from pdfdesk import tools
from pdfdesk.document import PdfDocument, PasswordRequired, line_rects

YELLOW_MIN = (200, 200, 0)


def word_rect(document, page, text):
    return next(w.rect for w in document.words(page) if w.text == text)


def has_ink(document, page, rect):
    pix = document.page(page).get_pixmap(alpha=False)
    return any(
        sum(pix.pixel(x, y)) < 300
        for x in range(int(rect[0]), int(rect[2]))
        for y in range(int(rect[1]), int(rect[3]))
    )


def pixel_is_yellow(document, page, rect):
    """Render with annotations and look for highlight color inside an on-screen rectangle."""
    pix = document.page(page).get_pixmap(alpha=False, annots=True)
    for x in range(int(rect[0]), int(rect[2])):
        for y in range(int(rect[1]), int(rect[3])):
            r, g, b = pix.pixel(x, y)
            if r > 200 and g > 200 and b < 120:
                return True
    return False


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_highlight_lands_on_the_selected_word(qapp, pdf_factory, rotation):
    document = PdfDocument(pdf_factory([[(100, "Alpha Bravo Charlie")]], rotation))
    rect = word_rect(document, 0, "Bravo")
    assert has_ink(document, 0, rect), "word positions must match what is drawn on screen"
    words = [w for w in document.words(0) if w.text == "Bravo"]
    document.add_markup("highlight", {0: line_rects(words)})
    assert pixel_is_yellow(document, 0, rect)
    assert not pixel_is_yellow(document, 0, word_rect(document, 0, "Alpha"))
    assert document.dirty


def test_undo_redo_and_save_roundtrip(qapp, pdf_factory, tmp_path):
    path = pdf_factory([[(100, "One")], [(100, "Two")], [(100, "Three")]])
    document = PdfDocument(path)
    document.delete_pages([1])
    assert len(document) == 2
    document.undo()
    assert len(document) == 3
    document.redo()
    assert len(document) == 2
    document.save()
    assert not document.dirty
    with pymupdf.open(path) as check:
        assert check.page_count == 2
    # The file stays usable after saving over itself.
    document.rotate_pages([0], 90)
    document.save()
    assert PdfDocument(path).page(0).rotation == 90


def test_failed_edit_restores_the_document(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100, "One")], [(100, "Two")]]))
    with pytest.raises(RuntimeError):
        with document.edit(structural=True):
            document.doc.delete_page(0)
            raise RuntimeError("boom")
    assert len(document) == 2
    assert not document.can_undo()


def test_cannot_delete_every_page(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100, "One")]]))
    with pytest.raises(ValueError):
        document.delete_pages([0])


def test_move_pages(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100, "One")], [(100, "Two")], [(100, "Three")]]))
    document.move_pages([2, 0, 1])
    assert [document.words(i)[0].text for i in range(3)] == ["Three", "One", "Two"]


def test_password_protect_and_reopen(qapp, pdf_factory, tmp_path):
    document = PdfDocument(pdf_factory([[(100, "Secret")]]))
    document.password = "hunter2"
    out = str(tmp_path / "locked.pdf")
    document.save(out)
    with pytest.raises(PasswordRequired):
        PdfDocument(out)
    assert PdfDocument(out, password="hunter2").words(0)[0].text == "Secret"
    # Later saves keep the password, and edits still work on the reopened file.
    document.rotate_pages([0], 90)
    document.save()
    with pytest.raises(PasswordRequired):
        PdfDocument(out)


def test_parse_ranges():
    assert tools.parse_ranges("1-2, 4", 5) == [[0, 1], [3]]
    for bad in ("", "0", "6", "3-2", "a"):
        with pytest.raises(ValueError):
            tools.parse_ranges(bad, 5)


def test_merge_split_extract(qapp, pdf_factory, tmp_path):
    a = pdf_factory([[(100, "A1")], [(100, "A2")]])
    b = pdf_factory([[(100, "B1")]])
    merged = str(tmp_path / "merged.pdf")
    tools.merge_files([a, b], merged)
    document = PdfDocument(merged)
    assert [document.words(i)[0].text for i in range(3)] == ["A1", "A2", "B1"]
    paths = tools.split_every(document, 2, str(tmp_path), "part")
    assert [pymupdf.open(p).page_count for p in paths] == [2, 1]


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_page_numbers_sit_at_the_bottom_on_rotated_pages(qapp, pdf_factory, rotation):
    document = PdfDocument(pdf_factory([[(100, "Body")]], rotation))
    tools.add_page_numbers(document, "{page}#")
    page = document.page(0)
    number = next(w for w in document.words(0) if w.text == "1#")
    assert number.rect[1] > page.rect.height * 0.9
    assert abs((number.rect[0] + number.rect[2]) / 2 - page.rect.width / 2) < 20
    dictionary = page.get_text("dict")
    direction = next(
        line["dir"]
        for block in dictionary["blocks"]
        for line in block.get("lines", [])
        if any("1#" in s["text"] for s in line["spans"])
    )
    # PyMuPDF reports direction on the unrotated page; on screen it has to read left to right.
    on_screen = pymupdf.Point(direction) * pymupdf.Matrix(rotation)
    assert tuple(on_screen) == pytest.approx((1, 0), abs=0.01)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_watermark_is_centered_and_rises_to_the_right(qapp, pdf_factory, rotation):
    document = PdfDocument(pdf_factory([[(100, "Body")]], rotation))
    tools.add_watermark(document, "DRAFT")
    page = document.page(0)
    rect = word_rect(document, 0, "DRAFT")
    assert abs((rect[0] + rect[2]) / 2 - page.rect.width / 2) < 25
    assert abs((rect[1] + rect[3]) / 2 - page.rect.height / 2) < 25
    direction = next(
        line["dir"]
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        if any("DRAFT" in s["text"] for s in line["spans"])
    )
    x, y = pymupdf.Point(direction) * pymupdf.Matrix(rotation)
    assert x > 0.5 and y < -0.5


def test_watermark_and_compress(qapp, pdf_factory, tmp_path):
    document = PdfDocument(pdf_factory([[(100, "Body")]]))
    tools.add_watermark(document, "DRAFT")
    assert "DRAFT" in document.page(0).get_text()
    out = str(tmp_path / "small.pdf")
    assert tools.compress(document, out) == os.path.getsize(out)
    assert "DRAFT" in pymupdf.open(out)[0].get_text()


def test_form_field_fill(qapp, tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    widget = pymupdf.Widget()
    widget.field_name = "name"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.rect = pymupdf.Rect(50, 50, 250, 80)
    page.add_widget(widget)
    path = str(tmp_path / "form.pdf")
    doc.save(path)
    document = PdfDocument(path)
    xref = document.widget_at(0, (100, 60))
    assert xref is not None
    document.set_widget_value(0, xref, "Ada")
    document.save()
    assert PdfDocument(path).widget_info(0, xref)["value"] == "Ada"
