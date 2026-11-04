"""Checks that a packaged build has everything it needs: PDFDesk.exe --self-check results.txt

Runs muted, using a temporary PDF. Exits with 0 only if every check passes.
"""

import os
import sys
import tempfile
import time

import pymupdf
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication, QMessageBox

from .main_window import MainWindow
from .settings import APP_HOME

TIMEOUT = 180


def _spin(condition, timeout=TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def run(results_path, plugin_folders):
    failures = []

    def check(label, passed, detail=""):
        with open(results_path, "a", encoding="utf-8") as f:
            f.write(("PASS " if passed else "FAIL ") + label + (f"  ({detail})" if detail else "") + "\n")
        if not passed:
            failures.append(label)

    folder = tempfile.mkdtemp(prefix="pdfdesk-self-check-")
    path = os.path.join(folder, "check.pdf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 80), "Chapter One", fontname="hebo", fontsize=16)
    page.insert_text((72, 120), "The first sentence is short and clear.", fontsize=11)
    page.insert_text((72, 140), "Here is a second sentence for the reader to say.", fontsize=11)
    doc.save(path)
    doc.close()

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(plugin_folders, home=APP_HOME)
    window.show()
    for plugin_id in ("read_aloud", "ocr", "document_stats"):
        info = window.plugins.plugins.get(plugin_id)
        check(f"{plugin_id} plugin loads", bool(info and info.active), info.error if info else "not found")
    view = window.open_path(path)
    check("opens a PDF", view is not None)

    controller = window.plugins.plugins["read_aloud"].module._controller
    controller.audio.setVolume(0)
    controller.toggle()
    playing = _spin(lambda: controller.state == "playing" and controller.player.position() > 100)
    check("reads aloud with built-in voices", playing)
    if playing:
        controller.pause()
        _spin(lambda: False, 0.3)
        before = controller.player.position()
        _spin(lambda: False, 1)
        check("pauses", controller.player.position() == before)
        controller.stop()
        check("stops", controller.player.playbackState() == QMediaPlayer.StoppedState)

    module = window.plugins.plugins["read_aloud"].module
    finished = []
    QMessageBox.information = staticmethod(lambda *a, **k: finished.append("ok"))
    QMessageBox.warning = staticmethod(lambda *a, **k: finished.append(a[2]))
    out = os.path.join(folder, "check.mp3")
    export_module = sys.modules[module.__name__ + ".export"]
    export_module.Mp3Export(
        module.api_for_check(), view.document, [0], "bf_emma", 1.0, out, controller.cache_dir
    ).start()
    done = _spin(lambda: bool(finished))
    check(
        "exports MP3",
        done and finished[0] == "ok" and os.path.getsize(out) > 1000,
        finished[0] if finished else "timed out",
    )

    with pymupdf.open(path) as source:
        pix = source[0].get_pixmap(dpi=200)
    scan_path = os.path.join(folder, "scan.pdf")
    scan = pymupdf.open()
    scan.new_page(width=612, height=792).insert_image(pymupdf.Rect(0, 0, 612, 792), pixmap=pix)
    scan.save(scan_path)
    scan.close()
    scan_view = window.open_path(scan_path)
    searchable = os.path.join(folder, "searchable.pdf")
    window.plugins.plugins["ocr"].module.make_searchable(scan_view.document, searchable)
    with pymupdf.open(searchable) as result:
        check("OCR recognizes text", "first sentence" in result[0].get_text())

    if getattr(sys, "frozen", False):
        outside = sorted(
            {
                name
                for name, loaded in list(sys.modules.items())
                if getattr(loaded, "__file__", None)
                and os.path.isfile(loaded.__file__)
                and not os.path.normcase(os.path.abspath(loaded.__file__)).startswith(os.path.normcase(sys._MEIPASS))
            }
        )
        check("uses only its own files", not outside, ", ".join(outside[:5]))

    with open(results_path, "a", encoding="utf-8") as f:
        f.write("ALL PASSED\n" if not failures else "FAILED: " + ", ".join(failures) + "\n")
    app.processEvents()
    # Skips interpreter teardown so a finished check can't hang on background work.
    os._exit(1 if failures else 0)
