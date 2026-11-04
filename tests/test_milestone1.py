import json
import os
import sys

import pymupdf
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reading_corpus import CASES, load_textmodel, score, spoken_words

from pdfdesk.document import PdfDocument
from pdfdesk.main_window import MainWindow, PluginDialog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS = os.path.join(ROOT, "plugins")
tm = load_textmodel()


@pytest.fixture
def window(qapp, tmp_path):
    windows = []

    def make(folders=None, home=None):
        win = MainWindow(folders or [], home=home or str(tmp_path / "home"))
        win.show()
        windows.append(win)
        return win

    yield make
    for win in windows:
        for view in win.views():
            view.document.dirty = False
        win.close()
    QApplication.processEvents()


@pytest.fixture
def reader(window):
    win = window([PLUGINS])
    plugin = win.plugins.plugins["read_aloud"]
    assert plugin.active, plugin.error
    controller = plugin.module._controller
    controller.audio.setVolume(0)
    # Tests look at decisions, so no voices are loaded and nothing plays.
    controller.synth.set_jobs = lambda jobs: None
    return win, controller, plugin.module._panel


def multi_page(path, pages=5):
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 90), f"This is the sentence that sits on page number {i + 1} of this file.", fontsize=11)
    doc.save(path)
    doc.close()
    return str(path)


def build(document, skip=False):
    builder = tm.ChunkBuilder(document, frozenset(), skip)
    for index in range(len(document)):
        builder.feed(index)
    return builder.finish()


# Reading accuracy
@pytest.mark.parametrize("name", CASES)
def test_generated_cases_read_correctly(qapp, tmp_path, name):
    path = str(tmp_path / f"{name}.pdf")
    expected = CASES[name](path)
    document = PdfDocument(path)
    actual = spoken_words(document)
    document.close()
    assert score(expected, actual) >= 0.97, actual


def test_columns_keep_highlight_rectangles_with_their_words(qapp, tmp_path):
    path = str(tmp_path / "c.pdf")
    CASES["right_first"](path)
    document = PdfDocument(path)
    chunks = build(document)
    first = chunks[0]
    assert first.text.startswith("The study began")
    # The left column's sentence is highlighted on the left of the page.
    assert max(r[2] for r in first.rects[0]) < 300
    document.close()


def test_a_word_is_found_when_reading_order_differs_from_file_order(qapp, tmp_path):
    path = str(tmp_path / "c.pdf")
    CASES["right_first"](path)
    document = PdfDocument(path)
    chunks = build(document)
    word = next(w for w in document.words(0) if w.text == "volunteers")
    found = tm.first_chunk_at(chunks, 0, word.index)
    assert "volunteers" in chunks[found].text
    document.close()


def test_short_list_columns_are_not_treated_as_prose(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100, "Name"), (120, "Address")]]))
    assert [c.text for c in build(document)] == ["Name Address"]


@pytest.mark.parametrize(
    "text, spoken",
    [
        ("It cost $5.", "It cost 5 dollars."),
        ("It cost $1.", "It cost 1 dollar."),
        ("It cost $1.50 today.", "It cost 1 dollar and 50 cents today."),
        ("Raised $5M in all.", "Raised 5 million dollars in all."),
        ("Raised $1.5 billion in all.", "Raised 1.5 billion dollars in all."),
        ("Paid £3.20 there.", "Paid 3 pounds and 20 pence there."),
        ("Due 12/25/2024 now.", "Due December 25, 20 24 now."),
        ("Due 25/12/2024 now.", "Due December 25, 20 24 now."),
        ("Due 2024-03-04 now.", "Due March 4, 20 24 now."),
        ("On March 4, 1999 it began.", "On March 4, 19 99 it began."),
        ("At 5:00 today.", "At 5 o'clock today."),
        ("At 5:05 pm today.", "At 5 oh 5 P M today."),
        ("Ratio 45:90 here.", "Ratio 45:90 here."),
        ("Pages 10–20 here.", "Pages 10 to 20 here."),
        ("See p. 12 and Fig. 3 here.", "See page 12 and figure 3 here."),
        ("We use C++ here.", "We use C plus plus here."),
        ("Cats vs. dogs, e.g., here.", "Cats versus dogs, for example here."),
    ],
)
def test_numbers_and_short_forms_are_spoken_naturally(text, spoken):
    assert tm.spoken_text(text) == spoken


