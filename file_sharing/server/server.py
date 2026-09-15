"""Socket listener, per-client handlers, dispatcher and asynchronous events."""
import argparse
import base64
import binascii
import hashlib
import os
import queue
import socket
import sqlite3
import threading
import uuid
from common.config import load_config, configure_logging
from common.protocol import AppError, recv_message, send_message
from server.security import username, password_hash, verify, physical
from server.storage import Storage

class Session:
    def __init__(self, server, sock, address):
        self.server, self.sock, self.address = server, sock, address
        self.user = None
        self.grants = {}
        self.transfer = None
        self.failures = 0
        self.out = queue.Queue(maxsize=256)
        self.closed = threading.Event()
        self.writer = threading.Thread(target=self.write_loop, daemon=True)
        self.thread = threading.Thread(target=self.run, daemon=True)

    def emit(self, message):
        if self.closed.is_set():
            return
        try:
            self.out.put_nowait(message)
        except queue.Full:
            self.server.log.warning('Slow client disconnected: %s', self.user or self.address)
            self.close()

    def write_loop(self):
        try:
            while not self.closed.is_set():
                message = self.out.get()
                if message is None:
                    break
                try:
                    send_message(self.sock, message)
                    if message.get('op') == 'DISCONNECT':
                        self.close()
                finally:
                    self.out.task_done()
        except (OSError, AppError):
            self.close()

    def close(self):
        self.closed.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            # Closing an already-disconnected socket is expected cleanup.
            self.server.log.debug('Socket already closed for %s', self.address)
        self.sock.close()
        try:
            self.out.put_nowait(None)
        except queue.Full:
            self.server.log.debug('Writer queue full at disconnect')

    def run(self):
        self.writer.start()
        self.server.log.info('Client connected: %s', self.address)
        try:
            while not self.closed.is_set():
                request = recv_message(self.sock)
                ident = request.get('id')
                op = request.get('op')
                if not isinstance(ident, str) or not 1 <= len(ident) <= 64:
                    raise AppError('PROTOCOL_ERROR', 'Request id must be a short string')
                try:
                    if request.get('type') != 'REQUEST' or not isinstance(op, str) or not isinstance(request.get('params', {}), dict):
                        raise AppError('INVALID_REQUEST', 'Expected REQUEST with op and params object')
                    with self.server.lock:
                        data = self.server.dispatch(self, op, request.get('params', {}))
                    self.emit({'type': 'RESPONSE', 'id': ident, 'op': op, 'data': data})
                except AppError as exc:
                    if exc.code == 'ACCESS_DENIED':
                        self.failures += 1
                    self.server.log.warning('Request rejected user=%s op=%r code=%s', self.user, op, exc.code)
                    self.emit({'type': 'ERROR', 'id': ident, 'code': exc.code, 'message': str(exc)})
                except (OSError, sqlite3.Error) as exc:
                    self.server.log.error('Storage failure user=%s op=%s class=%s', self.user, op, type(exc).__name__)
                    with self.server.lock:
                        self.server.abort(self)
                    self.emit({'type': 'ERROR', 'id': ident, 'code': 'STORAGE_ERROR', 'message': 'Storage operation failed; see server log'})
                except Exception:
                    self.server.log.exception('Unexpected handler failure op=%s', op)
                    self.emit({'type': 'ERROR', 'id': ident, 'code': 'SERVER_ERROR', 'message': 'Internal server error'})
        except AppError as exc:
            self.server.log.warning('Protocol error from %s: %s', self.address, exc.code)
            self.emit({'type': 'ERROR', 'id': None, 'code': exc.code, 'message': str(exc)})
            # Writer has a socket timeout, so flushing this error is bounded.
            self.writer.join(timeout=0.05)
        except (OSError, EOFError) as exc:
            self.server.log.info('Connection ended user=%s reason=%s', self.user, type(exc).__name__)
        finally:
            self.close()
            with self.server.lock:
                try:
                    self.server.abort(self)
                except (OSError, sqlite3.Error):
                    self.server.log.exception('Transfer cleanup failed; startup recovery will retry')
                self.server.sessions.discard(self)
            self.writer.join(timeout=2)
            self.server.log.info('Client disconnected: %s', self.user or self.address)

