import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PDFDESK_HOME"] = tempfile.mkdtemp(prefix="pdfdesk-test-home-")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymupdf
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def make_pdf(path, pages, rotation=0):
    """Build a PDF from a list of pages, each a list of (y, text, font, size)."""
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page(width=612, height=792)
        for y, text, *style in lines:
            font = style[0] if style else "helv"
            size = style[1] if len(style) > 1 else 11
            page.insert_text((72, y), text, fontname=font, fontsize=size)
        page.set_rotation(rotation)
    doc.save(path)
    doc.close()
    return str(path)


@pytest.fixture
def pdf_factory(tmp_path):
    counter = {"n": 0}

    def factory(pages, rotation=0):
        counter["n"] += 1
        return make_pdf(tmp_path / f"doc{counter['n']}.pdf", pages, rotation)

    return factory
