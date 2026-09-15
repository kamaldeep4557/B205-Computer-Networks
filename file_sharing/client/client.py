"""One socket reader routes responses by request id and handles server events."""
import base64
import hashlib
import os
import queue
import socket
import tempfile
import threading
import uuid
from collections import deque
from pathlib import Path
from common.protocol import AppError, recv_message, send_message

class Client:
    def __init__(self, host='127.0.0.1', port=5000, timeout=120, on_notification=None):
        self.timeout = timeout
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        try:
            self.sock.connect((host, port))
        except OSError:
            self.sock.close()
            raise
        self.request_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.transfer_lock = threading.Lock()
        self.pending = {}
        self.notifications = deque(maxlen=200)
        self.events = queue.Queue(maxsize=200)
        self.on_notification = on_notification
        self.closed = threading.Event()
        self.user = None
        self.reader = threading.Thread(target=self.read_loop, daemon=True)
        self.reader.start()
        try:
            self.info = self.request('CONNECT')
        except Exception:
            self.close()
            raise
        self.heartbeat = threading.Thread(target=self.keep_alive, daemon=True)
        self.heartbeat.start()

    def read_loop(self):
        try:
            while not self.closed.is_set():
                message = recv_message(self.sock)
                if message.get('type') == 'NOTIFICATION':
                    self.notifications.append(message)
                    try:
                        self.events.put_nowait(message)
                    except queue.Full:
                        self.events.get_nowait()
                        self.events.put_nowait(message)
                    if self.on_notification:
                        self.on_notification(message)
                else:
                    with self.state_lock:
                        waiting = self.pending.get(message.get('id'))
                    if waiting:
                        waiting.put(message)
                    elif message.get('type') == 'ERROR':
                        raise AppError(message.get('code'), message.get('message'))
        except (OSError, EOFError, AppError) as exc:
            self.closed.set()
            with self.state_lock:
                for waiting in self.pending.values():
                    waiting.put({'type': 'ERROR', 'code': 'CONNECTION_LOST', 'message': str(exc)})
        finally:
            self.sock.close()

    def request(self, op, **params):
        with self.request_lock:
            if self.closed.is_set():
                raise AppError('CONNECTION_LOST', 'Not connected')
            ident, waiting = uuid.uuid4().hex, queue.Queue()
            with self.state_lock:
                self.pending[ident] = waiting
            try:
                send_message(self.sock, {'type': 'REQUEST', 'id': ident, 'op': op, 'params': params})
                try:
                    response = waiting.get(timeout=self.timeout)
                except queue.Empty as exc:
                    self.close()
                    raise AppError('TIMEOUT', 'Server response timed out; connection closed') from exc
                if response.get('type') == 'ERROR':
                    raise AppError(response['code'], response['message'])
                return response['data']
            finally:
                with self.state_lock:
                    self.pending.pop(ident, None)

    def keep_alive(self):
        interval = max(0.25, min(self.info['idle_timeout'], self.timeout) / 3)
        while not self.closed.wait(interval):
            try:
                self.request('STATUS' if self.user else 'CONNECT')
            except (OSError, AppError):
                self.close()
                break

    def register(self, name, password):
        return self.request('REGISTER', username=name, password=password)

    def login(self, name, password):
        result = self.request('LOGIN', username=name, password=password)
        self.user = result['username']
        return result

    def pages(self, op, **params):
        items, offset = [], 0
        while offset is not None:
            result = self.request(op, offset=offset, **params)
            items.extend(result['items'])
            offset = result['next_offset']
        return items

    def upload(self, local, remote, password=None, progress=None):
        with self.transfer_lock:
            started = False
            try:
                with Path(local).open('rb') as handle:
                    size = os.fstat(handle.fileno()).st_size
                    result = self.request('UPLOAD', path=remote, size=size, password=password)
                    started = True
                    ident, offset, digest = result['transfer_id'], 0, hashlib.sha256()
                    if progress:
                        progress('UPLOAD_START', 0, size)
                    while True:
                        chunk = handle.read(self.info['chunk_size'])
                        if not chunk:
                            break
                        result = self.request('UPLOAD_CHUNK', transfer_id=ident, offset=offset,
                                              data=base64.b64encode(chunk).decode('ascii'))
                        digest.update(chunk)
                        offset = result['bytes']
                        if progress:
                            progress('UPLOAD_PROGRESS', offset, size)
                    result = self.request('UPLOAD_FINISH', transfer_id=ident, sha256=digest.hexdigest())
                    started = False
                    if progress:
                        progress('UPLOAD_COMPLETE', offset, size)
                    return result
            finally:
                if started and not self.closed.is_set():
                    self.request('ABORT')

    def download(self, remote, local, progress=None):
        with self.transfer_lock:
            target = Path(local).expanduser().resolve()
            if target.exists():
                raise FileExistsError('Destination already exists; choose a new filename')
            target.parent.mkdir(parents=True, exist_ok=True)
            started, partial, published = False, None, False
            try:
                # Reserve the destination before contacting the server; no overwrite races.
                with target.open('xb'):
                    pass
                published = True
                with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent, prefix='.download-', delete=False) as handle:
                    partial = Path(handle.name)
                    result = self.request('DOWNLOAD', path=remote)
                    started = True
                    ident, resource = result['transfer_id'], result['resource']
                    size, offset, digest = resource['size'], 0, hashlib.sha256()
                    if progress:
                        progress('DOWNLOAD_START', 0, size)
                    while offset < size:
                        result = self.request('DOWNLOAD_CHUNK', transfer_id=ident, offset=offset)
                        chunk = base64.b64decode(result['data'], validate=True)
                        if not chunk or result['bytes'] != offset + len(chunk) or result['bytes'] > size:
                            raise AppError('INCOMPLETE_TRANSFER', 'Unexpected download chunk')
                        handle.write(chunk)
                        digest.update(chunk)
                        offset += len(chunk)
                        if progress:
                            progress('DOWNLOAD_PROGRESS', offset, size)
                    if digest.hexdigest() != resource['sha256']:
                        raise AppError('INCOMPLETE_TRANSFER', 'Download checksum mismatch')
                    self.request('DOWNLOAD_FINISH', transfer_id=ident, sha256=digest.hexdigest())
                    started = False
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(partial, target)
                partial, published = None, False
                if progress:
                    progress('DOWNLOAD_COMPLETE', offset, size)
                return {'path': str(target), 'bytes': size, 'sha256': digest.hexdigest()}
            finally:
                if partial:
                    partial.unlink(missing_ok=True)
                if published:
                    target.unlink(missing_ok=True)
                if started and not self.closed.is_set():
                    self.request('ABORT')

    def close(self):
        self.closed.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            # Idempotent cleanup: the reader may already have closed the socket.
            if self.sock.fileno() != -1:
                self.sock.close()
        self.sock.close()

    def disconnect(self):
        try:
            if not self.closed.is_set():
                self.request('DISCONNECT')
        finally:
            self.close()
            if threading.current_thread() is not self.reader:
                self.reader.join(timeout=2)
            if hasattr(self, 'heartbeat') and threading.current_thread() is not self.heartbeat:
                self.heartbeat.join(timeout=2)
