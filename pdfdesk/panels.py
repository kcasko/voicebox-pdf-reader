import os
from collections import OrderedDict, deque

import pymupdf
from PySide6.QtCore import QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .theme import theme

THUMB_WIDTH = 132
THUMB_MAX_HEIGHT = 400
THUMB_MIN_SIDE = 8
THUMB_MARGIN = 10
THUMB_LABEL = 22
THUMB_CACHE = 300
THUMB_QUEUE = 48
SIZE_ROLE = Qt.UserRole + 1
SEARCH_COLOR = QColor(255, 200, 0, 110)
SEARCH_CURRENT_COLOR = QColor(255, 120, 0, 130)
RAIL_WIDTH = 48
SIDE_WIDTH = 224
SIDE_MAX_WIDTH = 480


def thumb_size(page_width, page_height):
    """Fit a page in the thumbnail box. Pages can be any shape, so both sides are limited."""
    width, height = max(1, page_width), max(1, page_height)
    scale = min(THUMB_WIDTH / width, THUMB_MAX_HEIGHT / height)
    return QSize(max(THUMB_MIN_SIDE, round(width * scale)), max(THUMB_MIN_SIDE, round(height * scale)))


class _ThumbnailDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        size = index.data(SIZE_ROLE)
        if size is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        width, height = size.width(), size.height()
        x = option.rect.x() + (option.rect.width() - width) // 2
        y = option.rect.y() + THUMB_MARGIN // 2
        frame = QRectF(x, y, width, height)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        # Only what gets painted is rendered, so asking here is what makes thumbnails lazy.
        pixmap = self.parent().thumbnail(index.data(Qt.UserRole))
        if pixmap is None:
            painter.fillRect(frame, QColor(255, 255, 255))
        else:
            painter.drawPixmap(x, y, pixmap)
        if selected:
            painter.setPen(QPen(theme.color("accent"), 2.5))
            painter.drawRoundedRect(frame.adjusted(-2, -2, 2, 2), 3, 3)
        else:
            painter.setPen(QPen(theme.color("faint" if hovered else "border"), 1))
            painter.drawRect(frame.adjusted(-0.5, -0.5, 0.5, 0.5))
        font = QFont(painter.font())
        font.setPointSizeF(9)
        font.setBold(selected)
        painter.setFont(font)
        painter.setPen(theme.color("accent" if selected else "muted"))
        label = QRect(option.rect.x(), y + height + 2, option.rect.width(), THUMB_LABEL)
        painter.drawText(label, Qt.AlignCenter, index.data(Qt.DisplayRole))
        painter.restore()