def test_references_are_only_removed_when_asked():
    text = "It works [3] well (Lee, 2019)."
    assert tm.spoken_text(text) == text
    assert tm.spoken_text(text, True) == "It works well."
    assert tm.spoken_text("See https://a.example/b for more.", True) == "See a link for more."
    assert tm.spoken_text("17", True) == ""
    assert tm.spoken_text("Pads: control the sounds -") == "Pads: control the sounds"
    # A figure in brackets that isn't a citation stays.
    assert tm.spoken_text("The total (about 2019 people) grew.", True) == "The total (about 2019 people) grew."


def test_a_sentence_that_is_only_a_link_is_dropped(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100, "https://example.com/page")]]))
    assert build(document, skip=True) == []
    assert len(build(document, skip=False)) == 1


def test_numbered_list_items_stay_together(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100, "1. First numbered item without a period"), (114, "2. Second numbered item without a period")]]))
    assert [c.text for c in build(document)] == ["1. First numbered item without a period", "2. Second numbered item without a period"]


def test_sentence_after_an_acronym_still_splits(qapp, pdf_factory):
    document = PdfDocument(pdf_factory([[(100, "They moved to the big cities of the U.S. The rest of them stayed behind.")]]))
    assert len(build(document)) == 2


# Read Aloud controls
def test_read_this_page_stops_at_the_end_of_the_page(reader, tmp_path):
    win, controller, panel = reader
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    panel._read_page()
    assert controller._last_page == view.current_page == 0
    controller.stop()


def test_reading_one_page_keeps_the_saved_place(reader, tmp_path):
    win, controller, panel = reader
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    key = os.path.normcase(view.document.path)
    controller.api.settings["positions"] = {key: [3, 0]}
    panel._read_page()
    assert controller._save_position() is False
    assert controller.api.settings["positions"][key] == [3, 0]
    controller.stop()


def test_play_reads_the_visible_page_and_offers_the_way_back(reader, tmp_path):
    win, controller, panel = reader
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    controller.api.settings["positions"] = {os.path.normcase(view.document.path): [0, 0]}
    view._current_page = 4
    offers = []
    controller.resume_offered.connect(offers.append)
    controller.play_saved_or_current()
    assert controller._seek == (4, 0)
    assert offers[-1] == 0
    assert not panel.resume_button.isHidden()
    controller.resume_offer()
    assert controller._seek == (0, 0)
    assert offers[-1] == -1
    controller.stop()


def test_play_resumes_when_you_are_still_near_your_place(reader, tmp_path):
    win, controller, _panel = reader
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    controller.api.settings["positions"] = {os.path.normcase(view.document.path): [1, 0]}
    view._current_page = 2
    controller.play_saved_or_current()
    assert controller._seek == (1, 0)
    controller.stop()


def test_f5_reads_the_tab_in_front_of_you(reader, tmp_path):
    win, controller, _panel = reader
    first = win.open_path(multi_page(tmp_path / "a.pdf"))
    controller.read_from(first.document, 0)
    second = win.open_path(multi_page(tmp_path / "b.pdf"))
    controller.toggle()
    assert controller.document is second.document
    controller.stop()


def test_toolbar_button_shows_the_state(reader, tmp_path):
    win, controller, _panel = reader
    action = next(a for a in win.plugin_toolbar().actions() if a.text() == "Read Aloud")
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    controller.read_from(view.document, 0)
    assert action.text() == "Pause"
    controller.pause()
    assert action.text() == "Resume"
    controller.stop()
    assert action.text() == "Read Aloud"


def test_progress_starts_near_zero(reader, tmp_path):
    win, _controller, _panel = reader
    module = win.plugins.plugins["read_aloud"].module
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    assert module.progress_through(view.document, 0, 0) == 0
    assert module.progress_through(view.document, 2, 0) == pytest.approx(0.4)
    assert module.progress_through(view.document, 2, 0.5) == pytest.approx(0.5)


def test_progress_moves_when_the_file_stores_columns_backwards(reader, tmp_path):
    win, controller, _panel = reader
    path = str(tmp_path / "c.pdf")
    CASES["right_first"](path)
    view = win.open_path(path)
    controller.read_from(view.document, 0)
    while controller.state == "waiting" and not controller._built_all:
        controller._build_tick()
    controller.index = len(controller.chunks) - 1
    assert controller.page_fraction() > 0.5
    controller.stop()


