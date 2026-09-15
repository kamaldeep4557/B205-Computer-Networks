import base64
import concurrent.futures
import hashlib
import json
import logging
import queue
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from client.client import Client
from common.config import load_config
from common.protocol import AppError, MAX_FRAME, recv_message
from server.server import Server
PASSWORD = 'TestPassword!2026'
SECRET = 'ResourceSecret!2026'

def wait_until(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError('Condition did not become true')

def config(root):
    p = root / 'config.json'
    p.write_text(json.dumps({'port': 0, 'socket_timeout': 8, 'chunk_size': 4096}))
    return load_config(p)

def start(cfg):
    s = Server(cfg)
    for h in list(s.log.handlers):
        if type(h) is logging.StreamHandler:
            s.log.removeHandler(h)
            h.close()
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    return s, t

class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.cfg = config(cls.root)
        cls.server, cls.thread = start(cls.cfg)
        for name in ('Alice', 'Bob', 'Charlie'):
            c = Client(*cls.server.address, timeout=8)
            c.register(name, PASSWORD)
            c.disconnect()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.thread.join(2)
        cls.temp.cleanup()

    def setUp(self):
        wait_until(lambda: not any(s.user for s in self.server.sessions))
        self.clients = []
        for name in ('Alice', 'Bob', 'Charlie'):
            c = Client(*self.server.address, timeout=8)
            c.login(name, PASSWORD)
            self.clients.append(c)
        self.a, self.b, self.c = self.clients
        self.p = self._testMethodName
        self.local = self.root / (self.p + '.bin')
        self.data = bytes(range(256)) * 79 + b'last partial chunk'
        self.local.write_bytes(self.data)

    def tearDown(self):
        for c in self.clients:
            c.disconnect()

    def error(self, code, fn, *args, **kwargs):
        with self.assertRaises(AppError) as cm:
            fn(*args, **kwargs)
        self.assertEqual(cm.exception.code, code)

    def upload(self, path=None, **kw):
        return self.a.upload(self.local, path or self.p + '.bin', **kw)

    def mkdir(self, path=None):
        return self.a.request('CREATE_FOLDER', path=path or self.p, parents=True)

    def test_01_server_connection_three_users(self):
        self.assertEqual(self.a.info['protocol'], 1)
        self.assertEqual(self.a.request('STATUS')['users'], ['Alice', 'Bob', 'Charlie'])

    def test_02_unique_users_and_sessions(self):
        d = Client(*self.server.address, timeout=8)
        try:
            self.error('DUPLICATE_USER', d.register, 'alice', PASSWORD)
            self.error('USER_ONLINE', d.login, 'ALICE', PASSWORD)
        finally:
            d.disconnect()

    def test_03_upload_metadata(self):
        r = self.upload()['resource']
        self.assertEqual(r['size'], len(self.data))
        self.assertEqual(r['uploader'], 'Alice')
        self.assertEqual(r['type'], 'application/octet-stream')
        self.assertIn('+00:00', r['creation_time'])
        self.assertEqual(r['sha256'], hashlib.sha256(self.data).hexdigest())
        self.assertNotIn('password_hash', r)
        self.assertEqual((Path(self.cfg['storage_dir']) / r['path']).read_bytes(), self.data)

    def test_04_download_integrity(self):
        self.upload()
        dest = self.root / (self.p + '-out')
        self.b.download(self.p + '.bin', dest)
        self.assertEqual(dest.read_bytes(), self.data)

    def test_05_search_metadata_filters(self):
        self.mkdir(self.p + '/Nested')
        self.upload(self.p + '/Nested/report.txt')
        result = self.c.pages('SEARCH', query='report', type='text/plain', uploader='Alice', folder=self.p, created='T')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['path'], self.p + '/Nested/report.txt')
        self.assertEqual(self.c.pages('SEARCH', query='report', uploader='Nobody'), [])

    def test_06_delete_storage_and_metadata(self):
        self.upload()
        self.b.request('DELETE_FILE', path=self.p + '.bin')
        self.assertFalse((Path(self.cfg['storage_dir']) / (self.p + '.bin')).exists())
        self.assertEqual(self.c.pages('SEARCH', query=self.p), [])

    def test_07_nested_folders(self):
        p = self.p + '/Documents/University/Networks'
        self.mkdir(p)
        self.assertEqual(self.b.request('LIST', path=p)['path'], p)
        self.assertTrue((Path(self.cfg['storage_dir']) / p).is_dir())

    def test_08_duplicate_file_folder_names(self):
        self.upload()
        self.error('DUPLICATE_NAME', self.upload)
        self.mkdir()
        self.error('DUPLICATE_NAME', self.mkdir)
        self.error('DUPLICATE_NAME', self.a.request, 'CREATE_FOLDER', path=self.p + '.bin')

    def test_09_same_filename_different_folders(self):
        self.mkdir(self.p + '/A')
        self.mkdir(self.p + '/B')
        x = self.upload(self.p + '/A/report.txt')['resource']
        y = self.upload(self.p + '/B/report.txt')['resource']
        self.assertNotEqual(x['id'], y['id'])

    def test_10_protected_file_passwords(self):
        p = self.p + '.bin'
        self.upload(p, password=SECRET)
        self.error('ACCESS_DENIED', self.b.request, 'DOWNLOAD', path=p)
        self.error('ACCESS_DENIED', self.b.request, 'ACCESS', path=p, password='WrongPassword')
        self.b.request('ACCESS', path=p, password=SECRET)
        self.b.download(p, self.root / (self.p + '-out'))

    def test_11_recursive_folder_acl(self):
        self.mkdir(self.p + '/Child/Deep')
        p = self.p + '/Child/Deep/secret.bin'
        self.upload(p)
        self.a.request('PROTECT', path=self.p, password=SECRET)
        self.error('ACCESS_DENIED', self.b.request, 'LIST', path=self.p + '/Child')
        self.error('ACCESS_DENIED', self.b.request, 'DOWNLOAD', path=p)
        self.error('ACCESS_DENIED', self.b.request, 'CREATE_FOLDER', path=self.p + '/New')
        self.error('ACCESS_DENIED', self.b.request, 'UPLOAD', path=self.p + '/new.bin', size=1)
        self.error('ACCESS_DENIED', self.b.request, 'DELETE_FILE', path=p)
        self.assertEqual(self.b.pages('SEARCH', query='secret', folder=self.p), [])
        self.b.request('ACCESS', path=self.p, password=SECRET)
        self.assertEqual(len(self.b.pages('SEARCH', query='secret', folder=self.p)), 1)

    def test_12_owner_protection_and_revocation(self):
        p = self.p + '.bin'
        self.upload(p)
        self.error('ACCESS_DENIED', self.b.request, 'PROTECT', path=p, password=SECRET)
        self.a.request('PROTECT', path=p, password=SECRET)
        self.b.request('ACCESS', path=p, password=SECRET)
        self.a.request('PROTECT', path=p, password='ChangedSecret!')
        self.error('ACCESS_DENIED', self.b.request, 'DOWNLOAD', path=p)
        self.a.request('PROTECT', path=p, password=None)
        self.b.download(p, self.root / (self.p + '-out'))

    def test_13_upload_notifications(self):
        self.upload()
        for c in (self.b, self.c):
            event = c.events.get(timeout=2)
            self.assertEqual(event['event'], 'FILE_UPLOADED')
            self.assertEqual(event['actor'], 'Alice')
            self.assertEqual(event['path'], self.p + '.bin')

    def test_14_deletion_notifications(self):
        self.upload()
        self.b.events.get(timeout=2)
        self.c.events.get(timeout=2)
        self.b.request('DELETE_FILE', path=self.p + '.bin')
        self.assertEqual(self.a.events.get(timeout=2)['event'], 'FILE_DELETED')
        self.assertEqual(self.c.events.get(timeout=2)['actor'], 'Bob')

    def test_15_actual_byte_progress(self):
        up, down = [], []
        self.upload(progress=lambda *x: up.append(x))
        self.b.download(self.p + '.bin', self.root / (self.p + '-out'), progress=lambda *x: down.append(x))
        for events, mode in ((up, 'UPLOAD'), (down, 'DOWNLOAD')):
            self.assertEqual(events[0], (mode + '_START', 0, len(self.data)))
            self.assertEqual(events[-1], (mode + '_COMPLETE', len(self.data), len(self.data)))
            positions = [x[1] for x in events if x[0].endswith('PROGRESS')]
            self.assertEqual(positions, list(range(4096, len(self.data), 4096)) + [len(self.data)])

    def test_16_invalid_input_command(self):
        self.error('UNKNOWN_COMMAND', self.b.request, 'NOT_A_COMMAND')
        self.error('INVALID_INPUT', self.b.request, 'UPLOAD', path=self.p, size=-1)
        self.error('INVALID_INPUT', self.b.request, 'LIST', offset=True)
        self.error('INVALID_INPUT', self.b.request, 'SEARCH', query=['bad'])
        self.error('INVALID_PATH', self.b.request, 'DOWNLOAD', path=['bad'])
        self.assertIn('users', self.b.request('STATUS'))

    def test_17_missing_file_folder(self):
        for op, p in (('DOWNLOAD', 'absent.bin'), ('DELETE_FILE', 'absent.bin'), ('LIST', 'absent-folder')):
            self.error('NOT_FOUND', self.b.request, op, path=p)
        self.error('NOT_FOUND', self.b.request, 'UPLOAD', path='absent-folder/file', size=1)

    def test_18_disconnect_and_relogin(self):
        self.b.disconnect()
        wait_until(lambda: 'Bob' not in self.a.request('STATUS')['users'])
        b = Client(*self.server.address, timeout=8)
        self.clients.append(b)
        self.assertEqual(b.login('Bob', PASSWORD)['username'], 'Bob')

    def test_19_simultaneous_duplicate_upload(self):
        def upload(c):
            try:
                c.upload(self.local, self.p + '.bin')
                return 'OK'
            except AppError as exc:
                return exc.code
        with concurrent.futures.ThreadPoolExecutor(3) as pool:
            result = list(pool.map(upload, self.clients))
        self.assertEqual(sorted(result), ['DUPLICATE_NAME', 'DUPLICATE_NAME', 'OK'])

    def test_20_simultaneous_folder_creation(self):
        def create(c):
            try:
                c.request('CREATE_FOLDER', path=self.p)
                return 'OK'
            except AppError as exc:
                return exc.code
        with concurrent.futures.ThreadPoolExecutor(3) as pool:
            result = list(pool.map(create, self.clients))
        self.assertEqual(result.count('OK'), 1)
        self.assertEqual(result.count('DUPLICATE_NAME'), 2)

    def test_21_interrupted_upload_cleanup(self):
        p = self.p + '.bin'
        t = self.a.request('UPLOAD', path=p, size=9000)
        self.a.request('UPLOAD_CHUNK', transfer_id=t['transfer_id'], offset=0, data=base64.b64encode(b'x'*4096).decode())
        self.a.close()
        def cleaned():
            with self.server.lock:
                return not self.server.storage.db.execute('SELECT 1 FROM resources WHERE path=?', (p,)).fetchone()
        wait_until(cleaned)
        self.assertFalse((Path(self.cfg['storage_dir']) / p).exists())
        self.assertFalse((self.server.storage.temp / t['transfer_id']).exists())

    def test_22_interrupted_download_cleanup(self):
        self.upload()
        dest = self.root / (self.p + '-out')
        def interrupt(status, done, total):
            if done:
                self.b.close()
        self.error('CONNECTION_LOST', self.b.download, self.p + '.bin', dest, progress=interrupt)
        self.assertFalse(dest.exists())
        self.assertEqual(list(self.root.glob('.download-*')), [])

    def test_23_path_traversal(self):
        for p in ('../escape', '/etc/passwd', 'A/../../escape', 'C:\\Windows', 'A//B', 'CON', '.hidden', 'bad\nname'):
            self.error('INVALID_PATH', self.b.request, 'CREATE_FOLDER', path=p, parents=True)
        self.assertFalse((self.root.parent / 'escape').exists())

    def test_24_logging_no_password_leaks(self):
        self.upload()
        self.error('ACCESS_DENIED', self.b.request, 'PROTECT', path=self.p + '.bin', password=SECRET)
        text = Path(self.cfg['log_file']).read_text()
        for phrase in ('Server started', 'Client connected', 'UPLOAD_START', 'UPLOAD_COMPLETE', 'ACCESS_DENIED'):
            self.assertIn(phrase, text)
        self.assertNotIn(PASSWORD, text)
        self.assertNotIn(SECRET, text)

    def test_25_configuration(self):
        self.assertEqual(self.a.info['chunk_size'], 4096)
        self.assertTrue(Path(self.cfg['database']).is_absolute())
        bad = self.root / 'bad.json'
        bad.write_text('{"chunk_size": -1}')
        with self.assertRaises(ValueError):
            load_config(bad)

    def test_26_empty_nonempty_protected_folder_deletion(self):
        self.mkdir(self.p + '/Child')
        self.error('NOT_EMPTY', self.b.request, 'DELETE_FOLDER', path=self.p)
        self.a.request('PROTECT', path=self.p + '/Child', password=SECRET)
        self.error('ACCESS_DENIED', self.b.request, 'DELETE_FOLDER', path=self.p + '/Child')
        self.b.request('ACCESS', path=self.p + '/Child', password=SECRET)
        self.b.request('DELETE_FOLDER', path=self.p + '/Child')
        self.b.request('DELETE_FOLDER', path=self.p)
        self.error('NOT_FOUND', self.c.request, 'LIST', path=self.p)

    def test_27_authentication_and_hashes(self):
        d = Client(*self.server.address, timeout=8)
        try:
            self.error('AUTH_REQUIRED', d.request, 'LIST')
            self.error('ACCESS_DENIED', d.login, 'Alice', 'BadPassword')
            self.error('INVALID_INPUT', d.register, 'bad name', PASSWORD)
        finally:
            d.disconnect()
        with self.server.lock:
            hashes = [r[0] for r in self.server.storage.db.execute('SELECT password_hash FROM users')]
        self.assertEqual(len(set(hashes)), 3)
        self.assertTrue(all(x.startswith('600000$') and PASSWORD not in x for x in hashes))

    def test_28_checksum_failure(self):
        t = self.a.request('UPLOAD', path=self.p + '.bin', size=1)
        self.a.request('UPLOAD_CHUNK', transfer_id=t['transfer_id'], offset=0, data='eA==')
        self.error('INCOMPLETE_TRANSFER', self.a.request, 'UPLOAD_FINISH', transfer_id=t['transfer_id'], sha256='incorrect')
        self.assertEqual(self.b.pages('SEARCH', query=self.p), [])
        self.upload()

    def test_29_empty_file_transfer(self):
        self.local.write_bytes(b'')
        self.upload()
        dest = self.root / (self.p + '-out')
        self.b.download(self.p + '.bin', dest)
        self.assertEqual(dest.read_bytes(), b'')

    def test_30_private_notifications(self):
        self.mkdir()
        self.a.request('PROTECT', path=self.p, password=SECRET)
        self.upload(self.p + '/hidden.bin')
        with self.assertRaises(queue.Empty):
            self.b.events.get(timeout=0.2)
        self.a.request('DELETE_FILE', path=self.p + '/hidden.bin')
        with self.assertRaises(queue.Empty):
            self.c.events.get(timeout=0.2)

    def test_31_active_transfer_locks(self):
        self.mkdir()
        p = self.p + '/file.bin'
        self.upload(p)
        self.b.request('DOWNLOAD', path=p)
        self.error('RESOURCE_BUSY', self.c.request, 'DELETE_FILE', path=p)
        self.error('RESOURCE_BUSY', self.a.request, 'PROTECT', path=self.p, password=SECRET)
        self.b.request('ABORT')
        self.c.request('DELETE_FILE', path=p)

    def test_32_malformed_frame_isolation(self):
        for payload in (struct.pack('!I', MAX_FRAME + 1), struct.pack('!I', 1) + b'{'):
            raw = socket.create_connection(self.server.address, timeout=2)
            raw.sendall(payload)
            try:
                self.assertEqual(recv_message(raw)['code'], 'PROTOCOL_ERROR')
            finally:
                raw.close()
        self.assertEqual(len(self.a.request('STATUS')['users']), 3)

    def test_33_local_no_overwrite(self):
        self.upload()
        with self.assertRaises(FileExistsError):
            self.b.download(self.p + '.bin', self.local)
        self.assertEqual(self.local.read_bytes(), self.data)

    def test_34_realistic_three_user_flow(self):
        self.mkdir(self.p + '/Documents')
        self.upload(self.p + '/Documents/report.txt')
        self.assertEqual(self.b.events.get(timeout=2)['actor'], 'Alice')
        self.c.events.get(timeout=2)
        self.assertEqual(len(self.c.pages('SEARCH', query='report', folder=self.p)), 1)
        self.b.request('CREATE_FOLDER', path=self.p + '/Projects')
        self.upload(self.p + '/Projects/project.zip')
        self.b.events.get(timeout=2)
        self.c.events.get(timeout=2)
        self.c.download(self.p + '/Projects/project.zip', self.root / (self.p + '-out.zip'))
        self.b.request('DELETE_FILE', path=self.p + '/Documents/report.txt')
        self.assertEqual(self.a.events.get(timeout=2)['event'], 'FILE_DELETED')
        self.assertEqual(self.c.events.get(timeout=2)['event'], 'FILE_DELETED')

    def test_35_layered_passwords(self):
        self.mkdir(self.p + '/Inner')
        self.upload(self.p + '/Inner/file.bin', password=SECRET)
        self.a.request('PROTECT', path=self.p, password=SECRET)
        self.a.request('PROTECT', path=self.p + '/Inner', password='SecondPassword!')
        self.error('ACCESS_DENIED', self.b.request, 'ACCESS', path=self.p + '/Inner', password='SecondPassword!')
        self.b.request('ACCESS', path=self.p, password=SECRET)
        self.b.request('ACCESS', path=self.p + '/Inner', password='SecondPassword!')
        self.error('ACCESS_DENIED', self.b.request, 'DOWNLOAD', path=self.p + '/Inner/file.bin')
        self.b.request('ACCESS', path=self.p + '/Inner/file.bin', password=SECRET)
        self.b.download(self.p + '/Inner/file.bin', self.root / (self.p + '-out'))

    def test_36_invalid_chunks(self):
        t = self.a.request('UPLOAD', path=self.p + '.bin', size=5)
        ident = t['transfer_id']
        self.error('INVALID_OFFSET', self.a.request, 'UPLOAD_CHUNK', transfer_id=ident, offset=1, data='eA==')
        self.error('INVALID_CHUNK', self.a.request, 'UPLOAD_CHUNK', transfer_id=ident, offset=0, data='%%%')
        self.error('INVALID_CHUNK', self.a.request, 'UPLOAD_CHUNK', transfer_id=ident, offset=0, data=base64.b64encode(b'too long').decode())
        self.a.request('ABORT')
        self.assertIsNone(self.a.request('STATUS')['transfer'])

    def test_41_storage_error_cleanup(self):
        from unittest.mock import Mock
        p = self.p + '.bin'
        result = self.a.request('UPLOAD', path=p, size=5)
        with self.server.lock:
            session = next(x for x in self.server.sessions if x.user == 'Alice')
            real_handle = session.transfer['handle']
            broken_handle = Mock(wraps=real_handle)
            broken_handle.write.side_effect = OSError('Injected disk-full failure')
            session.transfer['handle'] = broken_handle
        self.error('STORAGE_ERROR', self.a.request, 'UPLOAD_CHUNK',
                   transfer_id=result['transfer_id'], offset=0, data='aGVsbG8=')
        self.assertTrue(real_handle.closed)
        self.assertIsNone(self.a.request('STATUS')['transfer'])
        self.assertEqual(self.b.pages('SEARCH', query=self.p), [])
        self.upload()

    def test_42_symlink_escape_rejected(self):
        link = Path(self.cfg['storage_dir']) / (self.p + '-link')
        try:
            link.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest('OS does not permit creation of test symlinks')
        try:
            self.error('INVALID_PATH', self.b.request, 'CREATE_FOLDER',
                       path=link.name + '/outside', parents=True)
        finally:
            link.unlink()

    def test_43_missing_local_upload_file(self):
        with self.assertRaises(FileNotFoundError):
            self.a.upload(self.root / 'does-not-exist', self.p + '.bin')
        self.assertIsNone(self.a.request('STATUS')['transfer'])