class ThumbnailPanel(QListWidget):
    """Page thumbnails. Drag to reorder; the selection is what the Pages menu acts on."""

    pages_reordered = Signal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName("thumbnails")
        self.setItemDelegate(_ThumbnailDelegate(self))
        self.setSpacing(2)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.view = None
        self._cache = OrderedDict()  # (document, page) -> QPixmap, kept across tab switches
        self._pending = deque(maxlen=THUMB_QUEUE)
        self._timer = QTimer(self, interval=0, timeout=self._render_next)
        self.itemClicked.connect(self._on_clicked)

    def set_view(self, view):
        if self.view is not None:
            try:
                self.view.document.changed.disconnect(self._on_changed)
                self.view.current_page_changed.disconnect(self._on_page)
            except RuntimeError:
                pass
        self.view = view
        if view:
            view.document.changed.connect(self._on_changed)
            view.current_page_changed.connect(self._on_page)
        self.rebuild()

    def rebuild(self):
        self._timer.stop()
        self._pending.clear()
        self.clear()
        if not self.view:
            return
        for index in range(len(self.view.document)):
            size = thumb_size(*self.view.page_size(index))
            item = QListWidgetItem(str(index + 1))
            item.setData(Qt.UserRole, index)
            item.setData(SIZE_ROLE, size)
            item.setSizeHint(QSize(THUMB_WIDTH + 16, size.height() + THUMB_LABEL + THUMB_MARGIN))
            self.addItem(item)
        self._on_page(self.view.current_page)

    def thumbnail(self, index):
        """The cached image of a page, or None after queueing it to be rendered."""
        if not self.view:
            return None
        key = (self.view.document, index)
        pixmap = self._cache.get(key)
        if pixmap is not None:
            self._cache.move_to_end(key)
            return pixmap
        if index not in self._pending:
            self._pending.append(index)
            self._timer.start()
        return None

    def forget(self, document):
        for key in [k for k in self._cache if k[0] is document]:
            del self._cache[key]

    def _on_changed(self, structural):
        if self.view:
            self.forget(self.view.document)
        if structural:
            self.rebuild()
        else:
            # Annotations only change what a page looks like.
            self.viewport().update()

    def _render_next(self):
        if not self._pending or not self.view:
            self._timer.stop()
            return
        # Newest first: those are what the user has just scrolled to.
        index = self._pending.pop()
        document = self.view.document
        if index >= len(document):
            return
        page = document.page(index)
        ratio = self.devicePixelRatioF()
        size = thumb_size(page.rect.width, page.rect.height)
        matrix = pymupdf.Matrix(size.width() * ratio / max(1, page.rect.width), size.height() * ratio / max(1, page.rect.height))
        pix = page.get_pixmap(matrix=matrix, alpha=False, annots=True)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(ratio)
        self._cache[(document, index)] = pixmap
        while len(self._cache) > THUMB_CACHE:
            self._cache.popitem(last=False)
        self.viewport().update()

    def _on_clicked(self, item):
        if self.view:
            self.view.go_to_page(self.row(item))

    def _on_page(self, index):
        if 0 <= index < self.count() and len(self.selectedItems()) <= 1:
            self.blockSignals(True)
            self.setCurrentRow(index)
            self.scrollToItem(self.item(index))
            self.blockSignals(False)

    def selected_pages(self):
        return sorted(self.row(item) for item in self.selectedItems())

    def dropEvent(self, event):
        super().dropEvent(event)
        order = [self.item(i).data(Qt.UserRole) for i in range(self.count())]
        if order != sorted(order):
            # Reordering rebuilds this list, which can't happen in the middle of its own drop.
            QTimer.singleShot(0, lambda: self.pages_reordered.emit(order))


class OutlinePanel(QTreeWidget):
    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setIndentation(14)
        self.view = None
        self.itemClicked.connect(self._on_clicked)

    def set_view(self, view):
        if self.view is not None:
            try:
                self.view.document.changed.disconnect(self._on_changed)
            except RuntimeError:
                pass
        self.view = view
        if view:
            view.document.changed.connect(self._on_changed)
        self.rebuild()

    def _on_changed(self, structural):
        if structural:
            self.rebuild()

    def rebuild(self):
        self.clear()
        if not self.view:
            return
        toc = self.view.document.doc.get_toc(simple=True)
        if not toc:
            placeholder = QTreeWidgetItem(["This PDF has no outline."])
            placeholder.setFlags(Qt.NoItemFlags)
            self.addTopLevelItem(placeholder)
            return
        parents = {0: self.invisibleRootItem()}
        for level, title, page in toc:
            parent = parents.get(level - 1) or self.invisibleRootItem()
            item = QTreeWidgetItem(parent, [title])
            item.setData(0, Qt.UserRole, page - 1)
            parents[level] = item
        self.expandToDepth(0)

    def _on_clicked(self, item):
        page = item.data(0, Qt.UserRole)
        if self.view and page is not None and page >= 0:
            self.view.go_to_page(page)