def test_audio_follows_the_default_device(reader, monkeypatch):
    _win, controller, _panel = reader
    calls = []
    monkeypatch.setattr(controller.audio, "setDevice", calls.append, raising=False)
    controller._on_outputs_changed()
    assert len(calls) == 1


def test_mp3_export_uses_exactly_the_requested_pages(reader, tmp_path):
    win, _controller, _panel = reader
    module = win.plugins.plugins["read_aloud"].module
    export = sys.modules[module.__name__ + ".export"]
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    job = export.Mp3Export(module.api_for_check(), view.document, [0, 2], "bf_emma", 1.0, str(tmp_path / "o.mp3"), str(tmp_path), False)
    job.synth.set_jobs = lambda jobs: None
    job._build_tick(), job._build_tick()
    pages = {chunk.page for chunk in job.builder.finish()}
    assert pages == {0, 2}
    job.progress.close()
    job.timer.stop()
    job.synth.close()


def test_page_text_is_not_treated_as_markup(reader, tmp_path):
    _win, _controller, panel = reader
    for label in (panel.sentence, panel.status, panel.document_label):
        assert isinstance(label, QLabel) and label.textFormat() == Qt.PlainText


def test_a_failure_further_ahead_doesnt_stop_reading(reader, tmp_path):
    win, controller, _panel = reader
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    controller.read_from(view.document, 0)
    controller._on_audio_failed("some other path", "failed")
    assert controller.state == "waiting"
    controller.stop()


# Privacy
def protected_pdf(path):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 90), "A private sentence that nobody else should hear about.", fontsize=11)
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="", owner_pw="owner", permissions=pymupdf.PDF_PERM_ACCESSIBILITY)
    doc.close()
    return str(path)


def test_protected_pdfs_keep_audio_only_while_open(reader, tmp_path):
    win, controller, _panel = reader
    view = win.open_path(protected_pdf(tmp_path / "p.pdf"))
    assert view.document.is_protected
    private = controller.cache_for(view.document)
    assert private != controller.cache_dir
    with open(os.path.join(private, "x.wav"), "wb") as f:
        f.write(b"audio")
    win.close_tab(win.tabs.indexOf(view))
    assert not os.path.exists(private)


def test_ordinary_pdfs_use_the_normal_cache(reader, tmp_path):
    win, controller, _panel = reader
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    assert not view.document.is_protected
    assert controller.cache_for(view.document) == controller.cache_dir


def test_private_audio_from_a_crash_is_removed_at_start(window, tmp_path):
    home = str(tmp_path / "home2")
    leftover = os.path.join(home, "plugin-data", "read_aloud", "cache", "private-old")
    os.makedirs(leftover)
    win = window([PLUGINS], home=home)
    assert win.plugins.plugins["read_aloud"].active
    assert not os.path.exists(leftover)


def test_clear_saved_data_removes_audio_and_places(reader, tmp_path):
    win, controller, _panel = reader
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    audio = os.path.join(controller.cache_dir, "x.wav")
    with open(audio, "wb") as f:
        f.write(b"audio")
    controller.api.settings["positions"] = {os.path.normcase(view.document.path): [1, 0]}
    controller.clear_saved_data()
    assert not os.path.exists(audio)
    assert "positions" not in controller.api.settings


def test_clear_recent_forgets_files_and_pages(window, tmp_path):
    win = window()
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    win.close_tab(win.tabs.indexOf(view))
    assert win.settings["recent"] and win.settings["views"]
    win.clear_recent()
    assert win.settings["recent"] == [] and win.settings["views"] == {}


# Reader basics
def test_page_and_zoom_are_remembered_per_file(window, tmp_path):
    path = multi_page(tmp_path / "a.pdf")
    win = window()
    view = win.open_path(path)
    view.set_zoom(1.5)
    view.go_to_page(3)
    win.close_tab(win.tabs.indexOf(view))
    view = win.open_path(path)
    assert view.current_page == 3
    assert view.zoom == pytest.approx(1.5)


def test_a_bad_remembered_view_is_ignored(window, tmp_path):
    path = multi_page(tmp_path / "a.pdf")
    win = window()
    win.settings["views"] = {os.path.normcase(path): "nonsense"}
    assert win.open_path(path) is not None


def press(view, key, modifiers=Qt.NoModifier):
    view.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, modifiers))


