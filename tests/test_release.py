import importlib.util
import json
import os
import sys
import time
import wave

import numpy
import pymupdf
import pytest
from PySide6.QtCore import Qt
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QTreeWidget,
    QWidget,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reading_corpus import load_textmodel

from pdfdesk import theme as theme_module
from pdfdesk import settings, tools
from pdfdesk.document import PdfDocument
from pdfdesk.main_window import MainWindow, page_list
from pdfdesk.theme import DARK, LIGHT

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS = os.path.join(ROOT, "plugins")
tm = load_textmodel()


@pytest.fixture
def window(qapp, tmp_path):
    windows = []

    def make(folders=None):
        win = MainWindow(folders or [], home=str(tmp_path / "home"))
        win.show()
        windows.append(win)
        return win

    yield make
    for win in windows:
        for view in win.views():
            view.document.dirty = False
        win.close()
    QApplication.processEvents()


def multi_page(path, pages=5, text="This is the sentence that sits on page number {} of this file."):
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 90), text.format(i + 1), fontsize=11)
    doc.save(path)
    doc.close()
    return str(path)


def protected(path, **options):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 90), "Private words.", fontsize=11)
    doc.new_page().insert_text((72, 90), "More private words.", fontsize=11)
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, **options)
    doc.close()
    return str(path)


# Accessibility
def luminance(color):
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
@pytest.mark.parametrize(
    "front, back, needed",
    [
        ("text", "surface", 4.5),
        ("muted", "surface", 4.5),
        ("faint", "surface", 4.5),
        ("on_accent", "accent", 4.5),
        ("control_border", "surface", 3),
    ],
)
def test_colors_meet_wcag_aa(palette, front, back, needed):
    assert contrast(palette[front], palette[back]) >= needed


def test_every_focusable_control_has_a_name(window, tmp_path):
    win = window([PLUGINS])
    win.open_path(multi_page(tmp_path / "a.pdf"))
    win.plugins.plugins["read_aloud"].module._panel.parent().show()
    win.side.show_panel("search")
    QApplication.processEvents()
    kinds = (QAbstractButton, QComboBox, QLineEdit, QListWidget, QTreeWidget, QAbstractSpinBox)
    unnamed = []
    for widget in win.findChildren(QWidget):
        if not isinstance(widget, kinds) or widget.focusPolicy() == Qt.NoFocus or not widget.isVisible():
            continue
        text = "" if isinstance(widget, QLineEdit) else widget.text() if hasattr(widget, "text") else ""
        if not (widget.accessibleName() or text):
            unnamed.append(f"{type(widget).__name__} {widget.objectName()} {widget.toolTip()}")
    assert not unnamed


def test_keyboard_focus_styles_exist(window):
    window()
    sheet = QApplication.instance().styleSheet()
    for selector in ("QToolButton:focus", "QPushButton:focus", "QListWidget:focus", "PdfView:focus", "QCheckBox:focus", "QTabBar:focus"):
        assert selector in sheet


def test_contrast_theme_uses_the_system_colors(window, monkeypatch):
    win = window()
    monkeypatch.setattr(theme_module, "high_contrast_enabled", lambda: True)
    win.set_theme("light")
    assert QApplication.instance().styleSheet() == ""
    monkeypatch.setattr(theme_module, "high_contrast_enabled", lambda: False)
    win.set_theme("light")
    assert QApplication.instance().styleSheet() != ""


def test_enter_on_a_thumbnail_goes_to_that_page(window, tmp_path):
    win = window()
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    win.thumbnails.itemActivated.emit(win.thumbnails.item(3))
    assert view.current_page == 3


def test_enter_on_an_outline_entry_goes_to_that_page(window, tmp_path):
    path = multi_page(tmp_path / "a.pdf")
    with pymupdf.open(path) as doc:
        doc.set_toc([[1, "Part two", 3]])
        doc.saveIncr()
    win = window()
    view = win.open_path(path)
    win.outline.itemActivated.emit(win.outline.topLevelItem(0), 0)
    assert view.current_page == 2


