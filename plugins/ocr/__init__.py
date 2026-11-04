import os

import pymupdf
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QProgressDialog

OCR_DPI = 300
TESSDATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tessdata")


def make_searchable(document, out_path, on_page=None, language="eng"):
    """Write a copy where every page without text gets a recognized text layer."""
    with pymupdf.open() as output:
        for index in range(len(document)):
            if on_page and on_page(index) is False:
                return False
            page = document.page(index)
            if page.get_text("text").strip():
                output.insert_pdf(document.doc, from_page=index, to_page=index)
                continue
            pix = page.get_pixmap(dpi=OCR_DPI)
            data = pix.pdfocr_tobytes(language=language, tessdata=TESSDATA)
            with pymupdf.open("pdf", data) as recognized:
                output.insert_pdf(recognized)
        output.save(out_path, garbage=3, deflate=True)
    return True


def activate(api):
    def run():
        document = api.current_document()
        if document is None:
            api.status("Open a PDF first.")
            return
        stem = os.path.splitext(document.title)[0]
        out, _ = QFileDialog.getSaveFileName(api.window, "Save searchable copy", f"{stem} (searchable).pdf", "PDF files (*.pdf)")
        if not out:
            return
        progress = QProgressDialog("Recognizing text...", "Cancel", 0, len(document), api.window)
        progress.setWindowTitle("OCR")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        def on_page(index):
            progress.setValue(index)
            progress.setLabelText(f"Recognizing page {index + 1} of {len(document)}...")
            QApplication.processEvents()
            return not progress.wasCanceled()

        try:
            finished = make_searchable(document, out, on_page)
        except Exception as e:
            progress.close()
            QMessageBox.warning(api.window, "OCR", f"OCR failed.\n\n{e}")
            return
        progress.close()
        if finished:
            api.window.open_path(out)

    api.add_action("Tools", "Make Searchable (OCR)...", run)
