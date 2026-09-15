# Executed validation record

Environment: Linux, Python 3.12.14.
Networking: actual loopback TCP sockets, with OS-assigned ports.
Storage: fresh temporary filesystem directories and real SQLite databases.

## Final automated suite

Command: `python3 -m unittest discover -s tests -v`

**44 tests passed; 0 failures, 0 errors, 0 skips.**
The final captured run took 24.779 seconds. Complete unedited stdout/stderr is
in `test-results.txt`. Tests cover server/client startup, three simultaneous
users, authentication, real byte transfers, checksums, metadata, search,
notifications, nested folders, access checks, concurrent conflicts, malformed
frames, traversal/symlink rejection, storage failure cleanup and persistence.

The disk-full condition is an explicitly injected OSError against the active
server-side upload handle (test 41); it is not a claim that a real disk was
filled. Restart recovery test 39 seeds staging/deleting intent records and
restarts the real server; it does not simulate a physical power failure.
Test 37 fragments actual socket writes into three-byte pieces and reads several
frames from the stream. Tests 21 and 22 close actual client TCP connections
mid-transfer and assert partial cleanup. Test 44 exercises the console run loop
against a real server using automated command/password input and verifies the
downloaded contents. Tests 19/20 issue conflicting operations concurrently from
three independent TCP clients.

## Three-user demonstration

Command: `python3 demo.py`

**DEMONSTRATION PASSED.** Full output is in `demo-results.txt`. The demonstration
connected Alice, Bob and Charlie, transferred 14,800 bytes, received actual
server events, queried metadata, rejected unauthorized access and an incorrect
password, verified downloaded bytes, and confirmed deletion plus notifications.
The server and data are isolated and automatically cleaned after this script.

## Other checks actually run

- Python source compilation after the initial client/server implementation.
- Focused upload/folder tests after correcting the database INSERT mismatch.
- Focused console/storage-error/symlink/missing-local-file tests: 4 passed.
- Server and client `--help` entry points executed successfully.
- Packaged ZIP content/CRC validation after creating the archive.

## Limits of this evidence

The Windows click-by-click setup instructions have been supplied, but this
execution environment was Linux; a Windows desktop or multi-machine LAN run
was not performed. The console was driven by automated input, not manually
clicked. No report screenshot is represented as having been captured on your
laptop. Follow `DEMONSTRATION.md` to capture your own screenshots.

No production security audit, sustained high-load benchmark, 1 GiB transfer,
physical disk exhaustion or hardware power-loss test was performed. See README
for unencrypted TCP, shared deletion permissions, path naming restrictions,
throughput limits, lack of resume and other scope boundaries. Passing tests does
not establish that arbitrary operating-system faults or hardware corruption
can be recovered automatically.

`reference-architecture.png` is the user-supplied design reference, not an execution screenshot.