def test_markup_tools_are_in_a_menu(window):
    win = window()
    menu = next(a.menu() for a in win.menuBar().actions() if a.text() == "&Mark Up")
    assert set(win.tool_actions.values()) <= set(menu.actions())


# Search
def wait_for_search(panel):
    end = time.monotonic() + 30
    while panel._timer.isActive() and time.monotonic() < end:
        QApplication.processEvents()


def test_search_builds_snippets_without_a_lookup_per_match(window, tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    for row in range(20):
        page.insert_text((72, 80 + row * 14), "the quick brown fox and the quick grey hare and the quick cat", fontsize=9)
    path = str(tmp_path / "s.pdf")
    doc.save(path)
    doc.close()
    win = window()
    win.open_path(path)
    win.search.input.setText("quick")
    start = time.monotonic()
    win.search.start()
    wait_for_search(win.search)
    assert len(win.search._matches) == 60
    assert time.monotonic() - start < 2
    assert "quick" in win.search.results.item(0).text()


def test_match_case_filters_results(window, tmp_path):
    win = window()
    win.open_path(multi_page(tmp_path / "a.pdf", 1, "Quick quick QUICK word {}"))
    win.search.case_box.blockSignals(True)
    win.search.case_box.setChecked(True)
    win.search.case_box.blockSignals(False)
    win.search.input.setText("quick")
    win.search.start()
    wait_for_search(win.search)
    assert len(win.search._matches) == 1


def test_search_results_are_capped(window, tmp_path, monkeypatch):
    monkeypatch.setattr("pdfdesk.panels.MAX_SEARCH_RESULTS", 3)
    win = window()
    win.open_path(multi_page(tmp_path / "a.pdf", 10))
    win.search.input.setText("sentence")
    win.search.start()
    wait_for_search(win.search)
    assert len(win.search._matches) == 3
    assert "First 3" in win.search.status.text()


def test_clearing_a_search_clears_its_highlights(window, tmp_path):
    win = window()
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    win.search.input.setText("sentence")
    win.search.start()
    wait_for_search(win.search)
    assert "search-current" in view._overlays
    win.search.input.setText("")
    win.search.start()
    assert "search" not in view._overlays and "search-current" not in view._overlays


def test_deleting_pages_refreshes_search_results(window, tmp_path):
    win = window()
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    win.search.input.setText("sentence")
    win.search.start()
    wait_for_search(win.search)
    view.document.delete_pages([0, 1])
    wait_for_search(win.search)
    assert len(win.search._matches) == 3


# Speed
def test_links_and_widgets_are_read_once_per_page(qapp, tmp_path, monkeypatch):
    path = str(tmp_path / "l.pdf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(10, 10, 50, 30), "uri": "https://example.com"})
    doc.save(path)
    doc.close()
    document = PdfDocument(path)
    assert document.link_at(0, (20, 20))["uri"] == "https://example.com"
    assert document.link_at(0, (200, 200)) is None
    assert 0 in document._links
    cached = document._links[0]
    document.link_at(0, (20, 20))
    assert document._links[0] is cached
    document.add_note(0, (100, 100), "note")
    assert 0 not in document._links
    document.close()


def test_network_paths_arent_checked_at_startup(monkeypatch):
    def fail(_path):
        raise AssertionError("asked the network")

    monkeypatch.setattr(os.path, "exists", fail)
    assert settings.may_exist(r"\\server\share\a.pdf")


def test_missing_local_files_are_hidden(tmp_path):
    assert not settings.may_exist(str(tmp_path / "gone.pdf"))
    assert settings.may_exist(str(tmp_path))


def test_page_cache_is_limited_by_memory(window, tmp_path, monkeypatch):
    monkeypatch.setattr("pdfdesk.viewer.CACHE_BYTES", 1)
    win = window()
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    for index in range(5):
        view.go_to_page(index)
        view.viewport().repaint()
    assert len(view._cache) <= 2


def test_scanned_pages_dont_decode_images(window, qapp, tmp_path, monkeypatch):
    path = str(tmp_path / "scan.pdf")
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 200, 200), False)
    doc = pymupdf.open()
    doc.new_page().insert_image(pymupdf.Rect(0, 0, 200, 200), pixmap=pix)
    doc.save(path)
    doc.close()
    document = PdfDocument(path)
    builder = tm.ChunkBuilder(document)
    monkeypatch.setattr(tm, "_page_styles", lambda page: pytest.fail("looked at a page with no words"))
    builder.feed(0)
    assert builder.finish() == []
    document.close()


