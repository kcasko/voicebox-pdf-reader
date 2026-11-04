import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME
from .main_window import MainWindow
from .settings import APP_HOME

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def plugin_folders():
    return [os.path.join(BASE_DIR, "plugins"), os.path.join(APP_HOME, "plugins")]


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(os.path.join(BASE_DIR, "assets", "pdfdesk.ico")))
    arguments = app.arguments()[1:]
    if len(arguments) == 2 and arguments[0] == "--self-check":
        from .selfcheck import run

        run(arguments[1], plugin_folders())
    window = MainWindow(plugin_folders())
    window.show()
    for path in arguments:
        if path.lower().endswith(".pdf") and os.path.exists(path):
            window.open_path(path)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
