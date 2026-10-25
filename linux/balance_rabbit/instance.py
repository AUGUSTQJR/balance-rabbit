"""单实例：开机自启 + 手动启动时不会出现两只兔子。"""

from __future__ import annotations

import fcntl
import os

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .settings import CONFIG_DIR, LOCK_FILE


def server_name() -> str:
    return "balance-rabbit-%d" % os.getuid()


class SingleInstance(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._fd: int | None = None
        self._server: QLocalServer | None = None
        self.on_show = None

    def claim(self) -> bool:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            self._fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
        except OSError:
            return True
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self._fd)
            self._fd = None
            return False

        QLocalServer.removeServer(server_name())
        server = QLocalServer(self)
        server.newConnection.connect(self._on_new_connection)
        server.listen(server_name())
        self._server = server
        return True

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        connection = self._server.nextPendingConnection()
        if connection is None:
            return

        def read_message() -> None:
            data = bytes(connection.readAll()).decode("utf-8", "ignore")
            if "show" in data and self.on_show is not None:
                self.on_show()
            connection.disconnectFromServer()

        connection.readyRead.connect(read_message)
        connection.disconnected.connect(connection.deleteLater)

    def notify_existing(self) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(server_name())
        if not socket.waitForConnected(400):
            return False
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(400)
        socket.disconnectFromServer()
        return True

    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