# Reading
def test_compounds_keep_their_hyphen_over_a_line_break(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100, "These are well-"), (114, "known self-"), (128, "service tools and a bet-"), (142, "ween word.")]]))
    builder = tm.ChunkBuilder(document)
    builder.feed(0)
    assert builder.finish()[0].text == "These are well-known self-service tools and a between word."
    document.close()


def test_table_rows_are_read_separately(qapp, tmp_path):
    path = str(tmp_path / "t.pdf")
    doc = pymupdf.open()
    page = doc.new_page()
    for r, row in enumerate([("Item", "Qty"), ("Apples", "3"), ("Oranges", "12")]):
        for c, cell in enumerate(row):
            page.insert_text((72 + c * 180, 100 + r * 18), cell, fontsize=10)
    doc.save(path)
    doc.close()
    document = PdfDocument(path)
    builder = tm.ChunkBuilder(document)
    builder.feed(0)
    assert [c.text for c in builder.finish()] == ["Item Qty", "Apples 3", "Oranges 12"]
    document.close()


def test_text_the_voices_cant_read_is_skipped():
    assert tm.spoken_text("这是一个中文句子") == ""
    assert tm.spoken_text("Résumé") == "Résumé"
    assert tm.spoken_text("94.2") == "94.2"


# Problems found on real PDFs
def chunks_for(document, skip=True):
    builder = tm.ChunkBuilder(document, frozenset(), skip)
    for index in range(len(document)):
        builder.feed(index)
    return builder.finish()


def test_bold_table_rows_arent_headings(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100, "Revenue 960 1,001 3,859", "hebo"), (120, "This ordinary sentence of body text follows the bold row.")]]))
    assert not chunks_for(document)[0].heading
    document.close()


def test_bold_lowercase_line_isnt_a_heading(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100, "carries on from the line before it", "hebo"), (120, "This ordinary sentence of body text follows the bold line.")]]))
    assert not chunks_for(document)[0].heading
    document.close()


def test_symbol_font_bullets_arent_spoken():
    assert "" not in tm.spoken_text("Actions:  Configuring a driver")
    assert tm.spoken_text("") == ""


def test_a_name_broken_after_its_hyphen_stays_whole(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100, "The model called gpt-4-"), (114, "0125 is the newest version here.")]]))
    assert "gpt-4-0125" in chunks_for(document)[0].text
    document.close()


def test_untitled_contents_page_is_skipped_but_a_table_isnt(qapp, pdf_factory):
    contents = PdfDocument(pdf_factory([[(100 + i * 16, f"Section number {name} {page}") for i, (name, page) in enumerate(zip("abcdef", (3, 7, 11, 12, 14, 18)))]]))
    assert chunks_for(contents) == []
    contents.close()
    table = PdfDocument(pdf_factory([[(100 + i * 16, f"Revenue line {name} {value}") for i, (name, value) in enumerate(zip("abcdef", (90, 12, 55, 7, 81, 3)))]]))
    assert chunks_for(table)
    table.close()


def test_contents_pages_are_read_when_skipping_is_off(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100 + i * 16, f"Section number {name} {i + 1}") for i, name in enumerate("abcdef")]]))
    assert chunks_for(document, skip=False)
    document.close()


