"""One window per user: a second launch hands its PDFs to the first and exits."""

import hashlib
import json
import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

CONNECT_TIMEOUT_MS = 500
WRITE_TIMEOUT_MS = 2000


def server_name(home):
    return "PDFDesk-" + hashlib.sha1(os.path.normcase(os.path.abspath(home)).encode("utf-8")).hexdigest()[:16]


def send_to_running(home, paths):
    """Return True if another instance took over."""
    socket = QLocalSocket()
    socket.connectToServer(server_name(home))
    if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
        return False
    socket.write(json.dumps([os.path.abspath(p) for p in paths]).encode("utf-8") + b"\n")
    socket.waitForBytesWritten(WRITE_TIMEOUT_MS)
    socket.disconnectFromServer()
    return True


class InstanceServer(QObject):
    """Emits paths_received with the PDFs another launch asked to open (possibly none)."""

    paths_received = Signal(list)

    def __init__(self, home, parent=None):
        super().__init__(parent)
        self._server = QLocalServer(self)
        name = server_name(home)
        # A crashed instance can leave its name behind.
        QLocalServer.removeServer(name)
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(name)

    def _on_connection(self):
        socket = self._server.nextPendingConnection()
        buffer = bytearray()

        def read():
            buffer.extend(bytes(socket.readAll()))
            if not buffer.endswith(b"\n"):
                return
            socket.readyRead.disconnect(read)
            socket.deleteLater()
            try:
                paths = json.loads(buffer.decode("utf-8"))
            except ValueError:
                return
            if isinstance(paths, list):
                self.paths_received.emit([p for p in paths if isinstance(p, str)])

        socket.readyRead.connect(read)
        # A quick sender may have finished before this ran, so readyRead won't fire again.
        if socket.bytesAvailable():
            read()
