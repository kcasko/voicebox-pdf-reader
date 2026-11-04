"""End-to-end check of the built-in voices, MP3 export and OCR, with the volume muted.

Separately installed ffmpeg and Tesseract are hidden, to prove the app doesn't use them.
Not part of the normal test run because it takes a few minutes. Run it directly:
    .venv\\Scripts\\python.exe tests\\live_read_aloud.py
Give a log file as the argument to run it under pythonw, as the real app runs:
    .venv\\Scripts\\pythonw.exe tests\\live_read_aloud.py results.txt
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time

LOG = sys.argv[1] if len(sys.argv) > 1 else None


def log(text):
    if LOG:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text, flush=True)


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PDFDESK_HOME"] = tempfile.mkdtemp(prefix="pdfdesk-live-")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PROBE = shutil.which("ffprobe")
os.environ["PATH"] = os.pathsep.join(
    folder
    for folder in os.environ["PATH"].split(os.pathsep)
    if not (shutil.which("ffmpeg", path=folder) or shutil.which("tesseract", path=folder))
)
assert not shutil.which("ffmpeg") and not shutil.which("tesseract")

import pymupdf
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from pdfdesk.main_window import MainWindow

SENTENCES = [
    "The first sentence is short and clear.",
    "Here is a second sentence for the reader to say.",
    "This third sentence sits right in the middle of the page.",
    "A fourth sentence keeps the audio going a little longer.",
    "The fifth sentence is the last one on this page.",
]
failures = []


def check(label, passed, detail=""):
    log(("PASS " if passed else "FAIL ") + label + (f"  ({detail})" if detail else ""))
    if not passed:
        failures.append(label)


def spin(condition, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def wait(seconds):
    spin(lambda: False, seconds)


def make_pdf(path, pages=2):
    doc = pymupdf.open()
    for number in range(pages):
        page = doc.new_page()
        page.insert_text((72, 80), f"Chapter {number + 1}", fontname="hebo", fontsize=16)
        for i, sentence in enumerate(SENTENCES):
            page.insert_text((72, 120 + i * 18), sentence, fontsize=11)
    doc.save(path)
    doc.close()


def main():
    app = QApplication([])
    folder = tempfile.mkdtemp(prefix="pdfdesk-live-docs-")
    first_pdf = os.path.join(folder, "first.pdf")
    second_pdf = os.path.join(folder, "second.pdf")
    make_pdf(first_pdf)
    make_pdf(second_pdf)

    win = MainWindow([os.path.join(ROOT, "plugins")], home=os.environ["PDFDESK_HOME"])
    win.show()
    plugin = win.plugins.plugins["read_aloud"]
    assert plugin.active, plugin.error
    controller = plugin.module._controller
    controller.audio.setVolume(0)
    messages = []
    controller.message.connect(messages.append)

    view = win.open_path(first_pdf)
    started = time.monotonic()
    controller.toggle()
    ok = spin(lambda: controller.state == "playing", 240)
    check("starts playing with built-in voices", ok, f"{time.monotonic() - started:.1f}s; last: {messages[-1] if messages else ''}")
    if not ok:
        return
    check("heading comes first", controller.chunks[0].heading and controller.chunks[0].text == "Chapter 1.")
    check("the page shows the sentence highlight", "read-aloud" in view._overlays)

    spin(lambda: controller.index >= 2 and controller.player.position() > 200, 60)
    controller.pause()
    wait(0.3)
    before = controller.player.position()
    wait(1.5)
    after = controller.player.position()
    check("Pause really stops the audio", controller.state == "paused" and before == after, f"{before}ms then {after}ms")
    index = controller.index
    controller.toggle()
    wait(0.8)
    moved = controller.player.position() != after or controller.index != index
    check("Resume carries on", controller.state in ("playing", "waiting") and moved)

    index = controller.index
    controller.next()
    spin(lambda: controller.state == "playing", 60)
    check("Next moves one sentence", controller.index == index + 1)
    controller.previous()
    spin(lambda: controller.state == "playing", 60)
    check("Previous moves one sentence", controller.index == index)

    # Rate has to actually shorten playback, not just change a label.
    controller.set_speed(2.0)
    wait(0.5)
    check("Speed applies during playback", abs(controller.player.playbackRate() - 2.0) < 0.01)
    controller.set_speed(1.0)

    old_path = controller._job(controller.chunks[controller.index]).path
    controller.set_voice("George")
    new_path = controller._job(controller.chunks[controller.index]).path
    spin(lambda: controller.state == "playing", 120)
    playing = controller.player.source().toLocalFile().replace("/", os.sep)
    check("Switching voice uses separate audio", old_path != new_path and os.path.normcase(playing) == os.path.normcase(new_path))
    controller.set_voice("Emma")
    spin(lambda: controller.state == "playing", 120)

    spot = controller.chunks[controller.index]
    win.plugins.plugins["read_aloud"].module._panel.stop()
    wait(0.4)
    check(
        "Stop cuts the audio immediately",
        controller.player.playbackState() == QMediaPlayer.StoppedState and controller.state == "idle",
    )
    check("Stop clears the highlight", "read-aloud" not in view._overlays)

    second_view = win.open_path(second_pdf)
    controller.toggle()
    spin(lambda: controller.state == "playing", 120)
    check("A different PDF starts at its own beginning", controller.document is second_view.document and controller.index == 0)
    controller.stop()

    win.tabs.setCurrentWidget(view)
    controller.toggle()
    spin(lambda: controller.state == "playing", 120)
    chunk = controller.chunks[controller.index]
    check("The first PDF resumes where it stopped", (chunk.page, chunk.word) == (spot.page, spot.word), chunk.text)
    controller.stop()

    # Going back past the resume point used to hang the old reader.
    controller.read_from(view.document, 1, 0)
    spin(lambda: controller.state == "playing", 120)
    controller.previous()
    spin(lambda: controller.state == "playing", 120)
    chunk = controller.chunks[controller.index]
    check("Previous can go back to the page before", chunk.page == 0, chunk.text)
    controller.stop()

    controller.read_from(view.document, 1, 0)
    spin(lambda: controller.state == "playing", 120)
    controller.index = len(controller.chunks) - 2
    controller.next()
    ok = spin(lambda: controller.state == "idle", 120)
    check("Reading reaches the end cleanly", ok and messages[-1] == "Finished reading.", messages[-1])
    check("Finishing clears the saved spot", not controller._saved_position(view.document))

    # Export starts from the middle of a resumed session on purpose.
    out = os.path.join(folder, "out.mp3")
    QInputDialog.getText = staticmethod(lambda *a, **k: ("1-2", True))
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out, ""))
    done = []
    QMessageBox.information = staticmethod(lambda *a, **k: done.append(a[2]))
    QMessageBox.warning = staticmethod(lambda *a, **k: done.append("WARNING: " + a[2]))
    win.plugins.plugins["read_aloud"].module._panel._export()
    ok = spin(lambda: bool(done), 240)
    probe = subprocess.run(
        [PROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    check("MP3 export works", ok and os.path.exists(out) and probe.returncode == 0, f"{done}; duration {probe.stdout.strip()}s")

    # A page that's only a picture of text.
    with pymupdf.open(first_pdf) as source:
        pix = source[0].get_pixmap(dpi=200)
    scan_path = os.path.join(folder, "scan.pdf")
    scan = pymupdf.open()
    scan.new_page(width=612, height=792).insert_image(pymupdf.Rect(0, 0, 612, 792), pixmap=pix)
    scan.save(scan_path)
    scan.close()
    scan_view = win.open_path(scan_path)
    searchable = os.path.join(folder, "searchable.pdf")
    win.plugins.plugins["ocr"].module.make_searchable(scan_view.document, searchable)
    with pymupdf.open(searchable) as result:
        recognized = " ".join(result[0].get_text().split())
    check("OCR works", SENTENCES[0] in recognized, recognized[:60])

    check("Voicebox isn't involved", "voicebox" not in " ".join(sys.modules).lower())
    view.document.dirty = False
    second_view.document.dirty = False
    win.close()
    app.processEvents()


main()
log("\nFAILED: " + ", ".join(failures) if failures else "\nAll live checks passed.")
os._exit(1 if failures else 0)