def test_failure_messages_say_what_to_do(tmp_path, monkeypatch):
    from pdfdesk.main_window import open_failure_reason

    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-1.7 truncated")
    assert "damaged" in open_failure_reason(str(path), RuntimeError("raw message"))
    assert open_failure_reason(str(path), ValueError("This PDF has no pages.")) == "This PDF has no pages."
    assert "OneDrive" in open_failure_reason(str(tmp_path / "unreadable.pdf"), RuntimeError("raw message"))


# File safety
def test_copies_of_a_password_pdf_keep_the_password(qapp, tmp_path):
    source = protected(tmp_path / "p.pdf", user_pw="secret", owner_pw="boss")
    document = PdfDocument(source, password="secret")
    for name, make in (
        ("extract.pdf", lambda p: tools.save_pages(document, [0], p)),
        ("compress.pdf", lambda p: tools.compress(document, p)),
    ):
        out = str(tmp_path / name)
        make(out)
        with pymupdf.open(out) as copy:
            assert copy.needs_pass
            assert copy.authenticate("secret")
    document.close()


def test_copies_of_a_restricted_pdf_keep_the_restrictions(qapp, tmp_path):
    source = protected(tmp_path / "r.pdf", owner_pw="boss", permissions=pymupdf.PDF_PERM_ACCESSIBILITY)
    document = PdfDocument(source)
    assert document.edits_restricted
    out = str(tmp_path / "copy.pdf")
    tools.save_pages(document, [0], out)
    with pymupdf.open(out) as copy:
        assert not copy.needs_pass
        assert not copy.permissions & pymupdf.PDF_PERM_MODIFY
    document.close()


def test_ordinary_pdfs_arent_restricted(qapp, tmp_path):
    document = PdfDocument(multi_page(tmp_path / "a.pdf"))
    assert not document.edits_restricted and document.protection_options() == {}
    document.close()


def test_restricted_pdf_warns_once_after_a_change(window, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: calls.append(a[2])))
    win = window()
    view = win.open_path(protected(tmp_path / "r.pdf", owner_pw="boss", permissions=pymupdf.PDF_PERM_ACCESSIBILITY))
    assert not calls
    view.document.add_note(0, (100, 100), "one")
    view.document.add_note(0, (120, 120), "two")
    assert len(calls) == 1 and "restricted" in calls[0]


def test_a_failed_save_leaves_the_old_file_alone(qapp, tmp_path, monkeypatch):
    document = PdfDocument(multi_page(tmp_path / "a.pdf"))
    target = tmp_path / "keep.pdf"
    target.write_bytes(b"precious")

    def broken(self, *a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(pymupdf.Document, "save", broken)
    with pytest.raises(RuntimeError):
        tools.save_pages(document, [0], str(target))
    assert target.read_bytes() == b"precious"
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []
    document.close()


def test_splitting_asks_before_replacing_files(window, tmp_path, monkeypatch):
    win = window()
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    folder = tmp_path / "out"
    folder.mkdir()
    existing = folder / "a - pages 1-2.pdf"
    existing.write_bytes(b"precious")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("1-2", True)))
    monkeypatch.setattr("pdfdesk.main_window.QFileDialog.getExistingDirectory", staticmethod(lambda *a, **k: str(folder)))
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.No))
    win._split_dialog()
    assert asked and existing.read_bytes() == b"precious"
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    win._split_dialog()
    assert existing.read_bytes() != b"precious"
    assert view.document is not None


def test_delete_prompt_names_the_pages():
    assert page_list([2]) == "page 3"
    assert page_list([0, 2]) == "2 pages (1, 3)"
    assert "and 5 more" in page_list(list(range(15)))


def test_a_failed_insert_leaves_the_document_unmodified(window, tmp_path, monkeypatch):
    win = window()
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    locked = protected(tmp_path / "p.pdf", user_pw="secret", owner_pw="boss")
    monkeypatch.setattr("pdfdesk.main_window.QFileDialog.getOpenFileName", staticmethod(lambda *a, **k: (locked, "")))
    answers = [("wrong", True), ("", False)]
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: answers.pop(0)))
    win._insert_pdf()
    assert not view.document.dirty and len(view.document) == 5


