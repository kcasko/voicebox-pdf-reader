"""Colors, icons and the application stylesheet, in light and dark."""

import atexit
import os
import shutil
import tempfile

from PySide6.QtCore import QByteArray, QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

LIGHT = {
    "window": "#F5F3F0",
    "surface": "#FFFFFF",
    "surface_alt": "#FAF9F7",
    "hover": "#ECE9E5",
    "pressed": "#E2DEDA",
    "border": "#E2DEDA",
    "text": "#23201E",
    "muted": "#6E6964",
    "faint": "#A9A49E",
    "accent": "#C42C3C",
    "accent_hover": "#AA2332",
    "accent_soft": "#F9E6E8",
    "on_accent": "#FFFFFF",
    "canvas": "#DEDAD5",
    "shadow": "#000000",
}
DARK = {
    "window": "#191817",
    "surface": "#232120",
    "surface_alt": "#1E1D1C",
    "hover": "#302E2C",
    "pressed": "#3A3835",
    "border": "#343230",
    "text": "#EEECE9",
    "muted": "#A5A09A",
    "faint": "#6C6863",
    "accent": "#E8596A",
    "accent_hover": "#F07483",
    "accent_soft": "#47252A",
    "on_accent": "#FFFFFF",
    "canvas": "#121110",
    "shadow": "#000000",
}

ICON_SIZE = 18
FILLED_ICONS = {"play", "pause", "stop", "previous", "next"}
ICONS = {
    "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "save": '<path d="M5 3h11l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M7 3v5h8V3"/><path d="M7 21v-7h10v7"/>',
    "print": '<path d="M6 9V3h12v6"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="7" rx="1"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
    "redo": '<path d="m15 14 5-5-5-5"/><path d="M20 9H10a6 6 0 0 0 0 12h3"/>',
    "select": '<path d="M8 3h1.5A2.5 2.5 0 0 1 12 5.5v13A2.5 2.5 0 0 1 9.5 21H8"/><path d="M16 3h-1.5A2.5 2.5 0 0 0 12 5.5v13a2.5 2.5 0 0 0 2.5 2.5H16"/><path d="M9.5 12h5"/>',
    "hand": '<path d="M8 13V6a1.5 1.5 0 0 1 3 0v5"/><path d="M11 11V4.5a1.5 1.5 0 0 1 3 0V11"/><path d="M14 11V6a1.5 1.5 0 0 1 3 0v6"/><path d="M17 10a1.5 1.5 0 0 1 3 0v5a6 6 0 0 1-6 6h-2a6 6 0 0 1-5-2.7L4.3 14.2a1.6 1.6 0 0 1 2.6-1.8L8 14"/>',
    "highlight": '<path d="m15 4 5 5-9 9H6v-5z"/><path d="m12.5 6.500 5 5"/><path d="M4 21h9"/>',
    "underline": '<path d="M7 4v7a5 5 0 0 0 10 0V4"/><path d="M5 20h14"/>',
    "strike": '<path d="M4 12h16"/><path d="M16.500 7C15.700 5.300 14 4.500 12 4.500c-2.600 0-4.500 1.300-4.500 3.400 0 .8.3 1.500.8 2.100"/><path d="M7.500 17c.8 1.700 2.500 2.500 4.500 2.500 2.600 0 4.500-1.400 4.500-3.500 0-.7-.2-1.300-.6-1.800"/>',
    "note": '<path d="M4 5a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v10l-5 5H5a1 1 0 0 1-1-1z"/><path d="M15 20v-5h5"/>',
    "text": '<path d="M5 7V4h14v3"/><path d="M12 4v16"/><path d="M9 20h6"/>',
    "box": '<rect x="4" y="5" width="16" height="14" rx="2"/>',
    "draw": '<path d="m4 20 1-4L16 5a2.100 2.100 0 0 1 3 3L8 19z"/><path d="m14 7 3 3"/>',
    "pages": '<rect x="4" y="3" width="11" height="14" rx="1.500"/><path d="M19 7.500V19a2 2 0 0 1-2 2H8.500"/>',
    "outline": '<path d="M9 6h11"/><path d="M9 12h11"/><path d="M9 18h11"/><path d="M4.500 6h.01"/><path d="M4.500 12h.01"/><path d="M4.500 18h.01"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.500-3.500"/>',
    "up": '<path d="m6 15 6-6 6 6"/>',
    "down": '<path d="m6 9 6 6 6-6"/>',
    "left": '<path d="m15 6-6 6 6 6"/>',
    "right": '<path d="m9 6 6 6-6 6"/>',
    "minus": '<path d="M5 12h14"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "close": '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>',
    "check": '<path d="m5 12.500 4.500 4.500L19 7.500"/>',
    "file": '<path d="M6 3h8l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M14 3v5h5"/><path d="M8 13h8"/><path d="M8 17h6"/>',
    "volume": '<path d="M4 9.500v5h4l5 4.500V5L8 9.500z"/><path d="M16.500 9a4.500 4.500 0 0 1 0 6"/><path d="M19 6.500a8 8 0 0 1 0 11"/>',
    "export": '<path d="M12 4v11"/><path d="m7 10.500 5 5 5-5"/><path d="M4 20h16"/>',
    "play": '<path d="M7 4.500v15a1 1 0 0 0 1.500.86l12-7.500a1 1 0 0 0 0-1.720l-12-7.500A1 1 0 0 0 7 4.500z"/>',
    "pause": '<rect x="6" y="4" width="4.500" height="16" rx="1.200"/><rect x="13.500" y="4" width="4.500" height="16" rx="1.200"/>',
    "stop": '<rect x="5.500" y="5.500" width="13" height="13" rx="2"/>',
    "previous": '<rect x="4" y="5" width="2.500" height="14" rx="1"/><path d="M20 6v12a1 1 0 0 1-1.500.86l-10-6a1 1 0 0 1 0-1.720l10-6A1 1 0 0 1 20 6z"/>',
    "next": '<rect x="17.500" y="5" width="2.500" height="14" rx="1"/><path d="M4 6v12a1 1 0 0 0 1.500.86l10-6a1 1 0 0 0 0-1.720l-10-6A1 1 0 0 0 4 6z"/>',
}