class Server:
    def __init__(self, config):
        self.config = config
        self.log = configure_logging(config)
        self.lock = threading.RLock()
        self.sessions = set()
        self.stopping = threading.Event()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.listener.bind((config['host'], config['port']))
            self.listener.listen(config['max_clients'])
            self.listener.settimeout(0.5)
            self.address = self.listener.getsockname()
            self.storage = Storage(config, self.log)
        except Exception:
            self.listener.close()
            raise

    def serve_forever(self):
        self.log.info('Server started on %s:%s; waiting for connections', *self.address)
        while not self.stopping.is_set():
            try:
                sock, address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.stopping.is_set():
                    break
                raise
            sock.settimeout(self.config['socket_timeout'])
            with self.lock:
                if self.stopping.is_set() or len(self.sessions) >= self.config['max_clients']:
                    sock.close()
                    continue
                session = Session(self, sock, address)
                self.sessions.add(session)
                session.thread.start()

    def stop(self):
        if self.stopping.is_set():
            return
        self.stopping.set()
        self.listener.close()
        with self.lock:
            sessions = list(self.sessions)
        for s in sessions:
            s.close()
        for s in sessions:
            s.thread.join(timeout=self.config['socket_timeout'] + 2)
        with self.lock:
            self.storage.db.close()
        self.log.info('Server shutdown complete')
        for handler in list(self.log.handlers):
            handler.close()
            self.log.removeHandler(handler)

    def notify(self, actor, event, resource, chain):
        message = {'type': 'NOTIFICATION', 'event': event, 'actor': actor.user,
                   'path': resource['path'], 'resource_id': resource['id']}
        # Snapshot chain also protects deletion notifications after metadata is removed.
        for other in list(self.sessions):
            if other is not actor and other.user and self.storage.allowed_chain(other, chain):
                other.emit(message)

    def abort(self, s):
        t = s.transfer
        if not t:
            return
        s.transfer = None
        t['handle'].close()
        path = t['path']
        self.storage.busy[path] = max(0, self.storage.busy.get(path, 0) - 1)
        if not self.storage.busy[path]:
            del self.storage.busy[path]
        if t['mode'] == 'upload':
            (self.storage.temp / t['id']).unlink(missing_ok=True)
            # Only an unpublished staging resource is removed, never a completed file.
            row = self.storage.db.execute('SELECT state FROM resources WHERE id=?', (t['id'],)).fetchone()
            if row and row['state'] == 'staging':
                physical(self.storage.root, path).unlink(missing_ok=True)
                with self.storage.db:
                    self.storage.db.execute('DELETE FROM resources WHERE id=?', (t['id'],))
        self.log.info('Transfer closed user=%s mode=%s bytes=%s', s.user, t['mode'], t['offset'])

    def active(self, s, p, mode):
        t = s.transfer
        if not t or t['mode'] != mode or p.get('transfer_id') != t['id']:
            raise AppError('INVALID_TRANSFER', 'No matching active transfer')
        return t

    def dispatch(self, s, op, p):
        db, st = self.storage.db, self.storage
        if s.failures >= 10 and op not in ('DISCONNECT', 'STATUS'):
            raise AppError('RATE_LIMITED', 'Too many denied requests; reconnect')
        if op == 'CONNECT':
            return {'protocol': 1, 'chunk_size': self.config['chunk_size'],
                    'max_file_size': self.config['max_file_size'], 'idle_timeout': self.config['socket_timeout']}
        if op == 'DISCONNECT':
            return {'message': 'Goodbye'}
        if op in ('REGISTER', 'LOGIN'):
            if s.user:
                raise AppError('ALREADY_LOGGED_IN', 'Disconnect before switching accounts')
            name = username(p.get('username'))
            if op == 'REGISTER':
                hashed = password_hash(p.get('password'))
                try:
                    with db:
                        db.execute('INSERT INTO users VALUES (?,?)', (name, hashed))
                except sqlite3.IntegrityError as exc:
                    raise AppError('DUPLICATE_USER', 'Username already registered') from exc
                self.log.info('Registered user=%s', name)
                return {'message': 'Registered; now log in'}
            row = db.execute('SELECT * FROM users WHERE username=?', (name,)).fetchone()
            if not row or not verify(p.get('password'), row['password_hash']):
                raise AppError('ACCESS_DENIED', 'Invalid username or password')
            if any(x.user and x.user.lower() == name.lower() for x in self.sessions):
                raise AppError('USER_ONLINE', 'Username already has an active session')
            s.user = row['username']
            self.log.info('Login user=%s', s.user)
            return {'username': s.user}
        if not s.user:
            raise AppError('AUTH_REQUIRED', 'Log in first')
        if op == 'STATUS':
            t = s.transfer
            return {'users': sorted(x.user for x in self.sessions if x.user),
                    'transfer': {'mode': t['mode'], 'bytes': t['offset'], 'total': t['size']} if t else None}
        if op in ('LIST', 'SEARCH'):
            offset = p.get('offset', 0)
            if type(offset) is not int or offset < 0:
                raise AppError('INVALID_INPUT', 'Offset must be a nonnegative integer')
            return st.listing(s, p.get('path', ''), offset) if op == 'LIST' else st.search(s, p, offset)
        if op == 'CREATE_FOLDER':
            if type(p.get('parents', False)) is not bool:
                raise AppError('INVALID_INPUT', 'parents must be boolean')
            result = st.mkdir(s, p.get('path'), p.get('parents', False))
            self.log.info('Folder created user=%s path=%s', s.user, result['path'])
            return result
        if op in ('ACCESS', 'PROTECT'):
            result = st.access(s, p.get('path'), p.get('password')) if op == 'ACCESS' else st.protect(s, p.get('path'), p.get('password'))
            self.log.info('%s user=%s', op, s.user)
            return result
        if op in ('DELETE_FILE', 'DELETE_FOLDER'):
            result, chain = st.delete(s, p.get('path'), 'file' if op == 'DELETE_FILE' else 'folder')
            self.notify(s, 'FILE_DELETED' if op == 'DELETE_FILE' else 'FOLDER_DELETED', result, chain)
            self.log.info('%s user=%s path=%s', op, s.user, result['path'])
            return result
        if op == 'ABORT':
            self.abort(s)
            return {'status': 'ABORTED'}
        if op == 'UPLOAD':
            if s.transfer:
                raise AppError('TRANSFER_BUSY', 'Finish or abort the current transfer')
            path = st.canonical_new(p.get('path'))
            st.check(s, path, False)
            st.free_name(path)
            size = p.get('size')
            if type(size) is not int or not 0 <= size <= self.config['max_file_size']:
                raise AppError('INVALID_INPUT', 'Invalid file size or file too large')
            hashed = password_hash(p['password']) if p.get('password') is not None else None
            ident = st.insert(path, 'file', s.user, size, hashed)
            try:
                handle = (st.temp / ident).open('xb')
            except OSError:
                with db:
                    db.execute('DELETE FROM resources WHERE id=?', (ident,))
                raise
            s.transfer = dict(id=ident, mode='upload', path=path, size=size,
                              offset=0, handle=handle, digest=hashlib.sha256())
            st.busy[path] = 1
            if hashed:
                s.grants[ident] = hashed
            self.log.info('UPLOAD_START user=%s path=%s size=%s', s.user, path, size)
            return {'transfer_id': ident, 'status': 'UPLOAD_START', 'bytes': 0, 'total': size}
        if op == 'UPLOAD_CHUNK':
            t = self.active(s, p, 'upload')
            if type(p.get('offset')) is not int or p['offset'] != t['offset']:
                raise AppError('INVALID_OFFSET', 'Unexpected chunk offset')
            encoded = p.get('data')
            if not isinstance(encoded, str) or len(encoded) > 4 * ((self.config['chunk_size'] + 2) // 3):
                raise AppError('INVALID_CHUNK', 'Chunk exceeds limit')
            try:
                chunk = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise AppError('INVALID_CHUNK', 'Invalid base64 chunk') from exc
            if not chunk or len(chunk) > self.config['chunk_size'] or t['offset'] + len(chunk) > t['size']:
                raise AppError('INVALID_CHUNK', 'Chunk size does not match declared transfer')
            written = t['handle'].write(chunk)
            if written != len(chunk):
                raise OSError('Short storage write')
            t['digest'].update(chunk)
            t['offset'] += written
            return {'status': 'UPLOAD_PROGRESS', 'bytes': t['offset'], 'total': t['size']}
        if op == 'UPLOAD_FINISH':
            t = self.active(s, p, 'upload')
            if t['offset'] != t['size'] or p.get('sha256') != t['digest'].hexdigest():
                self.abort(s)
                raise AppError('INCOMPLETE_TRANSFER', 'Size or checksum mismatch; upload discarded')
            t['handle'].flush()
            os.fsync(t['handle'].fileno())
            t['handle'].close()
            os.replace(st.temp / t['id'], physical(st.root, t['path']))
            with db:
                db.execute("UPDATE resources SET state='ready', sha256=? WHERE id=?", (t['digest'].hexdigest(), t['id']))
            result = st.public(st.get(t['path']))
            self.abort(s)
            self.notify(s, 'FILE_UPLOADED', result, st.chain(result['path']))
            self.log.info('UPLOAD_COMPLETE user=%s path=%s', s.user, result['path'])
            return {'status': 'UPLOAD_COMPLETE', 'resource': result}
        if op == 'DOWNLOAD':
            if s.transfer:
                raise AppError('TRANSFER_BUSY', 'Finish or abort the current transfer')
            row = st.get(p.get('path'), 'file')
            st.check(s, row['path'])
            handle = physical(st.root, row['path']).open('rb')
            if os.fstat(handle.fileno()).st_size != row['size']:
                handle.close()
                raise AppError('STORAGE_ERROR', 'Stored file size differs from metadata')
            ident = uuid.uuid4().hex
            s.transfer = dict(id=ident, mode='download', path=row['path'], size=row['size'],
                              offset=0, handle=handle, digest=hashlib.sha256(), sha256=row['sha256'])
            st.busy[row['path']] = st.busy.get(row['path'], 0) + 1
            self.log.info('DOWNLOAD_START user=%s path=%s', s.user, row['path'])
            return {'transfer_id': ident, 'status': 'DOWNLOAD_START', 'resource': st.public(row)}
        if op == 'DOWNLOAD_CHUNK':
            t = self.active(s, p, 'download')
            st.check(s, t['path'])
            if type(p.get('offset')) is not int or p['offset'] != t['offset']:
                raise AppError('INVALID_OFFSET', 'Unexpected chunk offset')
            chunk = t['handle'].read(min(self.config['chunk_size'], t['size'] - t['offset']))
            if not chunk and t['offset'] < t['size']:
                self.abort(s)
                raise AppError('INCOMPLETE_TRANSFER', 'Stored file ended unexpectedly')
            t['digest'].update(chunk)
            t['offset'] += len(chunk)
            return {'status': 'DOWNLOAD_PROGRESS', 'data': base64.b64encode(chunk).decode('ascii'),
                    'bytes': t['offset'], 'total': t['size']}
        if op == 'DOWNLOAD_FINISH':
            t = self.active(s, p, 'download')
            good = t['offset'] == t['size'] and p.get('sha256') == t['digest'].hexdigest() == t['sha256']
            self.abort(s)
            if not good:
                raise AppError('INCOMPLETE_TRANSFER', 'Download size/checksum verification failed')
            self.log.info('DOWNLOAD_COMPLETE user=%s', s.user)
            return {'status': 'DOWNLOAD_COMPLETE'}
        raise AppError('UNKNOWN_COMMAND', 'Unknown operation')

def main():
    parser = argparse.ArgumentParser(description='Network file-sharing TCP server')
    parser.add_argument('--config')
    args = parser.parse_args()
    server = None
    try:
        server = Server(load_config(args.config))
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopping server...')
    except (OSError, ValueError, sqlite3.Error) as exc:
        print('Server startup/runtime error:', exc)
        raise SystemExit(1)
    finally:
        if server:
            server.stop()

if __name__ == '__main__':
    main()