def test_inserting_a_protected_pdf_asks_for_its_password(window, tmp_path, monkeypatch):
    win = window()
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    locked = protected(tmp_path / "p.pdf", user_pw="secret", owner_pw="boss")
    monkeypatch.setattr("pdfdesk.main_window.QFileDialog.getOpenFileName", staticmethod(lambda *a, **k: (locked, "")))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("secret", True)))
    win._insert_pdf()
    assert len(view.document) == 7


def test_a_file_changed_elsewhere_offers_to_reload(window, tmp_path, monkeypatch):
    path = multi_page(tmp_path / "a.pdf")
    win = window()
    view = win.open_path(path)
    win._check_disk(path)  # Nothing changed, so nothing to ask.
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes))
    assert not asked
    view.document.known_signature = (0, 0)
    win._check_disk(path)
    assert asked
    assert win.current_view() is not view and len(win.views()) == 1


def test_saving_doesnt_count_as_another_program_changing_it(window, tmp_path, monkeypatch):
    path = multi_page(tmp_path / "a.pdf")
    win = window()
    view = win.open_path(path)
    view.document.add_note(0, (100, 100), "note")
    win.save()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: pytest.fail("asked after our own save")))
    win._check_disk(path)


# Printing
def printed_page_sizes(path):
    with pymupdf.open(path) as doc:
        return [(page.rect.width, page.rect.height, len(page.get_images())) for page in doc]


def test_printing_turns_a_landscape_page_to_fill_the_sheet(window, tmp_path):
    source = str(tmp_path / "wide.pdf")
    doc = pymupdf.open()
    doc.new_page(width=792, height=612).draw_rect(pymupdf.Rect(0, 0, 792, 612), fill=(0, 0, 0))
    doc.save(source)
    doc.close()
    win = window()
    view = win.open_path(source)
    out = str(tmp_path / "out.pdf")
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(out)
    assert win._print_pages(view.document, printer) is None
    with pymupdf.open(out) as result:
        page = result[0]
        assert page.rect.height > page.rect.width
        # The black page should cover most of the portrait sheet rather than a band at the top.
        pix = page.get_pixmap(dpi=20)
        dark = sum(1 for i in range(0, len(pix.samples), pix.n) if pix.samples[i] < 80)
        assert dark / (pix.width * pix.height) > 0.6


def test_printer_failure_is_reported(window, tmp_path):
    win = window()
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(tmp_path / "no" / "such" / "folder" / "out.pdf"))
    assert win._print_pages(view.document, printer)


# Settings
@pytest.mark.parametrize(
    "bad",
    [
        {"recent": 5},
        {"recent": [1, 2]},
        {"geometry": 7},
        {"theme": 3},
        {"views": "x"},
    ],
)
def test_wrong_settings_types_dont_stop_the_app(qapp, tmp_path, bad):
    home = tmp_path / "home"
    home.mkdir()
    (home / "settings.json").write_text(json.dumps(bad), encoding="utf-8")
    win = MainWindow([], home=str(home))
    win.close()


def test_bad_plugin_state_doesnt_stop_the_app(qapp, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "plugins.json").write_text(json.dumps({"disabled": 3, "approved": []}), encoding="utf-8")
    win = MainWindow([], home=str(home))
    win.close()


@pytest.mark.parametrize("settings_text", ['{"speed": "fast"}', '{"positions": 3}', '{"voice": 5}', '{"speed": 900}'])
def test_bad_read_aloud_settings_dont_disable_it(qapp, tmp_path, settings_text):
    home = tmp_path / "home"
    data = home / "plugin-data" / "read_aloud"
    data.mkdir(parents=True)
    (data / "settings.json").write_text(settings_text, encoding="utf-8")
    win = MainWindow([PLUGINS], home=str(home))
    plugin = win.plugins.plugins["read_aloud"]
    assert plugin.active, plugin.error
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    assert plugin.module._controller._saved_position(view.document) is None
    win.close()