def icon_pixmap(name, color, size=ICON_SIZE, ratio=2.0):
    if name in FILLED_ICONS:
        style = f'fill="{color}" stroke="none"'
    else:
        style = f'fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {style}>{ICONS[name]}</svg>'
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixels = round(size * ratio)
    pixmap = QPixmap(QSize(pixels, pixels))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, pixels, pixels))
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


STYLESHEET = """
* {{ font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 10pt; outline: 0; }}
QMainWindow, QDialog, QMessageBox {{ background: {window}; }}
QWidget {{ color: {text}; }}
QLabel {{ background: transparent; }}
QLabel#muted, QLabel#panelStatus {{ color: {muted}; }}
QLabel#panelTitle {{ font-size: 11pt; font-weight: 600; }}
QLabel#welcomeTitle {{ font-size: 24pt; font-weight: 600; }}
QLabel#welcomeBody {{ font-size: 11pt; color: {muted}; }}
QLabel#sectionLabel {{ color: {muted}; font-size: 9pt; font-weight: 600; }}
QLabel#nowReading {{ font-size: 10.500pt; }}
QWidget#welcomePage {{ background: {window}; }}

QMenuBar {{ background: {surface}; padding: 2px 6px; }}
QMenuBar::item {{ background: transparent; padding: 5px 10px; border-radius: 5px; }}
QMenuBar::item:selected {{ background: {hover}; }}
QMenu {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {hover}; color: {text}; }}
QMenu::item:disabled {{ color: {faint}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 5px 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; margin-left: 4px; }}
QMenu::indicator:checked {{ image: url("{assets}/check.png"); }}

QToolBar {{ background: {surface}; border: none; border-bottom: 1px solid {border}; padding: 6px 10px; spacing: 2px; }}
QToolBar::separator {{ background: {border}; width: 1px; margin: 5px 8px; }}
QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 6px; }}
QToolButton:hover {{ background: {hover}; }}
QToolButton:pressed {{ background: {pressed}; }}
QToolButton:checked {{ background: {accent_soft}; }}
QToolButton#primaryAction {{ background: {accent}; color: {on_accent}; font-weight: 600; padding: 6px 12px 6px 10px; }}
QToolButton#primaryAction:hover {{ background: {accent_hover}; }}
QToolButton#playButton {{ background: {accent}; border-radius: 27px; }}
QToolButton#playButton:hover {{ background: {accent_hover}; }}
QToolButton#railButton {{ padding: 8px; border-radius: 8px; }}
QWidget#rail {{ background: {surface}; border-right: 1px solid {border}; }}
QWidget#sideStack {{ background: {surface_alt}; border-right: 1px solid {border}; }}

QStatusBar {{ background: {surface}; border-top: 1px solid {border}; color: {muted}; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {muted}; }}

QTabWidget::pane {{ border: none; background: {canvas}; }}
QTabBar {{ background: {window}; qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {muted}; padding: 8px 10px 8px 14px; margin: 5px 0 0 5px; border-top-left-radius: 8px; border-top-right-radius: 8px; min-width: 110px; max-width: 260px; }}
QTabBar::tab:hover {{ background: {hover}; }}
QTabBar::tab:selected {{ background: {surface}; color: {text}; font-weight: 600; }}
QTabBar::close-button {{ image: url("{assets}/close.png"); subcontrol-position: right; border-radius: 4px; padding: 2px; }}
QTabBar::close-button:hover {{ background: {pressed}; }}

QDockWidget {{ font-weight: 600; titlebar-close-icon: url("{assets}/close.png"); }}
QDockWidget::title {{ background: {surface_alt}; padding: 10px 14px; border-left: 1px solid {border}; }}
QDockWidget::close-button, QDockWidget::float-button {{ border: none; border-radius: 4px; background: transparent; }}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{ background: {hover}; }}
QWidget#readAloudPanel {{ background: {surface_alt}; border-left: 1px solid {border}; }}
QFrame#card {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; }}
QMainWindow::separator {{ background: transparent; width: 4px; height: 4px; }}
QSplitter::handle {{ background: transparent; }}

QPushButton {{ background: {surface}; border: 1px solid {border}; border-radius: 6px; padding: 7px 14px; }}
QPushButton:hover {{ background: {hover}; }}
QPushButton:pressed {{ background: {pressed}; }}
QPushButton:disabled {{ color: {faint}; }}
QPushButton#primaryButton {{ background: {accent}; color: {on_accent}; border: none; font-weight: 600; padding: 9px 26px; }}
QPushButton#primaryButton:hover {{ background: {accent_hover}; }}
QPushButton#recentFile {{ background: transparent; border: none; text-align: left; padding: 8px 10px; }}
QPushButton#recentFile:hover {{ background: {hover}; }}
QDialogButtonBox QPushButton {{ min-width: 72px; }}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{ background: {surface}; border: 1px solid {border}; border-radius: 6px; padding: 5px 8px; selection-background-color: {accent}; selection-color: {on_accent}; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {accent}; }}
QComboBox:hover {{ background: {hover}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{assets}/down.png"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border}; border-radius: 6px; padding: 4px; selection-background-color: {hover}; selection-color: {text}; }}

QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QTableWidget::indicator {{ width: 16px; height: 16px; border: 1px solid {faint}; border-radius: 4px; background: {surface}; }}
QCheckBox::indicator:checked, QTableWidget::indicator:checked {{ background: {accent}; border-color: {accent}; image: url("{assets}/check-on.png"); }}

QListWidget, QTreeWidget, QTableWidget {{ background: transparent; border: none; }}
QListWidget::item, QTreeWidget::item {{ padding: 5px 6px; border-radius: 5px; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {hover}; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {accent_soft}; color: {text}; }}
QListWidget#thumbnails::item, QListWidget#thumbnails::item:hover, QListWidget#thumbnails::item:selected {{ background: transparent; padding: 0; }}
QTreeWidget::branch {{ background: transparent; }}
QHeaderView::section {{ background: {surface_alt}; border: none; border-bottom: 1px solid {border}; padding: 6px; color: {muted}; }}
QTableWidget {{ gridline-color: {border}; }}

QProgressBar {{ background: {hover}; border: none; border-radius: 2px; max-height: 4px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 2px; }}
QProgressDialog QProgressBar {{ max-height: 8px; border-radius: 4px; }}
QToolTip {{ background: {text}; color: {surface}; border: none; padding: 4px 8px; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle {{ background: {faint}; border-radius: 3px; }}
QScrollBar::handle:hover {{ background: {muted}; }}
QScrollBar::handle:vertical {{ min-height: 32px; }}
QScrollBar::handle:horizontal {{ min-width: 32px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; border: none; width: 0; height: 0; }}
"""