class FramingPersistenceTests(unittest.TestCase):
    def test_37_fragmented_coalesced_frames(self):
        a, b = socket.socketpair()
        messages = [{'type': 'REQUEST', 'id': str(i), 'op': 'STATUS', 'params': {}} for i in range(3)]
        data = b''
        for m in messages:
            payload = json.dumps(m).encode()
            data += struct.pack('!I', len(payload)) + payload
        def sender():
            try:
                for i in range(0, len(data), 3):
                    a.sendall(data[i:i+3])
            finally:
                a.close()
        t = threading.Thread(target=sender)
        t.start()
        try:
            self.assertEqual([recv_message(b) for _ in messages], messages)
        finally:
            b.close()
            t.join()

    def test_38_persistent_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = config(root)
            s, t = start(cfg)
            c = Client(*s.address, timeout=8)
            c.register('PersistentUser', PASSWORD)
            c.login('PersistentUser', PASSWORD)
            local = root / 'local.txt'
            local.write_text('Persistent data')
            original = c.upload(local, 'saved.txt')['resource']
            c.disconnect()
            s.stop()
            t.join(2)
            s, t = start(cfg)
            c = Client(*s.address, timeout=8)
            try:
                c.login('PersistentUser', PASSWORD)
                self.assertEqual(c.pages('SEARCH', query='saved')[0]['id'], original['id'])
                c.download('saved.txt', root / 'download.txt')
                self.assertEqual((root / 'download.txt').read_text(), 'Persistent data')
            finally:
                c.disconnect()
                s.stop()
                t.join(2)

    def test_39_recover_interrupted_intents(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg = config(Path(temp))
            s, t = start(cfg)
            with s.lock:
                st = s.storage
                ident = st.insert('unfinished.bin', 'file', 'Alice', 6)
                (st.root / 'unfinished.bin').write_bytes(b'broken')
                (st.temp / ident).write_bytes(b'partial')
                deleted = st.insert('deleting.bin', 'file', 'Alice', 3)
                (st.root / 'deleting.bin').write_bytes(b'old')
                with st.db:
                    st.db.execute("UPDATE resources SET state='deleting' WHERE id=?", (deleted,))
            s.stop()
            t.join(2)
            s, t = start(cfg)
            try:
                with s.lock:
                    self.assertEqual(s.storage.db.execute('SELECT count(*) FROM resources').fetchone()[0], 0)
                self.assertEqual(list(s.storage.root.iterdir()), [])
                self.assertEqual(list(s.storage.temp.iterdir()), [])
            finally:
                s.stop()
                t.join(2)

    def test_40_connection_failure(self):
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        try:
            with self.assertRaises(OSError):
                Client(*sock.getsockname(), timeout=1)
        finally:
            sock.close()

if __name__ == '__main__':
    unittest.main(verbosity=2)