# Export
def make_wav(path, seconds=0.5, rate=24000):
    samples = (numpy.sin(numpy.arange(int(seconds * rate)) * 0.05) * 20000).astype(numpy.int16)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(samples.tobytes())
    return str(path)


def export_module():
    win_module = "read_aloud_export_test"
    if win_module not in sys.modules:
        package = importlib.util.spec_from_file_location("read_aloud_pkg", os.path.join(PLUGINS, "read_aloud", "__init__.py"), submodule_search_locations=[os.path.join(PLUGINS, "read_aloud")])
        module = importlib.util.module_from_spec(package)
        sys.modules["read_aloud_pkg"] = module
        package.loader.exec_module(module)
        sys.modules[win_module] = sys.modules["read_aloud_pkg.export"]
    return sys.modules[win_module]


def test_mp3_encoder_makes_a_real_mp3(qapp, tmp_path):
    export = export_module()
    wav = make_wav(tmp_path / "a.wav", 1.0)
    out = tmp_path / "o.mp3"
    assert export.encode_mp3([(wav, 0.35), (wav, 0)], str(out))
    data = out.read_bytes()
    # MP3 frames start with eleven set bits. 2.35 seconds at 128 kbps is about 37 KB.
    assert data[0] == 0xFF and data[1] & 0xE0 == 0xE0
    assert 25_000 < len(data) < 50_000
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_stopping_the_encoder_leaves_nothing_behind(qapp, tmp_path):
    export = export_module()
    wav = make_wav(tmp_path / "a.wav")
    out = tmp_path / "o.mp3"
    assert export.encode_mp3([(wav, 0)], str(out), lambda: True) is False
    assert not out.exists()
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_canceling_export_shows_no_error(window, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: calls.append(a[2])))
    win = window([PLUGINS])
    module = win.plugins.plugins["read_aloud"].module
    export = sys.modules[module.__name__ + ".export"]
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    job = export.Mp3Export(module.api_for_check(), view.document, [0], "bf_emma", 1.0, str(tmp_path / "o.mp3"), str(tmp_path), False)
    job._cancel()
    job._cancel()
    job._on_encoded("failure after canceling")
    QApplication.processEvents()
    assert not calls


# Playback
class FakeSink:
    """Stands in for the sound device: plays whatever it's given at real speed, on demand."""

    def __init__(self, rate=24000):
        self.rate = rate
        self.received = bytearray()
        self.processed = 0
        self.stopped = self.suspended = False
        self.starts = 0

    def setBufferSize(self, size):
        self.size = size

    def setVolume(self, volume):
        self.volume = volume

    def start(self):
        self.starts += 1
        return self

    def write(self, data):
        self.received.extend(data)
        return len(data)

    def bytesFree(self):
        return self.size - (len(self.received) - self.processed)

    def processedUSecs(self):
        return self.processed * 1_000_000 // (self.rate * 2)

    def advance(self, seconds):
        self.processed = min(len(self.received), self.processed + int(self.rate * 2 * seconds))

    def stop(self):
        self.stopped = True

    def suspend(self):
        self.suspended = True

    def resume(self):
        self.suspended = False


def sentence_player(qapp):
    export_module()
    player_module = sys.modules.get("read_aloud_pkg.player")
    if player_module is None:
        import importlib

        player_module = importlib.import_module("read_aloud_pkg.player")
    sink = FakeSink()
    player = player_module.SentencePlayer(sink_factory=lambda fmt, device: sink)
    # Test machines may have no sound device, and these tests don't need one.
    player.setDevice(object())
    return player, sink


def run_player(player, sink, seconds):
    for _ in range(int(seconds / 0.01)):
        player._tick()
        sink.advance(0.01)


