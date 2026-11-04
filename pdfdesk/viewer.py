import time
from collections import OrderedDict

import pymupdf
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtWidgets import QAbstractScrollArea, QInputDialog, QMenu, QMessageBox

from .document import line_rects, words_to_text
from .theme import theme

GAP = 16
SHADOW_LAYERS = 5
MIN_ZOOM = 0.25
MAX_ZOOM = 6.0
CACHE_PAGES = 24
DRAG_THRESHOLD = 4
MARKUP_TOOLS = {"highlight", "underline", "strike"}
DRAW_TOOLS = {"note", "text", "shape", "ink"}
SELECTION_COLOR = QColor(40, 120, 230, 80)


class PdfView(QAbstractScrollArea):
    current_page_changed = Signal(int)
    zoom_changed = Signal(float)
    selection_changed = Signal()
    tool_finished = Signal()

    def __init__(self, document, parent=None):
        super().__init__(parent)
        self.document = document
        self.zoom = 1.0
        self.fit_mode = "width"
        self.tool = "select"
        self.context_hook = None
        self.last_user_scroll = 0.0
        self._cache = OrderedDict()
        self._tops = []
        self._sizes = []
        self._canvas_width = 0
        self._canvas_height = 0
        self._current_page = 0
        self._selection = None
        self._overlays = {}
        self._press = None
        self._drag_rect = None
        self._ink = None
        self._hand_start = None
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFrameShape(QAbstractScrollArea.NoFrame)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.horizontalScrollBar().valueChanged.connect(lambda _v: self.viewport().update())
        document.changed.connect(self._on_document_changed)
        theme.changed.connect(self.viewport().update)
        self._relayout()

    # Layout
    def _relayout(self):
        self._sizes = [(p.rect.width, p.rect.height) for p in self.document.doc.pages()]
        self._apply_fit()
        self._tops, y = [], GAP
        for width, height in self._sizes:
            self._tops.append(y)
            y += round(height * self.zoom) + GAP
        self._canvas_height = y
        widest = max((w for w, _ in self._sizes), default=0)
        self._canvas_width = round(widest * self.zoom) + 2 * GAP
        viewport = self.viewport().size()
        self.verticalScrollBar().setRange(0, max(0, self._canvas_height - viewport.height()))
        self.verticalScrollBar().setPageStep(viewport.height())
        self.verticalScrollBar().setSingleStep(40)
        self.horizontalScrollBar().setRange(0, max(0, self._canvas_width - viewport.width()))
        self.horizontalScrollBar().setPageStep(viewport.width())
        self.viewport().update()

    def _apply_fit(self):
        if not self._sizes or not self.fit_mode:
            return
        viewport = self.viewport().size()
        # Keep room for the scrollbar so fitting does not flip it on and off.
        available = max(100, viewport.width() - 2 * GAP - self.verticalScrollBar().sizeHint().width())
        widest = max(w for w, _ in self._sizes)
        zoom = available / widest
        if self.fit_mode == "page":
            tallest = max(h for _, h in self._sizes)
            zoom = min(zoom, max(100, viewport.height() - 2 * GAP) / tallest)
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        self.zoom_changed.emit(self.zoom)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        anchor = self.current_page
        fraction = self._page_fraction()
        self._relayout()
        self._scroll_to_fraction(anchor, fraction)

    def _page_fraction(self):
        if not self._tops:
            return 0.0
        top = self._tops[self._current_page]
        height = max(1, self._sizes[self._current_page][1] * self.zoom)
        return (self.verticalScrollBar().value() - top) / height

    def _scroll_to_fraction(self, page, fraction):
        if page < len(self._tops):
            height = self._sizes[page][1] * self.zoom
            self.verticalScrollBar().setValue(round(self._tops[page] + fraction * height))

    def set_zoom(self, zoom, fit_mode=None):
        page, fraction = self._current_page, self._page_fraction()
        self.fit_mode = fit_mode
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        self._relayout()
        self._scroll_to_fraction(page, fraction)
        self.zoom_changed.emit(self.zoom)

    def set_fit(self, mode):
        self.set_zoom(self.zoom, fit_mode=mode)

    def _on_document_changed(self, structural):
        self._cache.clear()
        if structural:
            self._selection = None
            self._overlays.clear()
            self._relayout()
            self._current_page = min(self._current_page, max(0, len(self._tops) - 1))
        self.viewport().update()

    # Navigation
    @property
    def current_page(self):
        return self._current_page

    def _on_scroll(self, value):
        middle = value + self.viewport().height() / 2
        page = 0
        for i, top in enumerate(self._tops):
            if top > middle:
                break
            page = i
        if page != self._current_page:
            self._current_page = page
            self.current_page_changed.emit(page)
        self.viewport().update()

    def go_to_page(self, index, y=0.0):
        if not self._tops:
            return
        index = max(0, min(index, len(self._tops) - 1))
        self.verticalScrollBar().setValue(round(self._tops[index] + y * self.zoom) - GAP)
        if index != self._current_page:
            self._current_page = index
            self.current_page_changed.emit(index)

    def is_rect_visible(self, index, rect):
        top = self._tops[index] + rect[1] * self.zoom
        bottom = self._tops[index] + rect[3] * self.zoom
        scroll = self.verticalScrollBar().value()
        return top >= scroll and bottom <= scroll + self.viewport().height()

    def reveal_rect(self, index, rect):
        """Scroll just enough to bring a page rectangle into a comfortable position."""
        if index >= len(self._tops) or self.is_rect_visible(index, rect):
            return
        target = self._tops[index] + rect[1] * self.zoom - self.viewport().height() * 0.3
        self.verticalScrollBar().setValue(round(target))

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.set_zoom(self.zoom * factor)
            event.accept()
            return
        self.last_user_scroll = time.monotonic()
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        bar = self.verticalScrollBar()
        key = event.key()
        if key == Qt.Key_PageDown:
            self.go_to_page(self._current_page + 1)
        elif key == Qt.Key_PageUp:
            self.go_to_page(self._current_page - 1)
        elif key == Qt.Key_Home:
            self.go_to_page(0)
        elif key == Qt.Key_End:
            self.go_to_page(len(self._tops) - 1)
        elif key == Qt.Key_Down:
            bar.setValue(bar.value() + bar.singleStep())
        elif key == Qt.Key_Up:
            bar.setValue(bar.value() - bar.singleStep())
        elif key == Qt.Key_Escape:
            self.clear_selection()
            self.set_tool("select")
            self.tool_finished.emit()
        else:
            super().keyPressEvent(event)
            return
        self.last_user_scroll = time.monotonic()

    # Coordinates
    def _page_left(self, index):
        width = round(self._sizes[index][0] * self.zoom)
        canvas = max(self._canvas_width, self.viewport().width())
        return (canvas - width) // 2

    def _to_view(self, index, x, y):
        return QPointF(
            self._page_left(index) + x * self.zoom - self.horizontalScrollBar().value(),
            self._tops[index] + y * self.zoom - self.verticalScrollBar().value(),
        )

    def _rect_to_view(self, index, rect):
        top_left = self._to_view(index, rect[0], rect[1])
        return QRectF(top_left.x(), top_left.y(), (rect[2] - rect[0]) * self.zoom, (rect[3] - rect[1]) * self.zoom)

    def page_at(self, pos, clamp=False):
        """Return (page, x, y) in page coordinates for a viewport position."""
        canvas_y = pos.y() + self.verticalScrollBar().value()
        for index, top in enumerate(self._tops):
            height = self._sizes[index][1] * self.zoom
            if canvas_y < top - GAP or canvas_y > top + height:
                continue
            x = (pos.x() + self.horizontalScrollBar().value() - self._page_left(index)) / self.zoom
            y = (canvas_y - top) / self.zoom
            width, page_height = self._sizes[index]
            if clamp:
                return index, min(max(x, 0), width), min(max(y, 0), page_height)
            if 0 <= x <= width and 0 <= y <= page_height:
                return index, x, y
            return None
        return None

    def nearest_word(self, index, x, y, max_distance=None):
        best, best_distance = None, None
        for word in self.document.words(index):
            x0, y0, x1, y1 = word.rect
            dx = max(x0 - x, 0, x - x1)
            dy = max(y0 - y, 0, y - y1)
            distance = dx * dx / 16 + dy * dy  # Prefer the same line over a nearby column.
            if best_distance is None or distance < best_distance:
                best, best_distance = word.index, distance
        if max_distance is not None and (best_distance is None or best_distance > max_distance**2):
            return None
        return best

    # Selection
    def selection(self):
        """Return ((page, word), (page, word)) in reading order, or None."""
        return self._selection

    def clear_selection(self):
        if self._selection:
            self._selection = None
            self.selection_changed.emit()
            self.viewport().update()

    def select_words(self, start, end):
        self._selection = (start, end) if start <= end else (end, start)
        self.selection_changed.emit()
        self.viewport().update()

    def select_page(self):
        words = self.document.words(self._current_page)
        if words:
            self.select_words((self._current_page, 0), (self._current_page, len(words) - 1))

    def selected_words(self):
        """Return {page: [Word, ...]} for the current selection."""
        if not self._selection:
            return {}
        (first_page, first_word), (last_page, last_word) = self._selection
        result = {}
        for index in range(first_page, last_page + 1):
            words = self.document.words(index)
            start = first_word if index == first_page else 0
            end = last_word if index == last_page else len(words) - 1
            if words:
                result[index] = words[start : end + 1]
        return result

    def selected_text(self):
        return "\n".join(words_to_text(words) for words in self.selected_words().values())

    def copy_selection(self):
        text = self.selected_text()
        if text:
            QGuiApplication.clipboard().setText(text)

    def apply_markup(self, kind):
        rects = {page: line_rects(words) for page, words in self.selected_words().items()}
        if rects:
            self.document.add_markup(kind, rects)
            self.clear_selection()

    # Overlays let the search panel and plugins mark text without changing the PDF.
    def set_overlay(self, owner, rects_by_page, color=QColor(255, 200, 0, 90)):
        if rects_by_page:
            self._overlays[owner] = (rects_by_page, color)
        else:
            self._overlays.pop(owner, None)
        self.viewport().update()

    # Tools
    def set_tool(self, tool):
        self.tool = tool
        cursors = {"hand": Qt.OpenHandCursor, "select": Qt.IBeamCursor}
        if tool in MARKUP_TOOLS:
            cursor = Qt.IBeamCursor
        else:
            cursor = cursors.get(tool, Qt.CrossCursor)
        self.viewport().setCursor(cursor)

    def _finish_tool(self):
        self.set_tool("select")
        self.tool_finished.emit()

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() != Qt.LeftButton:
            return
        pos = event.position().toPoint()
        hit = self.page_at(pos)
        self._press = (pos, hit)
        if self.tool == "hand":
            self._hand_start = (pos, self.horizontalScrollBar().value(), self.verticalScrollBar().value())
            self.viewport().setCursor(Qt.ClosedHandCursor)
        elif self.tool == "ink" and hit:
            self._ink = (hit[0], [(hit[1], hit[2])])

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if not (event.buttons() & Qt.LeftButton) or not self._press:
            self._update_hover(pos)
            return
        press_pos, press_hit = self._press
        if self._hand_start:
            start, hx, vy = self._hand_start
            self.horizontalScrollBar().setValue(hx - (pos.x() - start.x()))
            self.verticalScrollBar().setValue(vy - (pos.y() - start.y()))
            self.last_user_scroll = time.monotonic()
            return
        if not press_hit:
            return
        if self.tool == "ink" and self._ink:
            hit = self.page_at(pos, clamp=True)
            if hit and hit[0] == self._ink[0]:
                self._ink[1].append((hit[1], hit[2]))
                self.viewport().update()
        elif self.tool in ("shape", "text"):
            self._drag_rect = (press_hit[0], press_hit[1], press_hit[2], pos)
            self.viewport().update()
        elif self.tool == "select" or self.tool in MARKUP_TOOLS:
            if (pos - press_pos).manhattanLength() < DRAG_THRESHOLD:
                return
            self._extend_selection(press_hit, pos)

    def _extend_selection(self, press_hit, pos):
        hit = self.page_at(pos, clamp=True)
        if not hit:
            return
        start = self.nearest_word(press_hit[0], press_hit[1], press_hit[2])
        end = self.nearest_word(hit[0], hit[1], hit[2])
        if start is not None and end is not None:
            self.select_words((press_hit[0], start), (hit[0], end))

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or not self._press:
            return
        press_pos, press_hit = self._press
        pos = event.position().toPoint()
        moved = (pos - press_pos).manhattanLength() >= DRAG_THRESHOLD
        self._press = None
        if self._hand_start:
            self._hand_start = None
            self.viewport().setCursor(Qt.OpenHandCursor)
        elif self.tool in MARKUP_TOOLS:
            if self._selection:
                self.apply_markup(self.tool)
        elif self.tool == "ink":
            self._finish_ink()
        elif self.tool in ("shape", "text") and press_hit:
            self._finish_box(press_hit, pos, moved)
        elif self.tool == "note" and press_hit:
            text, ok = QInputDialog.getMultiLineText(self, "Sticky note", "Note:")
            if ok and text.strip():
                self.document.add_note(press_hit[0], (press_hit[1], press_hit[2]), text)
            self._finish_tool()
        elif self.tool == "select" and not moved:
            self.clear_selection()
            if press_hit:
                self._click_page(press_hit)

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        hit = self.page_at(event.position().toPoint())
        if hit and self.tool == "select":
            word = self.nearest_word(hit[0], hit[1], hit[2], max_distance=8)
            if word is not None:
                self.select_words((hit[0], word), (hit[0], word))
                self._press = None

    def _finish_ink(self):
        ink, self._ink = self._ink, None
        if ink and len(ink[1]) > 1:
            self.document.add_ink(ink[0], ink[1])
        self.viewport().update()

    def _finish_box(self, press_hit, pos, moved):
        self._drag_rect = None
        end = self.page_at(pos, clamp=True)
        if moved and end and end[0] == press_hit[0]:
            rect = pymupdf.Rect(press_hit[1], press_hit[2], end[1], end[2]).normalize()
        else:
            rect = pymupdf.Rect(press_hit[1], press_hit[2], press_hit[1] + 200, press_hit[2] + 48)
        if self.tool == "shape":
            if moved:
                self.document.add_shape(press_hit[0], rect)
        else:
            text, ok = QInputDialog.getMultiLineText(self, "Add text", "Text:")
            if ok and text.strip():
                self.document.add_text_box(press_hit[0], rect, text)
        self._finish_tool()
        self.viewport().update()

    def _click_page(self, hit):
        index, x, y = hit
        xref = self.document.widget_at(index, (x, y))
        if xref is not None:
            self._edit_widget(index, xref)
            return
        link = self.document.link_at(index, (x, y))
        if link:
            self._follow_link(link)

    def _edit_widget(self, index, xref):
        info = self.document.widget_info(index, xref)
        if not info:
            return
        kind = info["type"]
        if kind == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
            self.document.set_widget_value(index, xref, not bool(info["value"]) or info["value"] == "Off")
        elif kind == pymupdf.PDF_WIDGET_TYPE_TEXT:
            text, ok = QInputDialog.getMultiLineText(self, "Fill in field", info["name"] or "Value:", str(info["value"] or ""))
            if ok:
                self.document.set_widget_value(index, xref, text)
        elif kind in (pymupdf.PDF_WIDGET_TYPE_COMBOBOX, pymupdf.PDF_WIDGET_TYPE_LISTBOX) and info["choices"]:
            choices = [c[1] if isinstance(c, (list, tuple)) else c for c in info["choices"]]
            value, ok = QInputDialog.getItem(self, "Fill in field", info["name"] or "Value:", choices, editable=False)
            if ok:
                self.document.set_widget_value(index, xref, value)

    def _follow_link(self, link):
        if link.get("kind") == pymupdf.LINK_GOTO:
            self.go_to_page(link["page"], link["to"].y if link.get("to") else 0)
        elif link.get("uri"):
            answer = QMessageBox.question(self, "Open link", f"Open this link in your browser?\n\n{link['uri']}")
            if answer == QMessageBox.Yes:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices

                QDesktopServices.openUrl(QUrl(link["uri"]))

    def _update_hover(self, pos):
        if self.tool != "select":
            return
        hit = self.page_at(pos)
        cursor = Qt.ArrowCursor
        if hit:
            index, x, y = hit
            if self.document.link_at(index, (x, y)) or self.document.widget_at(index, (x, y)) is not None:
                cursor = Qt.PointingHandCursor
            elif self.nearest_word(index, x, y, max_distance=4) is not None:
                cursor = Qt.IBeamCursor
        self.viewport().setCursor(cursor)

    def contextMenuEvent(self, event):
        pos = self.viewport().mapFrom(self, event.pos())
        hit = self.page_at(pos)
        if not hit:
            return
        index, x, y = hit
        menu = QMenu(self)
        if self._selection:
            menu.addAction("Copy", self.copy_selection)
            menu.addAction("Highlight", lambda: self.apply_markup("highlight"))
            menu.addAction("Underline", lambda: self.apply_markup("underline"))
            menu.addAction("Strikethrough", lambda: self.apply_markup("strike"))
        xref = self.document.annot_at(index, (x, y))
        if xref is not None:
            menu.addAction("Delete annotation", lambda: self.document.delete_annot(index, xref))
        if self.context_hook:
            self.context_hook(menu, self, index, (x, y))
        if not menu.isEmpty():
            menu.exec(event.globalPos())

    # Painting
    def _pixmap(self, index, ratio):
        key = (index, round(self.zoom * ratio, 3), self.document.revision)
        image = self._cache.get(key)
        if image is None:
            matrix = pymupdf.Matrix(self.zoom * ratio, self.zoom * ratio)
            pix = self.document.page(index).get_pixmap(matrix=matrix, alpha=False, annots=True)
            image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
            image.setDevicePixelRatio(ratio)
            self._cache[key] = image
            while len(self._cache) > CACHE_PAGES:
                self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(key)
        return image

    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.fillRect(event.rect(), theme.color("canvas"))
        ratio = self.devicePixelRatioF()
        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()
        selected = self.selected_words()
        for index, page_top in enumerate(self._tops):
            height = round(self._sizes[index][1] * self.zoom)
            if page_top + height < top:
                continue
            if page_top > bottom:
                break
            origin = self._to_view(index, 0, 0)
            self._paint_shadow(painter, origin, round(self._sizes[index][0] * self.zoom), height)
            painter.drawImage(origin, self._pixmap(index, ratio))
            for rects_by_page, color in self._overlays.values():
                for rect in rects_by_page.get(index, ()):
                    painter.fillRect(self._rect_to_view(index, tuple(rect)), color)
            if index in selected:
                for rect in line_rects(selected[index]):
                    painter.fillRect(self._rect_to_view(index, tuple(rect)), SELECTION_COLOR)
        self._paint_drafts(painter)

    def _paint_shadow(self, painter, origin, width, height):
        color = QColor(0, 0, 0, 16)
        for spread in range(SHADOW_LAYERS, 0, -1):
            painter.fillRect(
                QRectF(origin.x() - spread, origin.y() - spread + 2, width + 2 * spread, height + 2 * spread),
                color,
            )

    def _paint_drafts(self, painter):
        pen = QPen(QColor(30, 90, 220), 1.5)
        painter.setPen(pen)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._ink:
            index, points = self._ink
            path = [self._to_view(index, x, y) for x, y in points]
            for a, b in zip(path, path[1:]):
                painter.drawLine(a, b)
        if self._drag_rect:
            index, x, y, pos = self._drag_rect
            painter.drawRect(QRectF(self._to_view(index, x, y), QPointF(QPoint(pos))).normalized())
