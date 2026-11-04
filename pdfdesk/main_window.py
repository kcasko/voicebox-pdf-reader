import logging
import os

from PySide6.QtCore import QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence, QPainter
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QHBoxLayout,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, __version__, tools
from .document import PasswordRequired, PdfDocument
from .panels import SIDE_WIDTH, OutlinePanel, SearchPanel, SidePanel, ThumbnailPanel, WelcomePage
from .plugins import ContextInfo, PluginManager
from .settings import APP_HOME, load_json, save_json
from .theme import theme
from .viewer import PdfView

log = logging.getLogger(__name__)

PDF_FILTER = "PDF files (*.pdf)"
MAX_RECENT = 12
MAX_REMEMBERED_VIEWS = 200
ZOOM_PRESETS = ["Fit width", "Fit page", "50%", "75%", "100%", "125%", "150%", "200%", "300%"]
LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "pdfdesk.ico")
ANNOTATION_TOOLS = [
    ("select", "Select text", "select"),
    ("hand", "Hand: drag to scroll", "hand"),
    ("highlight", "Highlight", "highlight"),
    ("underline", "Underline", "underline"),
    ("strike", "Strikethrough", "strike"),
    ("note", "Sticky note", "note"),
    ("text", "Text box", "text"),
    ("shape", "Box", "box"),
    ("ink", "Draw", "draw"),
]
PLUGIN_TEXT_LIMITS = {"name": 60, "version": 20, "description": 500}


def fit_rect(frame, available):
    """Shrink and move a window rectangle until it is fully inside the available screen area."""
    width = min(frame.width(), available.width())
    height = min(frame.height(), available.height())
    x = max(available.left(), min(frame.x(), available.left() + available.width() - width))
    y = max(available.top(), min(frame.y(), available.top() + available.height() - height))
    return QRect(x, y, width, height)


def clip(text, limit):
    return text if len(text) <= limit else text[: limit - 1] + "…"


