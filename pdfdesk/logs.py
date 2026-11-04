"""A rotating log file, and a dialog instead of a silent failure when something goes wrong."""

import logging
import logging.handlers
import os
import sys
import traceback

from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME

MAX_BYTES = 1024 * 1024
BACKUPS = 3

log = logging.getLogger("pdfdesk")
_shown = set()


def log_path(home):
    return os.path.join(home, "logs", "pdfdesk.log")


def _on_qt_message(kind, _context, message):
    if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        log.warning("Qt: %s", message)


def _on_exception(kind, value, tb, path):
    log.error("Unhandled error\n%s", "".join(traceback.format_exception(kind, value, tb)))
    # A failure while painting repeats on every repaint; only say so once.
    where = traceback.extract_tb(tb)[-1] if tb else None
    key = (kind, where.filename, where.lineno) if where else (kind,)
    if key in _shown or QApplication.instance() is None:
        return
    _shown.add(key)
    QMessageBox.critical(
        None,
        APP_NAME,
        f"Something went wrong, but you can keep working. Save your changes if you can.\n\n{value}\n\nDetails are in:\n{path}",
    )


def setup(home):
    path = log_path(home)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    qInstallMessageHandler(_on_qt_message)
    sys.excepthook = lambda kind, value, tb: _on_exception(kind, value, tb, path)
    return path
