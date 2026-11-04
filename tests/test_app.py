import json
import os
import textwrap

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from pdfdesk.main_window import MainWindow

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def write_plugin(folder, plugin_id, body):
    path = folder / plugin_id
    path.mkdir(parents=True)
    (path / "plugin.json").write_text(json.dumps({"id": plugin_id, "name": plugin_id, "version": "1"}))
    (path / "__init__.py").write_text(textwrap.dedent(body))


@pytest.fixture
def window(qapp, tmp_path):
    made = []

    def factory(folders=None):
        win = MainWindow(folders or [], home=str(tmp_path / "home"))
        win.resize(1000, 700)
        made.append(win)
        return win

    yield factory
    for win in made:
        for view in win.views():
            view.document.dirty = False
        win.close()


def click(view, pos, event_type, button=Qt.LeftButton, buttons=Qt.LeftButton):
    event = QMouseEvent(event_type, QPointF(pos), QPointF(view.viewport().mapToGlobal(pos)), button, buttons, Qt.NoModifier)
    QApplication.sendEvent(view.viewport(), event)


def drag(view, start, end):
    from PySide6.QtCore import QEvent

    click(view, start, QEvent.MouseButtonPress)
    click(view, end, QEvent.MouseMove)
    click(view, end, QEvent.MouseButtonRelease, buttons=Qt.NoButton)


def word_point(view, word):
    center = view._to_view(0, (word.rect[0] + word.rect[2]) / 2, (word.rect[1] + word.rect[3]) / 2)
    return center.toPoint()


def test_open_scroll_and_page_tracking(window, pdf_factory):
    win = window()
    view = win.open_path(pdf_factory([[(100, f"Page {i}")] for i in range(5)]))
    win.show()
    QApplication.processEvents()
    assert win.page_total.text().strip() == "/ 5"
    view.go_to_page(3)
    assert view.current_page == 3
    assert win.page_input.text() == "4"
    assert win.thumbnails.count() == 5


def test_opening_same_file_twice_reuses_the_tab(window, pdf_factory):
    win = window()
    path = pdf_factory([[(100, "Hello")]])
    assert win.open_path(path) is win.open_path(path)
    assert win.tabs.count() == 1


def test_broken_file_reports_instead_of_crashing(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: messages.append(a[2]))
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    win = window()
    assert win.open_path(str(bad)) is None
    assert messages


def test_drag_selects_and_copies_text(window, pdf_factory):
    win = window()
    view = win.open_path(pdf_factory([[(100, "Alpha Bravo Charlie Delta")]]))
    win.show()
    QApplication.processEvents()
    words = view.document.words(0)
    drag(view, word_point(view, words[1]), word_point(view, words[2]))
    assert view.selected_text() == "Bravo Charlie"
    view.copy_selection()
    assert QApplication.clipboard().text() == "Bravo Charlie"


def test_highlight_tool_marks_the_dragged_words(window, pdf_factory):
    win = window()
    view = win.open_path(pdf_factory([[(100, "Alpha Bravo Charlie Delta")]]))
    win.show()
    QApplication.processEvents()
    view.set_tool("highlight")
    words = view.document.words(0)
    drag(view, word_point(view, words[1]), word_point(view, words[2]))
    page = view.document.page(0)
    assert [a.type[1] for a in page.annots()] == ["Highlight"]
    win._undo()
    page = view.document.page(0)
    assert not list(page.annots() or [])


def test_selection_works_after_scrolling_and_zooming(window, pdf_factory):
    win = window()
    view = win.open_path(pdf_factory([[(100, "First page")], [(100, "Second page words here")]]))
    win.show()
    QApplication.processEvents()
    view.set_zoom(1.5)
    view.go_to_page(1)
    QApplication.processEvents()
    hit = view.page_at(view._to_view(1, 80, 96).toPoint())
    assert hit[0] == 1
    assert hit[1] == pytest.approx(80, abs=1)
    assert hit[2] == pytest.approx(96, abs=1)


def test_search_finds_every_page(window, pdf_factory):
    win = window()
    win.open_path(pdf_factory([[(100, "needle here")], [(100, "nothing")], [(100, "another needle")]]))
    win.search.input.setText("needle")
    win.search.start()
    for _ in range(20):
        QApplication.processEvents()
    assert win.search.results.count() == 2
    assert win.search.status.text() == "2 matches"


def test_dirty_tab_prompts_and_can_be_cancelled(window, pdf_factory, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    win = window()
    view = win.open_path(pdf_factory([[(100, "One")], [(100, "Two")]]))
    view.document.rotate_pages([0], 90)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)
    assert win.close_tab(0) is False
    assert win.tabs.count() == 1


# Plugins
def test_plugin_adds_and_removes_its_ui(window, tmp_path):
    folder = tmp_path / "plugins"
    write_plugin(
        folder,
        "demo",
        """
        from PySide6.QtWidgets import QLabel
        calls = []
        def activate(api):
            api.add_action("Demo Menu", "Do it", lambda: calls.append("run"))
            api.add_panel("Demo Panel", QLabel("hi"))
            api.on("document_opened", lambda d: calls.append(d.title))
            api.add_context_provider(lambda c: [("Demo item", lambda: None)])
        def deactivate():
            calls.append("off")
        """,
    )
    win = window([str(folder)])
    info = win.plugins.plugins["demo"]
    assert info.active
    titles = [a.text() for a in win.menuBar().actions()]
    assert "Demo Menu" in titles
    win.plugins.set_enabled("demo", False)
    assert "off" in info.module.calls
    assert "Demo Menu" not in [a.text() for a in win.menuBar().actions()]
    win.plugins.set_enabled("demo", True)
    assert "Demo Menu" in [a.text() for a in win.menuBar().actions()]


def test_disabled_plugin_stays_off_after_restart(window, tmp_path):
    folder = tmp_path / "plugins"
    write_plugin(folder, "demo", "def activate(api):\n    pass\n")
    win = window([str(folder)])
    win.plugins.set_enabled("demo", False)
    win2 = window([str(folder)])
    assert not win2.plugins.plugins["demo"].active


def test_broken_plugins_do_not_stop_the_app(window, tmp_path, pdf_factory):
    folder = tmp_path / "plugins"
    write_plugin(folder, "crash_on_load", "raise RuntimeError('bad import')\n")
    write_plugin(folder, "crash_on_activate", "def activate(api):\n    api.add_action('Half', 'x', print)\n    raise RuntimeError('bad')\n")
    write_plugin(folder, "crash_on_event", "def activate(api):\n    api.on('document_opened', lambda d: 1 / 0)\n")
    bad_manifest = folder / "bad_manifest"
    bad_manifest.mkdir()
    (bad_manifest / "plugin.json").write_text("{nope")
    win = window([str(folder)])
    assert "bad import" in win.plugins.plugins["crash_on_load"].error
    assert "bad" in win.plugins.plugins["crash_on_activate"].error
    assert "Half" not in [a.text() for a in win.menuBar().actions()]
    assert win.plugins.plugins["bad_manifest"].error
    assert win.open_path(pdf_factory([[(100, "Fine")]])) is not None
    assert "division" in win.plugins.plugins["crash_on_event"].error


def test_bundled_plugins_load(window):
    win = window([os.path.join(ROOT, "plugins")])
    for plugin_id in ("read_aloud", "ocr", "document_stats"):
        info = win.plugins.plugins[plugin_id]
        assert info.active, info.error
    assert "Make Searchable (OCR)..." in [a.text() for a in win.plugin_menu("Tools").actions()]