class SearchPanel(QWidget):
    """Searches a page per timer tick so long documents stay responsive."""

    def __init__(self):
        super().__init__()
        self.view = None
        self.input = QLineEdit(placeholderText="Find in document")
        self.input.setClearButtonEnabled(True)
        self.case_box = QCheckBox("Match case")
        self.results = QListWidget()
        self.results.setWordWrap(True)
        self.status = QLabel("", objectName="panelStatus")
        previous = QToolButton(toolTip="Previous match")
        following = QToolButton(toolTip="Next match")
        theme.bind(previous, "up", "muted")
        theme.bind(following, "down", "muted")
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.status.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self.status, 1)
        row.addWidget(previous)
        row.addWidget(following)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.input)
        layout.addWidget(self.case_box)
        layout.addLayout(row)
        layout.addWidget(self.results, 1)
        self._timer = QTimer(self, interval=0, timeout=self._search_next)
        self._matches = []
        self._next_page = 0
        self._query = ""
        self.input.returnPressed.connect(self._on_return)
        self.case_box.toggled.connect(lambda _v: self.start())
        previous.clicked.connect(lambda: self._step(-1))
        following.clicked.connect(lambda: self._step(1))
        self.results.currentRowChanged.connect(self._show_match)

    def set_view(self, view):
        if self.view:
            self.view.set_overlay("search", None)
        self.view = view
        self.start()

    def focus(self):
        self.input.setFocus()
        self.input.selectAll()

    def _on_return(self):
        if self.input.text() == self._query and self._matches:
            self._step(1)
        else:
            self.start()

    def start(self):
        self._timer.stop()
        self.results.clear()
        self._matches = []
        self._next_page = 0
        self._query = self.input.text()
        self.status.setText("")
        if self.view:
            self.view.set_overlay("search", None)
        if self.view and self._query.strip():
            self._timer.start()

    def _search_next(self):
        document = self.view.document if self.view else None
        if document is None or self._next_page >= len(document):
            self._timer.stop()
            self.status.setText(f"{len(self._matches)} matches" if self._matches else "No matches")
            self._apply_overlay()
            return
        index = self._next_page
        self._next_page += 1
        page = document.page(index)
        rects = page.search_for(self._query, flags=pymupdf.TEXT_DEHYPHENATE)
        if self.case_box.isChecked():
            rects = [r for r in rects if self._query in page.get_textbox(r + (-1, -1, 1, 1))]
        for rect in rects:
            self._matches.append((index, document.to_display(page, rect)))
            snippet = page.get_textbox(rect + (-90, -1, 90, 1)).replace("\n", " ").strip()
            # The box cuts words off at both ends, so drop those when the match survives.
            trimmed = " ".join(snippet.split()[1:-1])
            if self._query.lower() in trimmed.lower():
                snippet = trimmed
            self.results.addItem(f"Page {index + 1}: {snippet}")
        self.status.setText(f"Searching... {len(self._matches)}")
        if rects and len(self._matches) == len(rects):
            self.results.setCurrentRow(0)

    def _apply_overlay(self):
        if not self.view:
            return
        by_page = {}
        for index, rect in self._matches:
            by_page.setdefault(index, []).append(rect)
        self.view.set_overlay("search", by_page, SEARCH_COLOR)

    def _step(self, delta):
        if self._matches:
            self.results.setCurrentRow((self.results.currentRow() + delta) % len(self._matches))

    def _show_match(self, row):
        if not self.view or not 0 <= row < len(self._matches):
            return
        index, rect = self._matches[row]
        self._apply_overlay()
        self.view.set_overlay("search-current", {index: [rect]}, SEARCH_CURRENT_COLOR)
        self.view.reveal_rect(index, rect)


