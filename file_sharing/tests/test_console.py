"""Exercise the actual console command loop without manual password entry."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from client.interface import Console
from tests.test_system import config, start, PASSWORD, SECRET

class ConsoleTests(unittest.TestCase):
    def test_44_console_end_to_end(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = config(root)
            server, thread = start(cfg)
            cfg['port'] = server.address[1]
            source = root / 'local file.txt'
            source.write_text('console file transfer')
            target = root / 'result file.txt'
            commands = iter([
                'register ConsoleUser', 'login ConsoleUser',
                'mkdirp /Docs/Nested', 'cd /Docs/Nested', 'pwd',
                f'upload "{source}" report.txt', 'list',
                'search report type=text/plain', 'protect report.txt',
                'access report.txt', f'download report.txt "{target}"',
                'status', 'notifications', 'unprotect report.txt',
                'delete report.txt', 'yes', 'cd ..', 'rmdir Nested', 'yes',
                'cd /', 'help', 'disconnect', 'connect', 'login ConsoleUser', 'exit'
            ])
            console = Console(cfg)
            output = io.StringIO()
            try:
                with redirect_stdout(output), patch('builtins.input', side_effect=lambda _: next(commands)), patch('getpass.getpass', side_effect=[PASSWORD, PASSWORD, SECRET, SECRET, PASSWORD]):
                    console.run()
                self.assertEqual(target.read_text(), source.read_text())
                text = output.getvalue()
                self.assertNotIn('ERROR', text)
                self.assertIn('UPLOAD_COMPLETE', text)
                self.assertIn('DOWNLOAD_COMPLETE', text)
                self.assertIn('Current folder: /Docs/Nested', text)
            finally:
                if console.client:
                    console.client.disconnect()
                server.stop()
                thread.join(2)
