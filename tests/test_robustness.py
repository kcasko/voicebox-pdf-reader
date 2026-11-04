import json
import logging
import os
import subprocess
import sys
import time
from unittest import mock

import pymupdf
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QRect
from PySide6.QtWidgets import QApplication, QMessageBox

from pdfdesk.document import PasswordRequired, PdfDocument
from pdfdesk.main_window import MainWindow, PluginDialog, fit_rect
from pdfdesk.panels import THUMB_MAX_HEIGHT, THUMB_WIDTH, thumb_size


@pytest.fixture
def window(qapp, tmp_path):
    made = []

    def factory(folders=None):
        win = MainWindow(folders or [], home=str(tmp_path / "home"))
        made.append(win)
        return win

    yield factory
    for win in made:
        for view in win.views():
            view.document.dirty = False
        win.close()


@pytest.fixture
def warnings(monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    return shown


def simple_pdf(path, pages=2):
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 100), f"Page {i + 1}")
    data = doc.tobytes()
    doc.close()
    with open(path, "wb") as f:
        f.write(data)
    return str(path)


def damage_page_tree(path, tmp_path):
    """Keep the file parseable but make the page tree point at something that isn't a page."""
    doc = pymupdf.open(path)
    pages = doc.xref_get_key(doc.pdf_catalog(), "Pages")[1].split()[0]
    doc.xref_set_key(int(pages), "Kids", "[1 0 R 1 0 R]")
    bad = str(tmp_path / "bad_tree.pdf")
    doc.save(bad)
    doc.close()
    return bad


# Opening
@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not a pdf",
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 200,
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
        b"trailer<</Root 1 0 R/Size 3>>\n%%EOF\n",
    ],
    ids=["empty", "garbage", "png", "no_pages"],
)
def test_unusable_files_report_and_leave_no_tab(window, warnings, tmp_path, content):
    path = tmp_path / "bad.pdf"
    path.write_bytes(content)
    win = window()
    assert win.open_path(str(path)) is None
    assert warnings
    assert win.tabs.count() == 0
    assert not win.settings.get("recent")


def test_real_image_named_pdf_is_rejected(window, warnings, tmp_path):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), False)
    path = str(tmp_path / "image.pdf")
    pix.save(path, output="png")
    assert window().open_path(path) is None
    assert warnings


def test_failure_while_laying_out_pages_reports(window, warnings, tmp_path):
    path = simple_pdf(tmp_path / "ok.pdf")
    win = window()
    with mock.patch("pdfdesk.main_window.PdfView", side_effect=RuntimeError("code=7: malformed page tree")):
        assert win.open_path(path) is None
    assert "malformed page tree" in warnings[0]
    assert win.tabs.count() == 0
    # The failed attempt must not keep the file open.
    os.rename(path, path + ".moved")


# Saving protected files
def protected(tmp_path, **options):
    path = str(tmp_path / "protected.pdf")
    with pymupdf.open(simple_pdf(tmp_path / "plain.pdf")) as doc:
        doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, **options)
    return path


def test_save_keeps_owner_restrictions(qapp, tmp_path):
    path = protected(tmp_path, owner_pw="owner", user_pw="", permissions=pymupdf.PDF_PERM_ACCESSIBILITY)
    with pymupdf.open(path) as doc:
        permissions = doc.permissions
    document = PdfDocument(path)
    document.add_note(0, (100, 100), "note")
    document.save()
    document.close()
    with pymupdf.open(path) as doc:
        assert doc.metadata["encryption"]
        assert doc.permissions == permissions
        assert doc.authenticate("owner")
        assert len(list(doc[0].annots())) == 1


def test_save_keeps_a_separate_owner_password(qapp, tmp_path):
    path = protected(tmp_path, owner_pw="owner", user_pw="secret")
    document = PdfDocument(path, password="secret")
    document.add_note(0, (100, 100), "note")
    document.save()
    document.close()
    with pymupdf.open(path) as doc:
        assert doc.needs_pass
        assert doc.authenticate("owner")


def test_undo_then_save_keeps_protection(qapp, tmp_path):
    path = protected(tmp_path, owner_pw="owner", user_pw="secret")
    document = PdfDocument(path, password="secret")
    document.add_note(0, (100, 100), "one")
    document.add_note(0, (120, 100), "two")
    document.undo()
    assert len(list(document.page(0).annots())) == 1
    document.save()
    document.close()
    with pytest.raises(PasswordRequired):
        PdfDocument(path)


def test_changing_and_removing_the_password_still_work(qapp, tmp_path):
    path = protected(tmp_path, owner_pw="owner", user_pw="secret")
    document = PdfDocument(path, password="secret")
    document.password = "changed"
    # An edit before saving has to survive a snapshot taken under the old password.
    document.add_note(0, (100, 100), "note")
    document.undo()
    document.save()
    with pytest.raises(PasswordRequired):
        PdfDocument(path, password="secret")
    document.password = None
    document.save()
    document.close()
    with pymupdf.open(path) as doc:
        assert not doc.needs_pass
        assert not doc.metadata["encryption"]


