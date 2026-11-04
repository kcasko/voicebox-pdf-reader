import os
import tempfile
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass

import pymupdf
from PySide6.QtCore import QObject, Signal

MAX_UNDO = 15
MAX_UNDO_BYTES = 500 * 1024 * 1024


class PasswordRequired(Exception):
    pass


@dataclass(frozen=True)
class Word:
    index: int
    text: str
    rect: tuple
    block: int
    line: int


def normalize_text(text):
    return unicodedata.normalize("NFKC", text).replace("\xad", "")


def line_rects(words):
    """Merge a run of words into one rectangle per text line."""
    rects, key = [], None
    for word in words:
        word_key = (word.block, word.line)
        if word_key == key and rects:
            rects[-1] = rects[-1] | pymupdf.Rect(word.rect)
        else:
            rects.append(pymupdf.Rect(word.rect))
            key = word_key
    return rects


def words_to_text(words):
    parts, key = [], None
    for word in words:
        word_key = (word.block, word.line)
        if key is None:
            parts.append(word.text)
        elif word_key == key:
            parts.append(" " + word.text)
        else:
            parts.append("\n" + word.text)
        key = word_key
    return "".join(parts)


class PdfDocument(QObject):
    changed = Signal(bool)  # True when pages were added, removed, moved or rotated
    state_changed = Signal()  # dirty flag, path or undo availability

    def __init__(self, path=None, password=None, data=None):
        super().__init__()
        self.path = os.path.abspath(path) if path else None
        self.password = password
        # What the open file and undo snapshots are encrypted with; `password` is what the next save uses.
        self._open_password = password
        self.dirty = False
        self.revision = 0
        self._undo = []
        self._redo = []
        self._words = {}
        self.doc = self._open(path, data)

    def _open(self, path=None, data=None):
        doc = pymupdf.open("pdf", data) if data is not None else pymupdf.open(path)
        try:
            # PyMuPDF goes by content, so an image renamed to .pdf opens too.
            if not doc.is_pdf:
                raise ValueError("This file isn't really a PDF.")
            if doc.needs_pass and not doc.authenticate(self._open_password or ""):
                raise PasswordRequired(path)
            if doc.page_count == 0:
                raise ValueError("This PDF has no pages.")
        except Exception:
            doc.close()
            raise
        return doc

    @property
    def title(self):
        return os.path.basename(self.path) if self.path else "Untitled.pdf"

    def __len__(self):
        return self.doc.page_count

    def page(self, index):
        return self.doc[index]

    def words(self, index):
        if index not in self._words:
            page = self.doc[index]
            rows = page.get_text("words")
            self._words[index] = [
                Word(i, normalize_text(r[4]), self.to_display(page, r[:4]), r[5], r[6])
                for i, r in enumerate(rows)
            ]
        return self._words[index]

    @staticmethod
    def to_display(page, rect):
        """PyMuPDF reports positions on the unrotated page; convert them to what's on screen."""
        return tuple((pymupdf.Rect(rect) * page.rotation_matrix).normalize())

    def _state_bytes(self):
        return self.doc.tobytes(garbage=0, deflate=False, encryption=pymupdf.PDF_ENCRYPT_KEEP)

    def _restore(self, data, structural=True):
        self.doc.close()
        self.doc = self._open(data=data)
        self._after_change(structural)

    def _after_change(self, structural):
        self.revision += 1
        self._words.clear()
        self.dirty = True
        self.changed.emit(structural)
        self.state_changed.emit()

    @contextmanager
    def edit(self, structural=False):
        """Run a change with an undo snapshot; the document is restored if it fails."""
        snapshot = self._state_bytes()
        try:
            yield self.doc
        except Exception:
            self._restore(snapshot)
            raise
        self._undo.append(snapshot)
        self._redo.clear()
        while len(self._undo) > MAX_UNDO or (
            len(self._undo) > 1 and sum(map(len, self._undo)) > MAX_UNDO_BYTES
        ):
            self._undo.pop(0)
        self._after_change(structural)

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if self._undo:
            self._redo.append(self._state_bytes())
            self._restore(self._undo.pop())

    def redo(self):
        if self._redo:
            self._undo.append(self._state_bytes())
            self._restore(self._redo.pop())

    def save(self, path=None):
        target = os.path.abspath(path or self.path)
        # A protected file keeps its passwords and permissions unless the user chose a new password.
        options = {"garbage": 3, "deflate": True, "encryption": pymupdf.PDF_ENCRYPT_KEEP}
        if self.password != self._open_password:
            options["encryption"] = pymupdf.PDF_ENCRYPT_NONE
            if self.password:
                options.update(
                    encryption=pymupdf.PDF_ENCRYPT_AES_256,
                    owner_pw=self.password,
                    user_pw=self.password,
                )
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), suffix=".pdf.tmp")
        os.close(fd)
        try:
            self.doc.save(tmp, **options)
            backup = self._state_bytes()
            # Windows will not replace a file that is still open.
            self.doc.close()
            try:
                os.replace(tmp, target)
            except OSError:
                self.doc = self._open(data=backup)
                raise
            self._open_password = self.password
            self.doc = self._open(target)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        self.path = target
        self.dirty = False
        self.revision += 1
        self._words.clear()
        self.changed.emit(False)
        self.state_changed.emit()

    def close(self):
        self.doc.close()

    # Annotations. Text coordinates are in the rotated, on-screen page space;
    # annotation calls expect the page's unrotated space.
    def _to_page_space(self, page, rect):
        return (pymupdf.Rect(rect) * page.derotation_matrix).normalize()

    def add_markup(self, kind, rects_by_page):
        adders = {
            "highlight": "add_highlight_annot",
            "underline": "add_underline_annot",
            "strike": "add_strikeout_annot",
        }
        with self.edit():
            for index, rects in rects_by_page.items():
                page = self.doc[index]
                adder = getattr(page, adders[kind])
                adder(quads=[self._to_page_space(page, r).quad for r in rects])

    def add_note(self, index, point, text):
        with self.edit():
            page = self.doc[index]
            page.add_text_annot(pymupdf.Point(point) * page.derotation_matrix, text)

    def add_text_box(self, index, rect, text, fontsize=12, color=(0.1, 0.1, 0.1)):
        with self.edit():
            page = self.doc[index]
            page.add_freetext_annot(
                self._to_page_space(page, rect),
                text,
                fontsize=fontsize,
                text_color=color,
                rotate=page.rotation,
            )

    def add_shape(self, index, rect, color=(0.85, 0.1, 0.1)):
        with self.edit():
            page = self.doc[index]
            annot = page.add_rect_annot(self._to_page_space(page, rect))
            annot.set_colors(stroke=color)
            annot.set_border(width=1.5)
            annot.update()

    def add_ink(self, index, points, color=(0.1, 0.2, 0.85)):
        with self.edit():
            page = self.doc[index]
            matrix = page.derotation_matrix
            path = [tuple(pymupdf.Point(p) * matrix) for p in points]
            annot = page.add_ink_annot([path])
            annot.set_colors(stroke=color)
            annot.set_border(width=1.5)
            annot.update()

    def annot_at(self, index, point):
        page = self.doc[index]
        target = pymupdf.Point(point)
        for annot in page.annots() or []:
            if target in (annot.rect * page.rotation_matrix).normalize():
                return annot.xref
        return None

    def delete_annot(self, index, xref):
        with self.edit():
            page = self.doc[index]
            for annot in page.annots() or []:
                if annot.xref == xref:
                    page.delete_annot(annot)
                    break

    def widget_at(self, index, point):
        page = self.doc[index]
        target = pymupdf.Point(point)
        for widget in page.widgets() or []:
            if target in (widget.rect * page.rotation_matrix).normalize():
                return widget.xref
        return None

    def widget_info(self, index, xref):
        for widget in self.doc[index].widgets() or []:
            if widget.xref == xref:
                return {
                    "type": widget.field_type,
                    "name": widget.field_label or widget.field_name,
                    "value": widget.field_value,
                    "choices": widget.choice_values,
                }
        return None

    def set_widget_value(self, index, xref, value):
        with self.edit():
            for widget in self.doc[index].widgets() or []:
                if widget.xref == xref:
                    widget.field_value = value
                    widget.update()
                    break

    def link_at(self, index, point):
        page = self.doc[index]
        target = pymupdf.Point(point)
        for link in page.get_links():
            if target in pymupdf.Rect(self.to_display(page, link["from"])):
                return link
        return None

    # Pages
    def rotate_pages(self, indexes, degrees):
        with self.edit(structural=True):
            for index in indexes:
                page = self.doc[index]
                page.set_rotation((page.rotation + degrees) % 360)

    def delete_pages(self, indexes):
        if len(set(indexes)) >= len(self):
            raise ValueError("A PDF has to keep at least one page.")
        with self.edit(structural=True):
            self.doc.delete_pages(sorted(set(indexes)))

    def move_pages(self, order):
        """Reorder pages; `order` lists every old page index in its new position."""
        with self.edit(structural=True):
            self.doc.select(list(order))

    def insert_blank(self, at):
        with self.edit(structural=True):
            source = self.doc[min(at, len(self) - 1)].rect
            self.doc.new_page(at, width=source.width, height=source.height)

    def insert_file(self, path, at, password=None):
        with self.edit(structural=True):
            with pymupdf.open(path) as other:
                if other.needs_pass and not other.authenticate(password or ""):
                    raise PasswordRequired(path)
                self.doc.insert_pdf(other, start_at=at)