class Theme(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.mode = "system"
        self.colors = LIGHT
        self._bindings = []
        self._assets = None
        self._app = None

    @property
    def is_dark(self):
        return self.colors is DARK

    def color(self, role):
        return QColor(self.colors[role])

    def apply(self, app, mode=None):
        """Set "light", "dark" or "system", and restyle the whole app."""
        if self._app is not app:
            self._app = app
            app.setStyle("Fusion")
            app.styleHints().colorSchemeChanged.connect(self._on_system_scheme)
        self.mode = mode or self.mode
        hints = app.styleHints()
        requested = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}.get(self.mode, Qt.ColorScheme.Unknown)
        hints.setColorScheme(requested)
        if self.mode == "system":
            self.colors = DARK if hints.colorScheme() == Qt.ColorScheme.Dark else LIGHT
        else:
            self.colors = DARK if self.mode == "dark" else LIGHT
        self._write_assets()
        font = QFont("Segoe UI Variable Text", 10)
        app.setFont(font)
        app.setPalette(self._palette())
        app.setStyleSheet(STYLESHEET.format(assets=self._assets.replace("\\", "/"), **self.colors))
        for binding in list(self._bindings):
            if not self._apply_binding(*binding):
                self._bindings.remove(binding)
        self.changed.emit()

    def _on_system_scheme(self, _scheme):
        if self.mode == "system" and self._app is not None:
            dark = self._app.styleHints().colorScheme() == Qt.ColorScheme.Dark
            if dark != self.is_dark:
                self.apply(self._app)

    def _palette(self):
        c = self.colors
        palette = QPalette()
        roles = {
            QPalette.Window: "window",
            QPalette.WindowText: "text",
            QPalette.Base: "surface",
            QPalette.AlternateBase: "surface_alt",
            QPalette.Text: "text",
            QPalette.Button: "surface",
            QPalette.ButtonText: "text",
            QPalette.ToolTipBase: "text",
            QPalette.ToolTipText: "surface",
            QPalette.Highlight: "accent",
            QPalette.HighlightedText: "on_accent",
            QPalette.PlaceholderText: "faint",
            QPalette.Link: "accent",
        }
        for role, name in roles.items():
            palette.setColor(role, QColor(c[name]))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            palette.setColor(QPalette.Disabled, role, QColor(c["faint"]))
        return palette

    def _write_assets(self):
        if self._assets is None:
            self._assets = tempfile.mkdtemp(prefix="pdfdesk-theme-")
            atexit.register(shutil.rmtree, self._assets, True)
        for filename, name, role in (
            ("close.png", "close", "muted"),
            ("down.png", "down", "muted"),
            ("check.png", "check", "text"),
            ("check-on.png", "check", "on_accent"),
        ):
            icon_pixmap(name, self.colors[role], size=16).save(os.path.join(self._assets, filename))

    def icon(self, name, role="text", checked_role="accent"):
        c = self.colors
        icon = QIcon()
        icon.addPixmap(icon_pixmap(name, c[role]), QIcon.Normal, QIcon.Off)
        icon.addPixmap(icon_pixmap(name, c[checked_role]), QIcon.Normal, QIcon.On)
        icon.addPixmap(icon_pixmap(name, c["faint"]), QIcon.Disabled, QIcon.Off)
        icon.addPixmap(icon_pixmap(name, c["faint"]), QIcon.Disabled, QIcon.On)
        return icon

    def bind(self, target, name, role="text"):
        """Give an action or button an icon that follows theme changes."""
        # A bad name would otherwise fail on every later theme change, for the whole app.
        if name not in ICONS:
            raise ValueError(f"Unknown icon: {name}")
        binding = (target, name, role)
        self._bindings = [b for b in self._bindings if b[0] is not target]
        self._bindings.append(binding)
        self._apply_binding(*binding)

    def _apply_binding(self, target, name, role):
        try:
            target.setIcon(self.icon(name, role, checked_role=role if role == "on_accent" else "accent"))
            return True
        except RuntimeError:
            return False  # The widget or action has been deleted.


theme = Theme()