class SidePanel(QWidget):
    """A slim rail of icons. Clicking one opens its panel; clicking it again collapses."""

    def __init__(self):
        super().__init__()
        self._buttons = QButtonGroup(self, exclusive=False)
        self._panels = {}
        self.rail = QWidget(objectName="rail")
        self.rail.setAttribute(Qt.WA_StyledBackground)
        self.rail.setFixedWidth(RAIL_WIDTH)
        self._rail_layout = QVBoxLayout(self.rail)
        self._rail_layout.setContentsMargins(7, 10, 7, 10)
        self._rail_layout.setSpacing(4)
        self._rail_layout.addStretch()
        self.stack = QStackedWidget(objectName="sideStack")
        self.stack.setAttribute(Qt.WA_StyledBackground)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.rail)
        layout.addWidget(self.stack, 1)
        self._set_open(True)

    def add_panel(self, key, title, icon, widget):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(12, 12, 8, 8)
        page_layout.setSpacing(10)
        page_layout.addWidget(QLabel(title, objectName="panelTitle"))
        page_layout.addWidget(widget, 1)
        self.stack.addWidget(page)
        button = QToolButton(objectName="railButton", toolTip=title, checkable=True)
        button.setIconSize(QSize(20, 20))
        theme.bind(button, icon, "muted")
        button.clicked.connect(lambda _c=False, k=key: self._on_button(k))
        self._rail_layout.insertWidget(self._rail_layout.count() - 1, button)
        self._panels[key] = (page, button)
        if len(self._panels) == 1:
            self.show_panel(key)

    def is_open(self):
        return self.stack.isVisibleTo(self)

    def show_panel(self, key):
        page, _button = self._panels[key]
        self.stack.setCurrentWidget(page)
        self._set_open(True)
        self._sync_buttons(key)

    def _on_button(self, key):
        page, _button = self._panels[key]
        if self.is_open() and self.stack.currentWidget() is page:
            self.set_collapsed(True)
        else:
            self.show_panel(key)

    def set_collapsed(self, collapsed):
        self._set_open(not collapsed)
        if collapsed:
            self._sync_buttons(None)
        else:
            current = self.stack.currentWidget()
            self._sync_buttons(next((k for k, (p, _b) in self._panels.items() if p is current), None))

    def _sync_buttons(self, active):
        for key, (_page, button) in self._panels.items():
            button.setChecked(key == active)

    def _set_open(self, is_open):
        self.stack.setVisible(is_open)
        if is_open:
            self.setMinimumWidth(RAIL_WIDTH + 170)
            self.setMaximumWidth(SIDE_MAX_WIDTH)
            parent = self.parent()
            if parent is not None and hasattr(parent, "sizes") and parent.sizes()[0] < SIDE_WIDTH:
                total = sum(parent.sizes())
                parent.setSizes([SIDE_WIDTH, total - SIDE_WIDTH])
        else:
            self.setFixedWidth(RAIL_WIDTH)


class WelcomePage(QWidget):
    """Shown when no PDF is open."""

    open_requested = Signal()
    recent_requested = Signal(str)

    def __init__(self, logo_path):
        super().__init__(objectName="welcomePage")
        self.setAttribute(Qt.WA_StyledBackground)
        logo = QLabel(alignment=Qt.AlignCenter)
        icon = QIcon(logo_path)
        if not icon.isNull():
            logo.setPixmap(icon.pixmap(72, 72))
        title = QLabel("PDF Desk", objectName="welcomeTitle", alignment=Qt.AlignCenter)
        body = QLabel("Read it, mark it up, or listen to it.", objectName="welcomeBody", alignment=Qt.AlignCenter)
        open_button = QPushButton("Open a PDF", objectName="primaryButton")
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.clicked.connect(self.open_requested)
        hint = QLabel("or drop one anywhere in this window", objectName="muted", alignment=Qt.AlignCenter)
        self.recent_label = QLabel("RECENT", objectName="sectionLabel")
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(2)
        column = QVBoxLayout()
        column.setSpacing(6)
        column.addStretch(3)
        column.addWidget(logo)
        column.addSpacing(8)
        column.addWidget(title)
        column.addWidget(body)
        column.addSpacing(14)
        column.addWidget(open_button, 0, Qt.AlignHCenter)
        column.addWidget(hint)
        column.addSpacing(26)
        column.addWidget(self.recent_label)
        column.addLayout(self.recent_box)
        column.addStretch(4)
        holder = QWidget()
        holder.setFixedWidth(460)
        holder.setLayout(column)
        layout = QHBoxLayout(self)
        layout.addStretch()
        layout.addWidget(holder)
        layout.addStretch()
        theme.changed.connect(self._restyle_recent)
        self._recent = []

    def set_recent(self, paths):
        self._recent = [p for p in paths if os.path.exists(p)][:5]
        self._restyle_recent()

    def _restyle_recent(self):
        while self.recent_box.count():
            widget = self.recent_box.takeAt(0).widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        self.recent_label.setVisible(bool(self._recent))
        for path in self._recent:
            folder = os.path.dirname(path)
            shown = folder if len(folder) <= 44 else "..." + folder[-41:]
            button = QPushButton(f"{os.path.basename(path)}    {shown}", objectName="recentFile")
            button.setIcon(theme.icon("file", "muted"))
            button.setToolTip(path)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _c=False, p=path: self.recent_requested.emit(p))
            self.recent_box.addWidget(button)
