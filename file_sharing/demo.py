"""Run a real three-client TCP demonstration in isolated temporary storage."""
import json
import secrets
import tempfile
import threading
from pathlib import Path
from client.client import Client
from common.config import load_config
from common.protocol import AppError
from server.server import Server

def main():
    with tempfile.TemporaryDirectory(prefix='file-sharing-demo-') as temp:
        root = Path(temp)
        cfg_path = root / 'config.json'
        cfg_path.write_text(json.dumps({'port': 0, 'chunk_size': 4096}))
        server = Server(load_config(cfg_path))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        clients = []
        account_password, resource_password = secrets.token_urlsafe(18), secrets.token_urlsafe(18)
        try:
            for name in ('Alice', 'Bob', 'Charlie'):
                c = Client(*server.address)
                c.register(name, account_password)
                c.login(name, account_password)
                clients.append(c)
            alice, bob, charlie = clients
            print('CONNECTED:', alice.request('STATUS')['users'])
            alice.request('CREATE_FOLDER', path='Documents/University/Networks', parents=True)
            source = root / 'report.txt'
            source.write_text('Networked file-sharing demonstration\n' * 400)
            remote = 'Documents/University/Networks/report.txt'
            def progress(status, done, total):
                print(f'{status}: {done}/{total} bytes ({100 if not total else done*100/total:.1f}%)')
            alice.upload(source, remote, progress=progress)
            print('BOB RECEIVED:', bob.events.get(timeout=3))
            print('CHARLIE RECEIVED:', charlie.events.get(timeout=3))
            print('CHARLIE SEARCH:', json.dumps(charlie.pages('SEARCH', query='report'), indent=2))
            alice.request('PROTECT', path='Documents', password=resource_password)
            try:
                charlie.request('DOWNLOAD', path=remote)
                raise AssertionError('Unauthorized download unexpectedly accepted')
            except AppError as exc:
                assert exc.code == 'ACCESS_DENIED'
                print('UNAUTHORIZED DOWNLOAD:', exc.code)
            try:
                charlie.request('ACCESS', path='Documents', password='IncorrectPassword!')
                raise AssertionError('Wrong password unexpectedly accepted')
            except AppError as exc:
                assert exc.code == 'ACCESS_DENIED'
                print('WRONG PASSWORD:', exc.code)
            charlie.request('ACCESS', path='Documents', password=resource_password)
            target = root / 'downloaded-report.txt'
            charlie.download(remote, target, progress=progress)
            assert target.read_bytes() == source.read_bytes()
            print('DOWNLOAD VERIFIED: source and destination bytes match')
            bob.request('ACCESS', path='Documents', password=resource_password)
            bob.request('DELETE_FILE', path=remote)
            print('ALICE RECEIVED:', alice.events.get(timeout=3))
            print('CHARLIE RECEIVED:', charlie.events.get(timeout=3))
            assert charlie.pages('SEARCH', query='report') == []
            print('DELETION VERIFIED: no stale metadata')
            print('DEMONSTRATION PASSED')
        finally:
            for c in clients:
                c.disconnect()
            server.stop()
            thread.join(2)

if __name__ == '__main__':
    main()
