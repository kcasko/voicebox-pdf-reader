import ctypes
import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME, logs
from .main_window import MainWindow
from .settings import APP_HOME
from .single_instance import InstanceServer, send_to_running

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_USER_MODEL_ID = "PDFDesk.PDFDesk"


def plugin_folders():
    return [os.path.join(BASE_DIR, "plugins"), os.path.join(APP_HOME, "plugins")]


def is_openable(path):
    return path.lower().endswith(".pdf") and os.path.exists(path)


def main():
    # Keeps the taskbar button and pinned shortcut together as one app.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(os.path.join(BASE_DIR, "assets", "pdfdesk.ico")))
    logs.setup(APP_HOME)
    arguments = app.arguments()[1:]
    if len(arguments) == 2 and arguments[0] == "--self-check":
        from .selfcheck import run

        run(arguments[1], plugin_folders())
    safe_mode = "--no-plugins" in arguments
    paths = [a for a in arguments if a != "--no-plugins"]
    if send_to_running(APP_HOME, [p for p in paths if is_openable(p)]):
        return 0
    window = MainWindow([] if safe_mode else plugin_folders())
    window.show()
    for path in paths:
        if is_openable(path):
            window.open_path(path)

    def on_other_launch(others):
        for path in others:
            if is_openable(path):
                window.open_path(path)
        if window.isMinimized():
            window.showNormal()
        window.raise_()
        window.activateWindow()

    server = InstanceServer(APP_HOME)
    server.paths_received.connect(on_other_launch)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