# Thumbnails
@pytest.mark.parametrize("size", [(612, 792), (2, 14400), (14400, 2), (0, 0)])
def test_thumbnail_size_is_always_bounded(size):
    result = thumb_size(*size)
    assert 0 < result.width() <= THUMB_WIDTH
    assert 0 < result.height() <= THUMB_MAX_HEIGHT


def test_thumbnails_render_only_what_is_painted(window, tmp_path):
    path = simple_pdf(tmp_path / "long.pdf", pages=200)
    win = window()
    win.resize(1000, 700)
    win.show()
    win.open_path(path)
    panel = win.thumbnails
    for _ in range(200):
        QApplication.processEvents()
    assert panel.count() == 200
    assert 0 < len(panel._cache) < 30


def test_thumbnails_survive_a_tab_switch(window, tmp_path):
    win = window()
    win.resize(1000, 700)
    win.show()
    first = win.open_path(simple_pdf(tmp_path / "a.pdf"))
    for _ in range(50):
        QApplication.processEvents()
    assert (first.document, 0) in win.thumbnails._cache
    cached = win.thumbnails._cache[(first.document, 0)]
    win.open_path(simple_pdf(tmp_path / "b.pdf"))
    win.tabs.setCurrentWidget(first)
    assert win.thumbnails._cache[(first.document, 0)] is cached


def test_thumbnails_refresh_after_a_change_and_forget_closed_documents(window, tmp_path):
    win = window()
    win.resize(1000, 700)
    win.show()
    view = win.open_path(simple_pdf(tmp_path / "a.pdf"))
    for _ in range(50):
        QApplication.processEvents()
    document = view.document
    document.add_note(0, (100, 100), "note")
    assert (document, 0) not in win.thumbnails._cache
    for _ in range(50):
        QApplication.processEvents()
    assert (document, 0) in win.thumbnails._cache
    document.dirty = False
    win.close_tab(win.tabs.indexOf(view))
    assert not [key for key in win.thumbnails._cache if key[0] is document]


def test_a_tiny_file_with_extreme_pages_stays_small(window, tmp_path):
    doc = pymupdf.open()
    for _ in range(50):
        doc.new_page(width=2, height=14400)
    path = str(tmp_path / "tall.pdf")
    doc.save(path)
    doc.close()
    win = window()
    win.resize(1000, 700)
    win.show()
    win.open_path(path)
    for _ in range(100):
        QApplication.processEvents()
    assert sum(p.width() * p.height() * 4 for p in win.thumbnails._cache.values()) < 10 * 1024 * 1024


# Window size
@pytest.mark.parametrize(
    "frame",
    [QRect(0, 0, 1700, 1100), QRect(-50, -50, 800, 600), QRect(5000, 900, 800, 600), QRect(100, 100, 3000, 3000)],
)
def test_window_rectangle_fits_the_screen(frame):
    available = QRect(0, 0, 1536, 816)
    assert available.contains(fit_rect(frame, available))


def test_window_that_already_fits_is_left_alone():
    frame = QRect(100, 100, 800, 600)
    assert fit_rect(frame, QRect(0, 0, 1536, 816)) == frame


def test_fit_rect_respects_a_second_screen_to_the_left():
    available = QRect(-1536, 0, 1536, 816)
    assert available.contains(fit_rect(QRect(-1400, 200, 1360, 880), available))


# Plugins
def write_plugin(root, folder, manifest, body="def activate(api):\n    pass\n"):
    path = root / folder
    path.mkdir(parents=True)
    (path / "plugin.json").write_text(json.dumps(manifest) if not isinstance(manifest, str) else manifest)
    (path / "__init__.py").write_text(body)


BAD_MANIFESTS = {
    "id_list": {"id": ["x"]},
    "id_int": {"id": 5},
    "id_traversal": {"id": "..\\..\\escaped"},
    "id_missing": {"name": "nope"},
    "name_int": {"id": "name_int", "name": 123},
    "description_dict": {"id": "description_dict", "description": {"a": 1}},
    "version_list": {"id": "version_list", "version": []},
    "not_an_object": [1, 2],
    "not_json": "{nope",
}


@pytest.mark.parametrize("manifest", BAD_MANIFESTS.values(), ids=BAD_MANIFESTS.keys())
def test_bad_manifest_never_runs_and_never_blocks_the_app(window, tmp_path, manifest):
    root = tmp_path / "plugins"
    marker = tmp_path / "ran.txt"
    write_plugin(root, "bad", manifest, f"open({str(marker)!r}, 'w').close()\ndef activate(api):\n    pass\n")
    win = window([str(root)])
    assert list(win.plugins.plugins) == ["bad"]
    info = win.plugins.plugins["bad"]
    assert info.invalid and "Bad plugin.json" in info.error
    win.plugins.set_enabled("bad", True)
    assert not info.active and not marker.exists()
    dialog = PluginDialog(win.plugins, win)
    assert dialog.table.rowCount() == 1
    assert not dialog.table.item(0, 0).flags()
    dialog.close()
    assert not os.path.exists(tmp_path / "escaped")


