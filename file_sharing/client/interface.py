"""Interactive console. Passwords are collected privately with getpass."""
import argparse
import getpass
import json
import shlex
import threading
from pathlib import Path
from common.config import load_config
from common.protocol import AppError
from client.client import Client

HELP = '''Commands (quote paths containing spaces; use forward slashes):
  connect                    Reconnect using configuration
  register USER              Create account (password prompt)
  login USER                 Log in (password prompt)
  list [FOLDER]              List names and full metadata
  cd FOLDER | cd .. | cd /    Navigate server folders
  pwd                        Show current server folder
  search TEXT [key=value...] Keys: type, uploader, folder, created
  upload LOCAL [REMOTE]      Upload into current folder or specified path
  download REMOTE [LOCAL]    Download (default: configured downloads folder)
  mkdir FOLDER               Create one folder
  mkdirp FOLDER/PATH         Create nested folders and missing ancestors
  delete FILE               Delete file (shared workspace permissions)
  rmdir FOLDER               Delete EMPTY folder
  protect PATH               Set/change resource password (creator only)
  unprotect PATH             Remove password (creator only)
  access PATH                Unlock resource for this session (password prompt)
  status                     Connected users and active transfer
  notifications              Show last 200 received events
  disconnect                 Close connection; console remains open
  help | exit
Remote paths are relative to current folder; a leading / means server root.
All authenticated users can modify unlocked shared resources. Only creators
can change protection. Unlock protected ancestors from the top down.
'''

class Console:
    def __init__(self, config):
        self.config, self.client, self.cwd = config, None, ''
        self.output_lock = threading.Lock()

    def show(self, value):
        with self.output_lock:
            print(value, flush=True)

    def notification(self, message):
        self.show('\n[NOTIFICATION] {actor} {event}: /{path}'.format(**message))

    def progress(self, status, done, total):
        percent = 100 if total == 0 else done * 100 / total
        self.show(f'{status}: {percent:6.1f}% | {done:,} / {total:,} bytes')

    def remote(self, text):
        if text.startswith('/'):
            return text[1:]
        return self.cwd + '/' + text if self.cwd else text

    def connect(self):
        if self.client and not self.client.closed.is_set():
            raise AppError('ALREADY_CONNECTED', 'Disconnect first')
        self.client = Client(self.config['host'], self.config['port'], self.config['socket_timeout'], self.notification)
        self.cwd = ''
        self.show('Connected to server. Use register USER or login USER.')

    def execute(self, line):
        # posix=False retains Windows backslashes; strip surrounding quotes only.
        args = [x[1:-1] if len(x) >= 2 and x[0] == x[-1] and x[0] in '\"\'' else x
                for x in shlex.split(line, posix=False)]
        if not args:
            return True
        cmd, rest = args[0].lower(), args[1:]
        if cmd == 'exit':
            return False
        if cmd == 'help':
            self.show(HELP)
            return True
        if cmd == 'connect':
            self.connect()
            return True
        c = self.client
        if not c or c.closed.is_set():
            raise AppError('CONNECTION_LOST', 'Use connect first')
        if cmd == 'disconnect':
            c.disconnect()
            self.show('Disconnected')
            return True
        if cmd in ('register', 'login'):
            if len(rest) != 1:
                raise ValueError('Usage: ' + cmd + ' USER')
            result = getattr(c, cmd)(rest[0], getpass.getpass('Account password: '))
        elif cmd == 'pwd':
            result = '/' + self.cwd
        elif cmd == 'list':
            result = c.pages('LIST', path=self.remote(rest[0]) if rest else self.cwd)
        elif cmd == 'cd':
            if len(rest) != 1:
                raise ValueError('Usage: cd FOLDER')
            path = self.cwd.rpartition('/')[0] if rest[0] == '..' else self.remote(rest[0])
            self.cwd = c.request('LIST', path=path)['path']
            result = 'Current folder: /' + self.cwd
        elif cmd == 'search':
            if not rest:
                raise ValueError('Usage: search TEXT [type=value uploader=value folder=value created=value]')
            fields = dict(item.split('=', 1) for item in rest[1:])
            if set(fields) - {'type', 'uploader', 'folder', 'created'}:
                raise ValueError('Unknown search field')
            result = c.pages('SEARCH', query=rest[0], **fields)
        elif cmd in ('upload', 'download'):
            if not 1 <= len(rest) <= 2:
                raise ValueError('Usage: ' + cmd + ' SOURCE [DESTINATION]')
            if cmd == 'upload':
                local = Path(rest[0]).expanduser()
                result = c.upload(local, self.remote(rest[1] if len(rest) == 2 else local.name), progress=self.progress)
            else:
                remote = self.remote(rest[0])
                local = rest[1] if len(rest) == 2 else str(Path(self.config['download_dir']) / remote.rsplit('/', 1)[-1])
                result = c.download(remote, local, progress=self.progress)
        elif cmd in ('mkdir', 'mkdirp', 'delete', 'rmdir', 'protect', 'unprotect', 'access'):
            if len(rest) != 1:
                raise ValueError('Usage: ' + cmd + ' PATH')
            path = self.remote(rest[0])
            if cmd in ('mkdir', 'mkdirp'):
                result = c.request('CREATE_FOLDER', path=path, parents=cmd == 'mkdirp')
            elif cmd in ('delete', 'rmdir'):
                if input('Permanently delete /' + path + '? Type yes: ').strip() != 'yes':
                    return True
                result = c.request('DELETE_FILE' if cmd == 'delete' else 'DELETE_FOLDER', path=path)
            else:
                password = None if cmd == 'unprotect' else getpass.getpass('Resource password: ')
                result = c.request('ACCESS' if cmd == 'access' else 'PROTECT', path=path, password=password)
        elif cmd == 'status':
            result = c.request('STATUS')
        elif cmd == 'notifications':
            result = list(c.notifications)
        else:
            raise ValueError('Unknown command. Use help.')
        self.show(json.dumps(result, indent=2) if not isinstance(result, str) else result)
        return True

    def run(self):
        self.show('NETWORK FILE SHARING | TCP / Python / SQLite\n' + HELP)
        try:
            self.connect()
        except OSError as exc:
            self.show('Connection failed: ' + str(exc) + '. Start the server, then use connect.')
        try:
            while True:
                try:
                    user = self.client.user if self.client and self.client.user else 'guest'
                    if not self.execute(input(f'{user}:/{self.cwd}> ')):
                        break
                except (AppError, OSError, ValueError) as exc:
                    self.show('ERROR ' + getattr(exc, 'code', '') + ': ' + str(exc))
        except (EOFError, KeyboardInterrupt):
            self.show('\nClosing client...')
        finally:
            if self.client:
                self.client.disconnect()

def main():
    parser = argparse.ArgumentParser(description='Interactive file-sharing client')
    parser.add_argument('--config')
    args = parser.parse_args()
    Console(load_config(args.config)).run()

if __name__ == '__main__':
    main()
