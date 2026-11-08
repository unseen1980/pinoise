"""Bounded, read-only local telemetry."""

import hashlib
import json
import os
import pathlib
import queue
import socket
import threading
import time
import uuid


def application_digest():
    root = pathlib.Path(__file__).resolve().parent
    h = hashlib.sha256()
    for path in sorted(root.glob("*.py")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


class Broker:
    def __init__(self, path, metadata):
        self.path = path
        self.metadata = dict(metadata)
        self.metadata.update(
            kind="hello",
            schema=2,
            service_id=str(uuid.uuid4()),
            application_sha256=application_digest(),
        )
        self.stop_event = threading.Event()
        self.clients = {}
        self.lock = threading.Lock()
        self.listener = None
        self.thread = None
        self.inode = None

    def start(self):
        parent = os.path.dirname(self.path)
        os.makedirs(parent, exist_ok=True)
        if os.path.exists(self.path):
            probe = socket.socket(socket.AF_UNIX)
            try:
                probe.connect(self.path)
            except ConnectionRefusedError:
                os.unlink(self.path)
            else:
                raise RuntimeError("telemetry socket already in use")
            finally:
                probe.close()
        self.listener = socket.socket(socket.AF_UNIX)
        self.listener.bind(self.path)
        self.inode = os.stat(self.path).st_ino
        os.chmod(self.path, 0o660)
        self.listener.listen(4)
        self.listener.settimeout(0.2)
        self.thread = threading.Thread(target=self._accept, daemon=True, name="telemetry")
        self.thread.start()

    def _accept(self):
        while not self.stop_event.is_set():
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            client.settimeout(1)
            q = queue.Queue(maxsize=128)
            with self.lock:
                if len(self.clients) >= 4:
                    client.close()
                    continue
                self.clients[client] = q
            threading.Thread(target=self._writer, args=(client, q), daemon=True).start()

    def _writer(self, client, q):
        try:
            hello = dict(self.metadata, mono=time.monotonic(), epoch=time.time())
            client.sendall((json.dumps(hello, allow_nan=False) + "\n").encode())
            while not self.stop_event.is_set():
                try:
                    message = q.get(timeout=0.25)
                except queue.Empty:
                    continue
                client.sendall(message)
        except OSError:
            pass
        finally:
            with self.lock:
                self.clients.pop(client, None)
            client.close()

    def publish(self, event):
        payload = (json.dumps(event, separators=(",", ":"), allow_nan=False) + "\n").encode()
        with self.lock:
            for client, q in list(self.clients.items()):
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    # Slow readers cannot block acquisition or receive a truncated session.
                    try:
                        client.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

    def close(self):
        self.stop_event.set()
        if self.listener:
            self.listener.close()
        with self.lock:
            for client in list(self.clients):
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        if self.thread:
            self.thread.join(2)
        try:
            if self.inode is not None and os.stat(self.path).st_ino == self.inode:
                os.unlink(self.path)
        except FileNotFoundError:
            pass