def test_space_scrolls_and_shift_space_goes_back(window, tmp_path):
    win = window()
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    bar = view.verticalScrollBar()
    press(view, Qt.Key_Space)
    moved = bar.value()
    assert moved > 0
    press(view, Qt.Key_Space, Qt.ShiftModifier)
    assert bar.value() < moved


def test_arrow_keys_turn_pages_when_nothing_scrolls_sideways(window, tmp_path):
    win = window()
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    view.set_fit("page")
    press(view, Qt.Key_Right)
    assert view.current_page == 1
    press(view, Qt.Key_Left)
    assert view.current_page == 0


def test_invalid_page_input_is_reset(window, tmp_path):
    win = window()
    win.open_path(multi_page(tmp_path / "a.pdf"))
    for text in ("abc", "²"):
        win.page_input.setText(text)
        win._on_page_input()
        assert win.page_input.text() == "1"


def test_actual_size_and_full_screen(window, tmp_path):
    win = window()
    view = win.open_path(multi_page(tmp_path / "a.pdf"))
    win.act_actual_size.trigger()
    assert view.zoom == 1.0
    win.act_full_screen.trigger()
    assert win.isFullScreen()
    win.act_full_screen.trigger()
    assert not win.isFullScreen()


# Plugin safety
def write_plugin(folder, plugin_id, source="def activate(api):\n    api.ran = True\n"):
    target = os.path.join(folder, plugin_id)
    os.makedirs(target)
    with open(os.path.join(target, "plugin.json"), "w", encoding="utf-8") as f:
        json.dump({"id": plugin_id, "name": plugin_id, "version": "1"}, f)
    with open(os.path.join(target, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(source)
    return target


def test_a_plugin_someone_added_stays_off_until_approved(window, tmp_path):
    home = str(tmp_path / "home3")
    folder = os.path.join(home, "plugins")
    target = write_plugin(folder, "added", "import pathlib\npathlib.Path(__file__).with_name('ran').write_text('x')\ndef activate(api):\n    pass\n")
    win = window([folder], home=home)
    info = win.plugins.plugins["added"]
    assert not info.active
    assert not os.path.exists(os.path.join(target, "ran"))
    win.plugins.set_enabled("added", True)
    assert not info.active
    win.plugins.approve("added")
    win.plugins.set_enabled("added", True)
    assert info.active


def test_approval_lapses_when_the_plugin_changes(window, tmp_path):
    home = str(tmp_path / "home4")
    folder = os.path.join(home, "plugins")
    target = write_plugin(folder, "added")
    win = window([folder], home=home)
    win.plugins.approve("added")
    assert not win.plugins.needs_approval("added")
    with open(os.path.join(target, "__init__.py"), "a", encoding="utf-8") as f:
        f.write("# changed\n")
    assert win.plugins.needs_approval("added")


def test_the_plugin_dialog_asks_before_turning_one_on(window, tmp_path, monkeypatch):
    home = str(tmp_path / "home5")
    folder = os.path.join(home, "plugins")
    write_plugin(folder, "added")
    win = window([folder], home=home)
    dialog = PluginDialog(win.plugins, win)
    answers = [QMessageBox.No, QMessageBox.Yes]
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: answers.pop(0)))
    dialog.table.item(0, 0).setCheckState(Qt.Checked)
    assert not win.plugins.plugins["added"].active
    dialog.table.item(0, 0).setCheckState(Qt.Checked)
    assert win.plugins.plugins["added"].active
    dialog.close()


def test_a_bad_plugin_icon_cant_break_theme_switching(window, tmp_path):
    folder = str(tmp_path / "plugins")
    write_plugin(folder, "bad_icon", "def activate(api):\n    api.add_action('Tools', 'x', print, icon='C:/nope.png')\n")
    win = window([folder])
    assert win.plugins.plugins["bad_icon"].active
    win.set_theme("dark")
    win.set_theme("light")


# Voices
def test_voice_threads_are_sensible():
    spec_name = "read_aloud_tts_threads"
    import importlib.util

    spec = importlib.util.spec_from_file_location(spec_name, os.path.join(PLUGINS, "read_aloud", "tts.py"))
    tts = importlib.util.module_from_spec(spec)
    sys.modules[spec_name] = tts
    spec.loader.exec_module(tts)
    assert 1 <= tts.voice_threads() <= (os.cpu_count() or 1)