def test_the_stream_stays_open_across_sentences(qapp, tmp_path):
    from PySide6.QtCore import QUrl

    player, sink = sentence_player(qapp)
    ended = []
    player.mediaStatusChanged.connect(ended.append)
    player.setSource(QUrl.fromLocalFile(make_wav(tmp_path / "a.wav", 0.5)))
    player.play()
    run_player(player, sink, 0.2)
    assert not ended
    assert player.position() > 0
    run_player(player, sink, 0.8)
    assert len(ended) == 1
    # Between sentences the stream keeps going, carrying silence.
    before = len(sink.received)
    run_player(player, sink, 0.4)
    assert len(sink.received) > before and not any(sink.received[before:])
    player.setSource(QUrl.fromLocalFile(make_wav(tmp_path / "b.wav", 0.3)))
    player.play()
    run_player(player, sink, 1.0)
    assert len(ended) == 2
    assert sink.starts == 1 and not sink.stopped
    player.stop()
    assert sink.stopped


def test_pausing_holds_the_position(qapp, tmp_path):
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QMediaPlayer

    player, sink = sentence_player(qapp)
    player.setSource(QUrl.fromLocalFile(make_wav(tmp_path / "a.wav", 0.5)))
    player.play()
    run_player(player, sink, 0.1)
    player.pause()
    assert sink.suspended and player.playbackState() == QMediaPlayer.PausedState
    player.play()
    assert not sink.suspended and player.playbackState() == QMediaPlayer.PlayingState


def test_a_missing_audio_file_reports_an_error(qapp, tmp_path):
    from PySide6.QtCore import QUrl

    player, _sink = sentence_player(qapp)
    errors = []
    player.errorOccurred.connect(lambda _e, text: errors.append(text))
    player.setSource(QUrl.fromLocalFile(str(tmp_path / "missing.wav")))
    assert errors