class MainWindow(QMainWindow):
    def __init__(self, plugin_folders=None, home=APP_HOME):
        super().__init__()
        self.home = home
        self.settings_path = os.path.join(home, "settings.json")
        self.settings = load_json(self.settings_path)
        theme.apply(QApplication.instance(), self.settings.get("theme", "system"))
        self.resize(1360, 880)
        self.setAcceptDrops(True)

        self.tabs = QTabWidget(tabsClosable=True, movable=True, documentMode=True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.welcome = WelcomePage(LOGO_PATH)
        self.welcome.open_requested.connect(self.open_dialog)
        self.welcome.recent_requested.connect(self.open_path)
        self.welcome.set_recent(self.settings.get("recent", []))
        self.center = QStackedWidget()
        self.center.addWidget(self.welcome)
        self.center.addWidget(self.tabs)

        self.thumbnails = ThumbnailPanel()
        self.thumbnails.pages_reordered.connect(self._on_pages_reordered)
        self.outline = OutlinePanel()
        self.search = SearchPanel()
        self.side = SidePanel()
        self.side.add_panel("pages", "Pages", "pages", self.thumbnails)
        self.side.add_panel("outline", "Outline", "outline", self.outline)
        self.side.add_panel("search", "Search", "search", self.search)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(3)
        self.splitter.addWidget(self.side)
        self.splitter.addWidget(self.center)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([SIDE_WIDTH, 1100])
        self.setCentralWidget(self.splitter)

        self._plugin_menus = {}
        self._build_actions()
        self._build_toolbars()
        self._build_status_bar()
        self._build_menus()

        self.plugins = PluginManager(self, plugin_folders or [], home)
        self.plugins.discover()
        self.plugins.load_enabled()
        self._update_title()
        self._update_actions()
        self._update_page_label()
        self.side.setVisible(False)

        if self.settings.get("geometry"):
            from PySide6.QtCore import QByteArray

            self.restoreGeometry(QByteArray.fromBase64(self.settings["geometry"].encode()))
        self._fit_to_screen()
        self._fitted_on_show = False

    def _fit_to_screen(self):
        if self.isMaximized() or self.isFullScreen():
            return
        frame = self.frameGeometry()
        fitted = fit_rect(frame, self.screen().availableGeometry())
        if fitted != frame:
            self.resize(fitted.width() - (frame.width() - self.width()), fitted.height() - (frame.height() - self.height()))
            self.move(fitted.topLeft())

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fitted_on_show:
            self._fitted_on_show = True
            # The title bar's size is only known once the window is really on screen.
            QTimer.singleShot(0, self._fit_to_screen)

    def _action(self, text, callback, shortcut=None, needs_document=True):
        action = QAction(text, self)
        action.triggered.connect(lambda _checked=False: callback())
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if needs_document:
            self._document_actions.append(action)
        return action

    def _build_actions(self):
        self._document_actions = []
        a = self._action
        self.act_open = a("Open...", self.open_dialog, QKeySequence.Open, needs_document=False)
        self.act_save = a("Save", self.save, QKeySequence.Save)
        self.act_save_as = a("Save As...", self.save_as, QKeySequence.SaveAs)
        self.act_print = a("Print...", self.print_document, QKeySequence.Print)
        self.act_close = a("Close Tab", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W")
        self.act_quit = a("Exit", self.close, needs_document=False)
        self.act_undo = a("Undo", self._undo, QKeySequence.Undo)
        self.act_redo = a("Redo", self._redo, QKeySequence.Redo)
        self.act_copy = a("Copy", lambda: self._with_view(lambda v: v.copy_selection()), QKeySequence.Copy)
        self.act_select_page = a("Select Page Text", lambda: self._with_view(lambda v: v.select_page()), QKeySequence.SelectAll)
        self.act_find = a("Find...", self._focus_search, QKeySequence.Find)
        self.act_zoom_in = a("Zoom In", lambda: self._zoom_by(1.2), QKeySequence.ZoomIn)
        self.act_zoom_out = a("Zoom Out", lambda: self._zoom_by(1 / 1.2), QKeySequence.ZoomOut)
        self.act_fit_width = a("Fit Width", lambda: self._with_view(lambda v: v.set_fit("width")), "Ctrl+1")
        self.act_fit_page = a("Fit Page", lambda: self._with_view(lambda v: v.set_fit("page")), "Ctrl+2")
        self.act_go_to = a("Go to Page...", self._go_to_dialog, "Ctrl+G")
        self.act_actual_size = a("Actual Size", lambda: self._with_view(lambda v: v.set_zoom(1.0)), "Ctrl+0")
        self.act_full_screen = a("Full Screen", self._toggle_full_screen, "F11", needs_document=False)

    def _build_toolbars(self):
        main = QToolBar("Main", objectName="main-toolbar", movable=False, floatable=False)
        main.setIconSize(QSize(18, 18))
        main.setContextMenuPolicy(Qt.PreventContextMenu)
        for action, icon in (
            (self.act_open, "open"),
            (self.act_save, "save"),
            (self.act_print, "print"),
            (self.act_undo, "undo"),
            (self.act_redo, "redo"),
            (self.act_zoom_in, "plus"),
            (self.act_zoom_out, "minus"),
        ):
            theme.bind(action, icon)
        main.addAction(self.act_open)
        main.addAction(self.act_save)
        main.addAction(self.act_print)
        main.addSeparator()
        main.addAction(self.act_undo)
        main.addAction(self.act_redo)
        main.addSeparator()
        self.tool_group = QActionGroup(self)
        self.tool_actions = {}
        for tool, label, icon in ANNOTATION_TOOLS:
            action = QAction(label, self, checkable=True)
            theme.bind(action, icon)
            action.triggered.connect(lambda _c=False, t=tool: self._set_tool(t))
            self.tool_group.addAction(action)
            main.addAction(action)
            self.tool_actions[tool] = action
            self._document_actions.append(action)
        self.tool_actions["select"].setChecked(True)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        main.addWidget(spacer)
        self.addToolBar(main)
        self.main_toolbar = main

    def _status_button(self, tip, icon, callback):
        button = QToolButton(toolTip=tip)
        button.setIconSize(QSize(15, 15))
        theme.bind(button, icon, "muted")
        button.clicked.connect(lambda _c=False: callback())
        return button

    def _build_status_bar(self):
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        bar.setContentsMargins(6, 0, 6, 0)
        self.page_input = QLineEdit(maximumWidth=44, alignment=Qt.AlignCenter)
        self.page_input.returnPressed.connect(self._on_page_input)
        self.page_total = QLabel(" / 0 ")
        self.zoom_box = QComboBox(editable=True, minimumWidth=108)
        self.zoom_box.addItems(ZOOM_PRESETS)
        self.zoom_box.activated.connect(lambda _i: self._on_zoom_box())
        self.zoom_box.lineEdit().returnPressed.connect(self._on_zoom_box)
        controls = QWidget()
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 3, 0, 3)
        row.setSpacing(2)
        row.addWidget(self._status_button("Previous page", "left", lambda: self._step_page(-1)))
        row.addWidget(self.page_input)
        row.addWidget(self.page_total)
        row.addWidget(self._status_button("Next page", "right", lambda: self._step_page(1)))
        row.addSpacing(14)
        row.addWidget(self._status_button("Zoom out", "minus", lambda: self._zoom_by(1 / 1.2)))
        row.addWidget(self.zoom_box)
        row.addWidget(self._status_button("Zoom in", "plus", lambda: self._zoom_by(1.2)))
        self.page_controls = controls
        bar.addPermanentWidget(controls)

    def _step_page(self, delta):
        self._with_view(lambda v: v.go_to_page(v.current_page + delta))

    def _build_menus(self):
        bar = self.menuBar()
        self.menu_file = bar.addMenu("&File")
        self.menu_file.addAction(self.act_open)
        self.recent_menu = self.menu_file.addMenu("Open Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        self.menu_file.addSeparator()
        for action in (self.act_save, self.act_save_as, self.act_print):
            self.menu_file.addAction(action)
        self.menu_file.addSeparator()
        self.menu_file.addAction(self.act_close)
        self.menu_file.addAction(self.act_quit)

        menu = bar.addMenu("&Edit")
        for action in (self.act_undo, self.act_redo, self.act_copy, self.act_select_page, self.act_find):
            menu.addAction(action)

        menu = bar.addMenu("&View")
        for action in (self.act_zoom_in, self.act_zoom_out, self.act_actual_size, self.act_fit_width, self.act_fit_page, self.act_go_to, self.act_full_screen):
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(self._action("Show or Hide Side Panel", self._toggle_side, "F4", needs_document=False))
        theme_menu = menu.addMenu("Theme")
        self.theme_group = QActionGroup(self)
        current = self.settings.get("theme", "system")
        for mode, label in (("system", "Match Windows"), ("light", "Light"), ("dark", "Dark")):
            action = QAction(label, self, checkable=True, checked=mode == current)
            action.triggered.connect(lambda _c=False, m=mode: self.set_theme(m))
            self.theme_group.addAction(action)
            theme_menu.addAction(action)

        menu = bar.addMenu("&Pages")
        d = self._document_action_on
        d(menu, "Rotate Right", lambda: self._rotate(90), "Ctrl+R")
        d(menu, "Rotate Left", lambda: self._rotate(-90), "Ctrl+Shift+R")
        d(menu, "Delete Pages", self._delete_pages, "Ctrl+Delete")
        d(menu, "Extract Pages...", self._extract_pages)
        menu.addSeparator()
        d(menu, "Insert Blank Page", self._insert_blank)
        d(menu, "Insert PDF...", self._insert_pdf)
        menu.addSeparator()
        d(menu, "Add Page Numbers", self._add_page_numbers)
        d(menu, "Add Watermark...", self._add_watermark)

        menu = bar.addMenu("&Tools")
        menu.addAction(self._action("Merge PDFs...", self._merge_dialog, needs_document=False))
        d(menu, "Split PDF...", self._split_dialog)
        d(menu, "Compress...", self._compress)
        menu.addSeparator()
        d(menu, "Set or Remove Password...", self._set_password)
        menu.addSeparator()
        d(menu, "Export Pages as Images...", self._export_images)
        d(menu, "Export Text...", self._export_text)

        self.menu_plugins = bar.addMenu("Pl&ugins")
        self.menu_plugins.addAction(self._action("Manage Plugins...", self._manage_plugins, needs_document=False))
        self.menu_plugins.addSeparator()

        menu = bar.addMenu("&Help")
        menu.addAction(self._action("Open Log Folder", self._open_logs, needs_document=False))
        menu.addAction(self._action(f"About {APP_NAME}", self._about, needs_document=False))

    def _document_action_on(self, menu, text, callback, shortcut=None):
        menu.addAction(self._action(text, callback, shortcut))

    # Plugin hooks
    def plugin_menu(self, title):
        for action in self.menuBar().actions():
            if action.menu() and action.text().replace("&", "") == title:
                return action.menu()
        if title not in self._plugin_menus:
            menu = self.menuBar().addMenu(title)
            self._plugin_menus[title] = menu
        return self._plugin_menus[title]

    def plugin_toolbar(self):
        return self.main_toolbar

    def prune_plugin_ui(self):
        for title, menu in list(self._plugin_menus.items()):
            if menu.isEmpty():
                self.menuBar().removeAction(menu.menuAction())
                del self._plugin_menus[title]

    def _toggle_side(self):
        self.side.set_collapsed(self.side.is_open())

    def _toggle_full_screen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _open_logs(self):
        folder = os.path.join(self.home, "logs")
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def set_theme(self, mode):
        self.settings["theme"] = mode
        save_json(self.settings_path, self.settings)
        theme.apply(QApplication.instance(), mode)

    def views(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def current_view(self):
        return self.tabs.currentWidget()

    def _with_view(self, callback):
        view = self.current_view()
        if view:
            callback(view)

    # Opening and closing
    def open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Open PDF", self._last_folder(), PDF_FILTER)
        for path in paths:
            self.open_path(path)

    def _last_folder(self):
        recent = self.settings.get("recent", [])
        return os.path.dirname(recent[0]) if recent else os.path.expanduser("~")

    def open_path(self, path):
        path = os.path.abspath(path)
        for view in self.views():
            if view.document.path and os.path.normcase(view.document.path) == os.path.normcase(path):
                self.tabs.setCurrentWidget(view)
                return view
        document = self._load_document(path)
        if document is None:
            return None
        try:
            view = PdfView(document)
        except Exception as e:
            # A damaged page tree can open fine and only fail once the pages are loaded.
            log.warning("Could not lay out %s: %s", path, e)
            document.close()
            QMessageBox.warning(self, APP_NAME, f"Could not open {os.path.basename(path)}. The file looks damaged.\n\n{e}")
            return None
        view.context_hook = self._on_context_menu
        view.current_page_changed.connect(self._update_page_label)
        view.zoom_changed.connect(self._update_zoom_box)
        view.tool_finished.connect(self._sync_tool_actions)
        document.state_changed.connect(self._on_document_state)
        document.changed.connect(lambda structural, d=document: self.plugins.emit("document_changed", d, structural))
        self.tabs.addTab(view, document.title)
        self.tabs.setCurrentWidget(view)
        self._restore_view(view)
        self._add_recent(path)
        self.plugins.emit("document_opened", document)
        return view

    def _restore_view(self, view):
        saved = self.settings.get("views", {}).get(os.path.normcase(view.document.path))
        if not isinstance(saved, list) or len(saved) != 3:
            return
        page, zoom, fit = saved
        if fit in ("width", "page"):
            view.set_fit(fit)
        elif isinstance(zoom, (int, float)):
            view.set_zoom(zoom)
        if isinstance(page, int):
            view.go_to_page(page)

    def _remember_view(self, view):
        if not view.document.path:
            return
        views = self.settings.setdefault("views", {})
        key = os.path.normcase(view.document.path)
        # Most recent last, so the oldest is the one to drop.
        views.pop(key, None)
        views[key] = [view.current_page, view.zoom, view.fit_mode]
        while len(views) > MAX_REMEMBERED_VIEWS:
            del views[next(iter(views))]

    def _load_document(self, path):
        password = None
        while True:
            try:
                return PdfDocument(path, password=password)
            except PasswordRequired:
                prompt = "This PDF needs a password:" if password is None else "That password didn't work. Try again:"
                password, ok = QInputDialog.getText(self, "Password", prompt, QLineEdit.Password)
                if not ok:
                    return None
            except Exception as e:
                QMessageBox.warning(self, APP_NAME, f"Could not open {os.path.basename(path)}.\n\n{e}")
                return None

    def _add_recent(self, path):
        recent = [p for p in self.settings.get("recent", []) if os.path.normcase(p) != os.path.normcase(path)]
        self.settings["recent"] = [path] + recent[: MAX_RECENT - 1]
        save_json(self.settings_path, self.settings)
        self.welcome.set_recent(self.settings["recent"])

    def _fill_recent(self):
        self.recent_menu.clear()
        recent = [p for p in self.settings.get("recent", []) if os.path.exists(p)]
        if not recent:
            self.recent_menu.addAction("No recent files").setEnabled(False)
        for path in recent:
            self.recent_menu.addAction(path, lambda p=path: self.open_path(p))
        if recent:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction("Clear Recent Files", self.clear_recent)

    def clear_recent(self):
        """Forget which files were opened, and the page each one was on."""
        self.settings["recent"] = []
        self.settings["views"] = {}
        save_json(self.settings_path, self.settings)
        self.welcome.set_recent([])

    def close_tab(self, index):
        view = self.tabs.widget(index)
        if view is None or not self._confirm_discard(view):
            return False
        self._remember_view(view)
        save_json(self.settings_path, self.settings)
        self.tabs.removeTab(index)
        self.thumbnails.forget(view.document)
        self.plugins.emit("document_closed", view.document)
        view.document.close()
        view.deleteLater()
        return True

    def _confirm_discard(self, view):
        if not view.document.dirty:
            return True
        self.tabs.setCurrentWidget(view)
        answer = QMessageBox.question(
            self,
            APP_NAME,
            f"Save changes to {view.document.title}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if answer == QMessageBox.Save:
            return self.save()
        return answer == QMessageBox.Discard

    def closeEvent(self, event):
        for view in self.views():
            if not self._confirm_discard(view):
                event.ignore()
                return
        for view in self.views():
            self._remember_view(view)
        self.settings["geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        save_json(self.settings_path, self.settings)
        self.plugins.shutdown()
        event.accept()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".pdf"):
                self.open_path(path)

    # Saving and printing
    def save(self):
        view = self.current_view()
        if not view:
            return False
        if not view.document.path:
            return self.save_as()
        return self._save_to(view, view.document.path)

    def save_as(self):
        view = self.current_view()
        if not view:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Save As", view.document.path or "", PDF_FILTER)
        return self._save_to(view, path) if path else False

    def _save_to(self, view, path):
        try:
            view.document.save(path)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Could not save the PDF. Is it open in another program?\n\n{e}")
            return False
        self._add_recent(path)
        self.statusBar().showMessage(f"Saved {path}", 4000)
        return True

    def print_document(self):
        view = self.current_view()
        if not view:
            return
        printer = QPrinter(QPrinter.HighResolution)
        if QPrintDialog(printer, self).exec() != QDialog.Accepted:
            return
        import pymupdf
        from PySide6.QtGui import QImage

        painter = QPainter(printer)
        first = max(printer.fromPage() - 1, 0)
        last = printer.toPage() - 1 if printer.toPage() else len(view.document) - 1
        for index in range(first, min(last, len(view.document) - 1) + 1):
            if index > first:
                printer.newPage()
            pix = view.document.page(index).get_pixmap(dpi=min(printer.resolution(), 300), alpha=False, annots=True)
            image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
            target = painter.viewport()
            size = image.size().scaled(target.size(), Qt.KeepAspectRatio)
            painter.setViewport(target.x(), target.y(), size.width(), size.height())
            painter.setWindow(image.rect())
            painter.drawImage(0, 0, image)
            painter.setViewport(target)
        painter.end()

    # State
    def _on_tab_changed(self, _index):
        view = self.current_view()
        self.center.setCurrentWidget(self.tabs if view else self.welcome)
        self.side.setVisible(view is not None)
        self.thumbnails.set_view(view)
        self.outline.set_view(view)
        self.search.set_view(view)
        self._update_title()
        self._update_actions()
        self._update_page_label()
        if view:
            self._update_zoom_box(view.zoom)
            self._sync_tool_actions()
        self.plugins.emit("current_view_changed", view)

    def _on_document_state(self):
        for i, view in enumerate(self.views()):
            marker = "*" if view.document.dirty else ""
            self.tabs.setTabText(i, view.document.title + marker)
        self._update_title()
        self._update_actions()
        self._update_page_label()

    def _update_title(self):
        view = self.current_view()
        if view:
            marker = "*" if view.document.dirty else ""
            self.setWindowTitle(f"{view.document.title}{marker} - {APP_NAME}")
        else:
            self.setWindowTitle(APP_NAME)

    def _update_actions(self):
        view = self.current_view()
        for action in self._document_actions:
            action.setEnabled(view is not None)
        self.act_undo.setEnabled(bool(view and view.document.can_undo()))
        self.act_redo.setEnabled(bool(view and view.document.can_redo()))

    def _update_page_label(self, _page=None):
        view = self.current_view()
        if view:
            self.page_input.setText(str(view.current_page + 1))
            self.page_total.setText(f" / {len(view.document)} ")
        else:
            self.page_input.clear()
            self.page_total.setText(" / 0 ")
        self.page_controls.setVisible(view is not None)

    def _update_zoom_box(self, zoom):
        view = self.current_view()
        if not view:
            return
        labels = {"width": "Fit width", "page": "Fit page"}
        self.zoom_box.setCurrentText(labels.get(view.fit_mode, f"{round(zoom * 100)}%"))

    def _on_page_input(self):
        view = self.current_view()
        text = self.page_input.text().strip()
        if view and text.isdecimal():
            view.go_to_page(int(text) - 1)
            view.setFocus()
        self._update_page_label()

    def _on_zoom_box(self):
        view = self.current_view()
        if not view:
            return
        text = self.zoom_box.currentText().strip().lower()
        if text == "fit width":
            view.set_fit("width")
        elif text == "fit page":
            view.set_fit("page")
        else:
            try:
                view.set_zoom(float(text.rstrip("%")) / 100)
            except ValueError:
                self._update_zoom_box(view.zoom)

    def _zoom_by(self, factor):
        self._with_view(lambda v: v.set_zoom(v.zoom * factor))

    def _set_tool(self, tool):
        self._with_view(lambda v: v.set_tool(tool))

    def _sync_tool_actions(self):
        view = self.current_view()
        if view and view.tool in self.tool_actions:
            self.tool_actions[view.tool].setChecked(True)

    def _focus_search(self):
        self.side.show_panel("search")
        self.search.focus()

    def _go_to_dialog(self):
        view = self.current_view()
        if not view:
            return
        page, ok = QInputDialog.getInt(self, "Go to page", "Page:", view.current_page + 1, 1, len(view.document))
        if ok:
            view.go_to_page(page - 1)

    def _undo(self):
        self._with_view(lambda v: v.document.undo())

    def _redo(self):
        self._with_view(lambda v: v.document.redo())

    def _on_context_menu(self, menu, view, index, point):
        word = view.nearest_word(index, point[0], point[1], max_distance=30)
        context = ContextInfo(view, view.document, index, point, word, view.selection())
        items = self.plugins.context_items(context)
        if items and not menu.isEmpty():
            menu.addSeparator()
        for label, callback in items:
            menu.addAction(label, callback)

    # Page tools
    def _target_pages(self):
        view = self.current_view()
        return self.thumbnails.selected_pages() or [view.current_page]

    def _guarded(self, title, callback):
        try:
            return callback()
        except Exception as e:
            QMessageBox.warning(self, title, str(e))
            return None

    def _rotate(self, degrees):
        view = self.current_view()
        pages = self._target_pages()
        current = view.current_page
        self._guarded("Rotate", lambda: view.document.rotate_pages(pages, degrees))
        view.go_to_page(current)

    def _delete_pages(self):
        view = self.current_view()
        pages = self._target_pages()
        label = f"page {pages[0] + 1}" if len(pages) == 1 else f"{len(pages)} pages"
        if QMessageBox.question(self, "Delete pages", f"Delete {label}? You can undo this until you close the file.") == QMessageBox.Yes:
            self._guarded("Delete pages", lambda: view.document.delete_pages(pages))

    def _on_pages_reordered(self, order):
        view = self.current_view()
        if view:
            self._guarded("Move pages", lambda: view.document.move_pages(order))

    def _extract_pages(self):
        view = self.current_view()
        default = ",".join(str(p + 1) for p in self._target_pages())
        text, ok = QInputDialog.getText(self, "Extract pages", "Pages (for example 1-3, 7):", text=default)
        if not ok:
            return
        groups = self._guarded("Extract pages", lambda: tools.parse_ranges(text, len(view.document)))
        if not groups:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save extracted pages", "", PDF_FILTER)
        if path:
            pages = [page for group in groups for page in group]
            self._guarded("Extract pages", lambda: tools.save_pages(view.document, pages, path))

    def _insert_blank(self):
        view = self.current_view()
        at = view.current_page + 1
        self._guarded("Insert page", lambda: view.document.insert_blank(at))
        view.go_to_page(at)

    def _insert_pdf(self):
        view = self.current_view()
        path, _ = QFileDialog.getOpenFileName(self, "Insert PDF", "", PDF_FILTER)
        if path:
            self._guarded("Insert PDF", lambda: view.document.insert_file(path, view.current_page + 1))

    def _add_page_numbers(self):
        view = self.current_view()
        self._guarded("Page numbers", lambda: tools.add_page_numbers(view.document))

    def _add_watermark(self):
        view = self.current_view()
        text, ok = QInputDialog.getText(self, "Add watermark", "Watermark text:", text="DRAFT")
        if ok and text.strip():
            self._guarded("Watermark", lambda: tools.add_watermark(view.document, text.strip()))

    # File tools
    def _merge_dialog(self):
        dialog = MergeDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        paths = dialog.paths()
        path, _ = QFileDialog.getSaveFileName(self, "Save merged PDF", "Merged.pdf", PDF_FILTER)
        if path and self._guarded("Merge", lambda: tools.merge_files(paths, path) or True):
            self.open_path(path)

    def _split_dialog(self):
        view = self.current_view()
        text, ok = QInputDialog.getText(
            self,
            "Split PDF",
            "One file per range (for example 1-3, 4-9),\nor a single number to split every N pages:",
        )
        if not ok or not text.strip():
            return
        folder = QFileDialog.getExistingDirectory(self, "Save the new PDFs in")
        if not folder:
            return
        stem = os.path.splitext(view.document.title)[0]
        if text.strip().isdigit():
            size = max(1, int(text))
            result = self._guarded("Split", lambda: tools.split_every(view.document, size, folder, stem))
        else:
            result = self._guarded(
                "Split",
                lambda: tools.split_ranges(view.document, tools.parse_ranges(text, len(view.document)), folder, stem),
            )
        if result:
            self.statusBar().showMessage(f"Created {len(result)} PDFs in {folder}", 6000)

    def _compress(self):
        view = self.current_view()
        stem = os.path.splitext(view.document.title)[0]
        path, _ = QFileDialog.getSaveFileName(self, "Save compressed copy", f"{stem} (compressed).pdf", PDF_FILTER)
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            size = self._guarded("Compress", lambda: tools.compress(view.document, path))
        finally:
            QApplication.restoreOverrideCursor()
        if size:
            self.statusBar().showMessage(f"Saved compressed copy ({size / 1024 / 1024:.1f} MB)", 6000)

    def _set_password(self):
        view = self.current_view()
        password, ok = QInputDialog.getText(
            self,
            "PDF password",
            "New password (leave empty to remove it). It applies the next time you save:",
            QLineEdit.Password,
        )
        if ok:
            view.document.password = password or None
            view.document.dirty = True
            view.document.state_changed.emit()

    def _export_images(self):
        view = self.current_view()
        folder = QFileDialog.getExistingDirectory(self, "Save page images in")
        if folder:
            stem = os.path.splitext(view.document.title)[0]
            result = self._guarded("Export images", lambda: tools.export_images(view.document, folder, stem))
            if result:
                self.statusBar().showMessage(f"Saved {len(result)} images in {folder}", 6000)

    def _export_text(self):
        view = self.current_view()
        stem = os.path.splitext(view.document.title)[0]
        path, _ = QFileDialog.getSaveFileName(self, "Export text", f"{stem}.txt", "Text files (*.txt)")
        if path:
            self._guarded("Export text", lambda: tools.export_text(view.document, path))

    def _manage_plugins(self):
        PluginDialog(self.plugins, self).exec()

    def _about(self):
        QMessageBox.about(self, APP_NAME, f"{APP_NAME} {__version__}\n\nA PDF reader and editor with plugins.")


class MergeDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Merge PDFs")
        self.resize(560, 360)
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        add = QPushButton("Add files...")
        remove = QPushButton("Remove")
        add.clicked.connect(self._add)
        remove.clicked.connect(lambda: [self.list.takeItem(self.list.row(i)) for i in self.list.selectedItems()])
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Files are merged from top to bottom. Drag to change the order."))
        layout.addWidget(self.list)
        layout.addLayout(row)
        layout.addWidget(buttons)

    def _add(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add PDFs", "", PDF_FILTER)
        self.list.addItems(paths)

    def _accept(self):
        if self.list.count() >= 2:
            self.accept()
        else:
            QMessageBox.information(self, "Merge PDFs", "Add at least two PDFs.")

    def paths(self):
        return [self.list.item(i).text() for i in range(self.list.count())]


class PluginDialog(QDialog):
    def __init__(self, manager, parent):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Plugins")
        self.resize(720, 340)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["On", "Plugin", "Version", "Description"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(True)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.error = QLabel("", wordWrap=True, textInteractionFlags=Qt.TextSelectableByMouse)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(
            QLabel(
                "Plugins run with the same access to your files as this app, and nothing limits what they do. "
                "Ones you add stay off until you turn them on.\n"
                f"Add your own by dropping a plugin folder into:\n{os.path.join(manager.home, 'plugins')}",
                wordWrap=True,
                textFormat=Qt.PlainText,
            )
        )
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self._fill()
        self.table.itemChanged.connect(self._on_item_changed)

    def showEvent(self, event):
        super().showEvent(event)
        # Descriptions can only wrap once the table knows its real width.
        self.table.resizeRowsToContents()

    def _fill(self):
        plugins = list(self.manager.plugins.values())
        self.table.blockSignals(True)
        self.table.setRowCount(len(plugins))
        errors = []
        for row, info in enumerate(plugins):
            box = QTableWidgetItem()
            # A plugin with a bad manifest can't be turned on; its code never runs.
            box.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled if not info.invalid else Qt.NoItemFlags)
            box.setCheckState(Qt.Checked if info.active else Qt.Unchecked)
            box.setData(Qt.UserRole, info.id)
            self.table.setItem(row, 0, box)
            self.table.setItem(row, 1, QTableWidgetItem(clip(info.name, PLUGIN_TEXT_LIMITS["name"])))
            self.table.setItem(row, 2, QTableWidgetItem(clip(info.version, PLUGIN_TEXT_LIMITS["version"])))
            self.table.setItem(row, 3, QTableWidgetItem(clip(info.description, PLUGIN_TEXT_LIMITS["description"])))
            if info.error:
                errors.append(f"{info.name}: {info.error.strip().splitlines()[-1]}")
        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()
        self.table.blockSignals(False)
        self.error.setText("\n".join(errors))

    def _on_item_changed(self, item):
        if item.column() != 0:
            return
        plugin_id = item.data(Qt.UserRole)
        enabled = item.checkState() == Qt.Checked
        if enabled and self.manager.needs_approval(plugin_id):
            info = self.manager.plugins[plugin_id]
            answer = QMessageBox.warning(
                self,
                "Turn on this plugin?",
                f"{clip(info.name, PLUGIN_TEXT_LIMITS['name'])} will run as a program on this computer, "
                f"with access to all your files.\n\nFolder: {info.folder}\n\nOnly turn it on if you trust where it came from.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                self._fill()
                return
            self.manager.approve(plugin_id)
        self.manager.set_enabled(plugin_id, enabled)
        self._fill()
