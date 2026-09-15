"""Persistent resources, recursive ACLs and recoverable filesystem mutations.

All methods are called with Server.lock held. Locks never span socket I/O.
SQLite records staging/deleting intent before filesystem changes. Startup finishes
interrupted deletions and removes unpublished uploads/unfinished folder creations.
"""
import mimetypes
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from common.protocol import AppError
from server.security import clean_path, physical, password_hash, verify

class Storage:
    def __init__(self, config, logger):
        self.config, self.logger = config, logger
        self.root = Path(config['storage_dir'])
        self.root.mkdir(parents=True, exist_ok=True)
        dbpath = Path(config['database'])
        dbpath.parent.mkdir(parents=True, exist_ok=True)
        self.temp = dbpath.parent / 'partial_uploads'
        self.temp.mkdir(exist_ok=True)
        self.db = sqlite3.connect(dbpath, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY COLLATE NOCASE, password_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS resources (
                id TEXT PRIMARY KEY, path TEXT UNIQUE COLLATE NOCASE NOT NULL,
                parent TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
                size INTEGER NOT NULL DEFAULT 0, type TEXT NOT NULL,
                creation_time TEXT NOT NULL, uploader TEXT NOT NULL,
                password_hash TEXT, sha256 TEXT, state TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS resource_parent ON resources(parent);
        ''')
        self.busy = {}  # Read leases and upload reservations; mutation cannot invalidate them.
        self.recover()

    def recover(self):
        for row in self.db.execute("SELECT * FROM resources WHERE state != 'ready' ORDER BY length(path) DESC").fetchall():
            p = physical(self.root, row['path'])
            if p.exists():
                if row['kind'] == 'folder':
                    p.rmdir()
                else:
                    p.unlink()
            (self.temp / row['id']).unlink(missing_ok=True)
            with self.db:
                self.db.execute('DELETE FROM resources WHERE id=?', (row['id'],))
            self.logger.warning('Recovered interrupted resource operation id=%s', row['id'])
        for p in self.temp.iterdir():
            if p.is_file() and not p.is_symlink():
                p.unlink()

    def get(self, path, kind=None):
        clean_path(path)
        row = self.db.execute("SELECT * FROM resources WHERE path=? AND state='ready'", (path,)).fetchone()
        if not row:
            raise AppError('NOT_FOUND', 'File or folder does not exist')
        row = dict(row)
        # Always use stored spelling for physical access on case-sensitive systems.
        if kind and row['kind'] != kind:
            raise AppError('WRONG_TYPE', 'Expected a ' + kind)
        return row

    def folder(self, path):
        return self.get(path, 'folder')['path'] if path else ''

    def chain(self, path, include=True):
        parts = path.split('/') if path else []
        if not include:
            parts = parts[:-1]
        return [self.get('/'.join(parts[:i])) for i in range(1, len(parts) + 1)]

    def allowed_chain(self, session, chain):
        return all(not r['password_hash'] or session.grants.get(r['id']) == r['password_hash'] for r in chain)

    def check(self, session, path, include=True):
        if not self.allowed_chain(session, self.chain(path, include)):
            raise AppError('ACCESS_DENIED', 'Protected resource: use access on locked ancestors first')

    def public(self, row):
        return {k: v for k, v in row.items() if k not in ('password_hash', 'state')} | {'protected': bool(row['password_hash'])}

    def free_name(self, path):
        if self.db.execute('SELECT 1 FROM resources WHERE path=?', (path,)).fetchone() or physical(self.root, path).exists():
            raise AppError('DUPLICATE_NAME', 'Name already exists or an upload has reserved it')
        if self.db.execute('SELECT count(*) FROM resources').fetchone()[0] >= self.config['max_resources']:
            raise AppError('LIMIT_EXCEEDED', 'Resource limit reached')

    def insert(self, path, kind, user, size=0, hashed=None):
        identifier = uuid.uuid4().hex
        parent, _, name = path.rpartition('/')
        mime = 'inode/directory' if kind == 'folder' else (mimetypes.guess_type(name)[0] or 'application/octet-stream')
        with self.db:
            self.db.execute('INSERT INTO resources VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                            (identifier, path, parent, name, kind, size, mime,
                             datetime.now(timezone.utc).isoformat(), user, hashed, None, 'staging'))
        return identifier

    def canonical_new(self, path):
        clean_path(path)
        if not path:
            raise AppError('INVALID_PATH', 'Root cannot be changed')
        parent, _, name = path.rpartition('/')
        parent = self.folder(parent)
        return parent + '/' + name if parent else name

    def mkdir(self, session, path, parents=False):
        clean_path(path)
        if not path:
            raise AppError('DUPLICATE_NAME', 'Root already exists')
        self.free_name(path)
        made = []
        try:
            current = ''
            for index, part in enumerate(path.split('/')):
                candidate = current + '/' + part if current else part
                try:
                    current = self.folder(candidate)
                    self.check(session, current)
                    continue
                except AppError as exc:
                    if exc.code != 'NOT_FOUND':
                        raise
                if not parents and index < len(path.split('/')) - 1:
                    raise AppError('NOT_FOUND', 'Parent folder does not exist; use mkdirp')
                self.check(session, current)
                self.free_name(candidate)
                ident = self.insert(candidate, 'folder', session.user)
                made.append((candidate, ident))
                physical(self.root, candidate).mkdir()
                with self.db:
                    self.db.execute("UPDATE resources SET state='ready' WHERE id=?", (ident,))
                current = candidate
            return self.public(self.get(current))
        except Exception:
            for p, ident in reversed(made):
                physical(self.root, p).rmdir() if physical(self.root, p).exists() else None
                with self.db:
                    self.db.execute('DELETE FROM resources WHERE id=?', (ident,))
            raise

    def listing(self, session, path, offset=0):
        path = self.folder(path)
        self.check(session, path)
        rows = self.db.execute("SELECT * FROM resources WHERE parent=? AND state='ready' ORDER BY kind DESC,name", (path,)).fetchall()
        return {'items': [self.public(dict(r)) for r in rows[offset:offset+100]],
                'next_offset': offset+100 if len(rows) > offset+100 else None, 'path': path}

    def search(self, session, fields, offset=0):
        clauses, args = ["state='ready'", "kind='file'"], []
        for key, column in {'query': 'name', 'type': 'type', 'uploader': 'uploader', 'folder': 'parent', 'created': 'creation_time'}.items():
            value = fields.get(key, '')
            if not isinstance(value, str) or len(value) > 256:
                raise AppError('INVALID_INPUT', 'Search values must be strings up to 256 characters')
            if value:
                clauses.append('instr(lower(' + column + '), lower(?)) > 0')
                args.append(value)
        rows = self.db.execute('SELECT * FROM resources WHERE ' + ' AND '.join(clauses) + ' ORDER BY path', args).fetchall()
        visible = [dict(r) for r in rows if self.allowed_chain(session, self.chain(r['path'], False))]
        return {'items': [self.public(r) for r in visible[offset:offset+100]],
                'next_offset': offset+100 if len(visible) > offset+100 else None}

    def ensure_idle(self, path):
        if any(n and (p.lower() == path.lower() or p.lower().startswith(path.lower() + '/')) for p, n in self.busy.items()):
            raise AppError('RESOURCE_BUSY', 'Resource has an active transfer; try again after completion')

    def protect(self, session, path, password):
        row = self.get(path)
        self.check(session, row['path'], False)
        if row['uploader'].lower() != session.user.lower():
            raise AppError('ACCESS_DENIED', 'Only the resource creator can change its protection')
        self.ensure_idle(row['path'])
        hashed = password_hash(password) if password is not None else None
        with self.db:
            self.db.execute('UPDATE resources SET password_hash=? WHERE id=?', (hashed, row['id']))
        if hashed:
            session.grants[row['id']] = hashed
        else:
            session.grants.pop(row['id'], None)
        return {'protected': bool(hashed)}

    def access(self, session, path, password):
        row = self.get(path)
        self.check(session, row['path'], False)
        if row['password_hash'] and not verify(password, row['password_hash']):
            raise AppError('ACCESS_DENIED', 'Incorrect resource password')
        if row['password_hash']:
            session.grants[row['id']] = row['password_hash']
        return {'path': row['path'], 'access': 'granted'}

    def delete(self, session, path, kind):
        row = self.get(path, kind)
        self.check(session, row['path'])
        self.ensure_idle(row['path'])
        if kind == 'folder' and self.db.execute('SELECT 1 FROM resources WHERE parent=?', (row['path'],)).fetchone():
            raise AppError('NOT_EMPTY', 'Delete folder contents individually before deleting the folder')
        chain = self.chain(row['path'])
        target = physical(self.root, row['path'])
        with self.db:
            self.db.execute("UPDATE resources SET state='deleting' WHERE id=?", (row['id'],))
        try:
            target.rmdir() if kind == 'folder' else target.unlink()
        except OSError:
            with self.db:
                self.db.execute("UPDATE resources SET state='ready' WHERE id=?", (row['id'],))
            raise
        with self.db:
            self.db.execute('DELETE FROM resources WHERE id=?', (row['id'],))
        return self.public(row), chain