def test_plugin_calling_sys_exit_does_not_stop_the_app(window, tmp_path):
    root = tmp_path / "plugins"
    write_plugin(root, "quits", {"id": "quits"}, "import sys\nsys.exit(3)\n")
    write_plugin(root, "quits_later", {"id": "quits_later"}, "import sys\ndef activate(api):\n    sys.exit(3)\n")
    write_plugin(
        root,
        "quits_on_event",
        {"id": "quits_on_event"},
        "import sys\ndef activate(api):\n    api.on('document_opened', lambda d: sys.exit(3))\n",
    )
    win = window([str(root)])
    assert "SystemExit" in win.plugins.plugins["quits"].error
    assert "SystemExit" in win.plugins.plugins["quits_later"].error
    assert win.open_path(simple_pdf(tmp_path / "a.pdf")) is not None
    assert "SystemExit" in win.plugins.plugins["quits_on_event"].error


def test_long_plugin_text_is_clipped_in_the_manager(window, tmp_path):
    root = tmp_path / "plugins"
    write_plugin(root, "long", {"id": "long", "name": "N" * 300, "version": "9" * 100, "description": "D" * 9000})
    dialog = PluginDialog(window([str(root)]).plugins, None)
    assert len(dialog.table.item(0, 1).text()) <= 60
    assert len(dialog.table.item(0, 2).text()) <= 20
    assert len(dialog.table.item(0, 3).text()) <= 500


# Links
@pytest.mark.parametrize(
    "uri,allowed",
    [
        ("https://example.com/", True),
        ("HTTP://example.com/", True),
        ("mailto:a@example.com", True),
        ("ms-msdt:/id PCWDiagnostic", False),
        ("search-ms:query=x", False),
        ("file:///C:/Windows/System32/calc.exe", False),
        ("calc.exe", False),
    ],
)
def test_only_web_and_email_links_can_open(window, tmp_path, monkeypatch, uri, allowed):
    view = window().open_path(simple_pdf(tmp_path / "a.pdf"))
    asked, blocked = [], []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: blocked.append(a[2]))
    with mock.patch("PySide6.QtGui.QDesktopServices.openUrl") as opened:
        view._follow_link({"kind": pymupdf.LINK_URI, "uri": uri})
    assert opened.called == allowed
    assert bool(asked) == allowed
    assert bool(blocked) != allowed


# Logging and the crash dialog
def test_unhandled_error_is_logged_and_shown_once(qapp, tmp_path, monkeypatch):
    from pdfdesk import logs

    hook, handlers = sys.excepthook, list(logging.getLogger().handlers)
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a[2]))
    logs._shown.clear()
    path = logs.setup(str(tmp_path))
    try:
        for _ in range(2):
            try:
                raise RuntimeError("boom in a slot")
            except RuntimeError:
                sys.excepthook(*sys.exc_info())
        for handler in logging.getLogger().handlers:
            handler.flush()
        with open(path, encoding="utf-8") as f:
            text = f.read()
        assert text.count("boom in a slot") >= 2 and "Traceback" in text
        assert len(shown) == 1 and path in shown[0]
    finally:
        sys.excepthook = hook
        for handler in logging.getLogger().handlers[:]:
            if handler not in handlers:
                logging.getLogger().removeHandler(handler)
                handler.close()
        from PySide6.QtCore import qInstallMessageHandler

        qInstallMessageHandler(None)


# Single instance
def test_second_launch_hands_over_paths(qapp, tmp_path):
    from pdfdesk.single_instance import InstanceServer, send_to_running

    home = str(tmp_path)
    assert not send_to_running(home, ["a.pdf"])
    server = InstanceServer(home)
    received = []
    server.paths_received.connect(received.append)
    # A real second launch is another process, so nothing here gets to pump the sender's events.
    sender = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; from PySide6.QtCore import QCoreApplication; app = QCoreApplication([]);"
            "from pdfdesk.single_instance import send_to_running;"
            "sys.exit(0 if send_to_running(sys.argv[1], [sys.argv[2]]) else 1)",
            home,
            str(tmp_path / "a.pdf"),
        ],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    deadline = time.monotonic() + 15
    while sender.poll() is None and time.monotonic() < deadline:
        QApplication.processEvents()
    assert sender.returncode == 0
    deadline = time.monotonic() + 5
    while not received and time.monotonic() < deadline:
        QApplication.processEvents()
    assert received == [[str(tmp_path / "a.pdf")]]
    server.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
