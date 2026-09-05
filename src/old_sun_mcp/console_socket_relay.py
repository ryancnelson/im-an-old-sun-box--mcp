"""Small stdlib relay executed inside a selected container; no shell or guest input."""

import os
import selectors
import socket
import sys


def relay(path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.connect(path)
        connection.settimeout(None)
        os.write(2, b"OLD_SUN_CONSOLE_READY\n")
        with selectors.DefaultSelector() as events:
            events.register(0, selectors.EVENT_READ)
            events.register(connection, selectors.EVENT_READ)
            while True:
                for key, _ in events.select():
                    if key.fileobj == 0:
                        data = os.read(0, 65536)
                        if data:
                            connection.sendall(data)
                        else:
                            connection.shutdown(socket.SHUT_WR)
                            events.unregister(0)
                    else:
                        data = connection.recv(65536)
                        if not data:
                            return
                        remaining = memoryview(data)
                        while remaining:
                            remaining = remaining[os.write(1, remaining):]


if __name__ == "__main__":
    relay(sys.argv[1])