def test_a_computer_with_no_sound_output_gets_a_clear_message(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QAudioDevice, QMediaDevices, QMediaPlayer

    player, _sink = sentence_player(qapp)
    player.setDevice(None)
    monkeypatch.setattr(QMediaDevices, "defaultAudioOutput", staticmethod(lambda: QAudioDevice()))
    errors = []
    player.errorOccurred.connect(lambda _e, text: errors.append(text))
    player.setSource(QUrl.fromLocalFile(make_wav(tmp_path / "a.wav", 0.2)))
    player.play()
    assert errors == ["No sound output was found."]
    assert player.playbackState() == QMediaPlayer.StoppedState


def test_pauses_suit_what_just_ended():
    from reading_corpus import load_textmodel

    module = load_textmodel()
    sentence = module.Chunk("It works well.", 0, 0, 0, 0)
    heading = module.Chunk("Chapter One.", 0, 0, 0, 0, heading=True)
    clause = module.Chunk("and then it carried on, with", 0, 0, 0, 0)
    assert module.pause_after(heading) > module.pause_after(sentence) > module.pause_after(clause) > 0
    assert module.pause_after(sentence, 2.0) == pytest.approx(module.pause_after(sentence) / 2)


def test_resuming_in_a_pause_goes_on_to_the_next_sentence(window, tmp_path):
    win = window([PLUGINS])
    controller = win.plugins.plugins["read_aloud"].module._controller
    controller.audio.setVolume(0)
    controller.synth.set_jobs = lambda jobs: None
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    controller.read_from(view.document, 0)
    for _ in range(6):
        controller._build_tick()
    controller.state = "playing"
    controller._pause_timer.start(5000)
    first = controller.index
    controller.pause()
    assert controller.state == "paused"
    controller.resume()
    assert controller.index == first + 1
    controller.stop()


def test_changing_speed_makes_new_audio(window, tmp_path):
    win = window([PLUGINS])
    controller = win.plugins.plugins["read_aloud"].module._controller
    controller.audio.setVolume(0)
    controller.synth.set_jobs = lambda jobs: None
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    controller.read_from(view.document, 0)
    for _ in range(6):
        controller._build_tick()
    chunk = controller.chunks[0]
    slow = controller._job(chunk).path
    controller.set_speed(1.5)
    assert controller._job(chunk).speed == 1.5 and controller._job(chunk).path != slow
    controller.set_speed(1.0)
    controller.stop()


def test_export_speed_gets_its_own_audio():
    export_module()
    tts = sys.modules["read_aloud_pkg.tts"]
    assert tts.audio_path("c", "v", "t") != tts.audio_path("c", "v", "t", 1.5)
    assert tts.Job("c", "v", "t", 1.5).speed == 1.5


# Controls
def test_changing_voice_while_paused_doesnt_resume_in_the_old_voice(window, tmp_path):
    win = window([PLUGINS])
    controller = win.plugins.plugins["read_aloud"].module._controller
    controller.audio.setVolume(0)
    controller.synth.set_jobs = lambda jobs: None
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    controller.read_from(view.document, 0)
    controller.pause()
    stops = []
    original = controller.player.stop
    controller.player.stop = lambda: (stops.append(1), original())
    controller.set_voice("George")
    assert stops
    controller.stop()


def test_a_long_scanned_pdf_says_so_early(window, tmp_path):
    path = str(tmp_path / "scan.pdf")
    doc = pymupdf.open()
    for _ in range(8):
        doc.new_page()
    doc.save(path)
    doc.close()
    win = window([PLUGINS])
    controller = win.plugins.plugins["read_aloud"].module._controller
    view = win.open_path(path)
    messages = []
    controller.message.connect(messages.append)
    controller.read_from(view.document, 0)
    for _ in range(5):
        controller._build_tick()
    assert any("OCR" in m for m in messages)
    controller.stop()


def test_self_check_doesnt_use_real_settings():
    source = open(os.path.join(ROOT, "pdfdesk", "selfcheck.py"), encoding="utf-8").read()
    assert "APP_HOME" not in source
    assert "shutil.rmtree(folder" in source


def test_the_license_is_in_place():
    from pdfdesk.main_window import about_text

    text = open(os.path.join(ROOT, "LICENSE"), encoding="utf-8").read()
    assert text.lstrip().startswith("GNU AFFERO GENERAL PUBLIC LICENSE")
    assert "Remote Network Interaction" in text and "END OF TERMS AND CONDITIONS" in text
    about = about_text()
    assert "Affero" in about and "NO WARRANTY" in about and "source" in about
    script = open(os.path.join(ROOT, "installer", "pdfdesk.iss"), encoding="utf-8").read()
    assert "LicenseFile=..\\LICENSE" in script and "PDFDesk-source-" in script
    spec = open(os.path.join(ROOT, "PDFDesk.spec"), encoding="utf-8").read()
    assert '("LICENSE", ".")' in spec and '("licenses", "licenses")' in spec


def test_version_in_the_installer_matches_the_app():
    from pdfdesk import __version__

    script = open(os.path.join(ROOT, "installer", "pdfdesk.iss"), encoding="utf-8").read()
    assert f"AppVersion={__version__}\n" in script.replace("\r\n", "\n")
    assert f"PDFDesk-source-{__version__}.zip" in script


def test_license_menu_opens_a_readable_copy(window, monkeypatch):
    opened = []
    monkeypatch.setattr("pdfdesk.main_window.QDesktopServices.openUrl", staticmethod(lambda url: opened.append(url.toLocalFile())))
    win = window()
    win._show_file("LICENSE")
    assert opened[0].endswith("LICENSE.txt") and os.path.exists(opened[0])
    assert "AFFERO" in open(opened[0], encoding="utf-8").read()


def test_third_party_notices_cover_the_copyleft_parts():
    text = open(os.path.join(ROOT, "THIRD_PARTY_NOTICES.md"), encoding="utf-8").read()
    for name in ("PyMuPDF", "phonemizer", "espeak-ng", "PySide6", "Kokoro", "lameenc", "Tesseract", "ONNX Runtime"):
        assert name in text, name
