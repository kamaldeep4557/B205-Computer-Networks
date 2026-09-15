# Network File Sharing — Python TCP application

A complete console client/server project built with Python's standard library.
It supports real simultaneous users, persistent accounts and SQLite metadata,
streamed uploads/downloads, nested folders, search, resource passwords, server
notifications and byte-based progress. There are no third-party dependencies.

## Quick start on Windows

1. Extract the ZIP (right-click → **Extract All**). Open the extracted
   `file_sharing` folder. Do not run the project inside the ZIP preview.
2. Install Python **3.10 or newer**, if needed, with the Windows Python launcher.
   In a terminal, check `py -3 --version`. If the launcher is unavailable but
   Python is on PATH, substitute `python` for `py -3` throughout.
3. Click the File Explorer address bar in `file_sharing`, type `cmd`, and press
   Enter. The prompt must be in the folder containing `README.md`.
4. Start the server in that terminal:

   ```bat
   py -3 -m server.server
   ```

5. Open **three more terminals in the same folder**. In each, run:

   ```bat
   py -3 -m client.interface
   ```

6. Register a different account in each client. For example, client 1:

   ```text
   register Alice
   login Alice
   ```

   Enter your own account password at each hidden password prompt. Use `Bob`
   and `Charlie` in clients 2 and 3. Account passwords must be 8–128 characters.
   Accounts persist: on later runs use `login`, not `register` again.
7. Enter `status` to see Alice, Bob and Charlie connected to the same server.
8. Type `help` for commands. Follow `docs/DEMONSTRATION.md` for the full practical.
9. Exit clients with `exit`; stop the server with **Ctrl+C**.

All four processes run on one laptop using `127.0.0.1`. No cloud account,
Docker, paid service, database installation or Internet connection is required.
An optional virtual environment can be created with `py -3 -m venv .venv`; it
is unnecessary because this project uses only the standard library.

On Linux/macOS substitute `python3` for `py -3` in all commands.

## Run tests and an automated demonstration

```bat
py -3 -m unittest discover -s tests -v
py -3 demo.py
```

Tests and `demo.py` start their own servers on OS-assigned localhost ports and
use isolated temporary directories. They do not change your normal shared files
or require a manually started server. The demonstration uses three real TCP
clients and prints notifications, progress, search metadata and password checks.
The included `docs/test-results.txt` and `docs/demo-results.txt` contain actual
executed output; see `docs/VALIDATION.md` for scope and limitations.

## Files and folders

| Path | Purpose |
| --- | --- |
| `common/protocol.py` | Framing, exact receives, sendall, structured errors |
| `common/config.py` | Config validation, defaults and logging |
| `server/server.py` | Listener, threaded sessions, dispatcher, accounts, transfers, notifications |
| `server/storage.py` | SQLite resources, folder/file operations, ACL checks, recovery |
| `server/security.py` | Password hashing, usernames and safe paths |
| `client/client.py` | Socket client, receiver, heartbeat, transfers and progress callbacks |
| `client/interface.py` | Interactive commands and password prompts |
| `config/config.json` | Host, port, paths, transfer and resource limits |
| `tests/test_system.py` | Automated framing, integration, concurrency and recovery tests |
| `demo.py` | Executable three-user scenario |
| `samples/report.txt` | Small demonstration upload |
| `samples/project.zip` | Valid ZIP demonstration upload |
| `storage/` | Physical server folder hierarchy and completed files |
| `data/metadata.sqlite3` | Automatically created account/resource database |
| `data/partial_uploads/` | Automatically created temporary incoming files |
| `logs/server.log` | Automatically created activity/error log |
| `downloads/` | Default local download destination |
| `docs/PROTOCOL.md` | Request/response schemas and transfer sequences |
| `docs/DEMONSTRATION.md` | Commands, demonstration and screenshot guide |
| `docs/REQUIREMENTS.md` | Complete numbered requirement mapping and final checklist |

Runtime directories are initialized automatically. Do not manually edit the
server's storage or database while it is running. Back up both together while
the server is stopped. Run only **one server per database/storage pair**.

## Console commands

Remote paths are relative to the current folder. A leading `/` selects the
server root. The wire protocol itself uses relative root-based paths. Use
forward slashes for server paths. Quote local or remote paths containing spaces.

| Command | Example |
| --- | --- |
| `connect` / `disconnect` | Reconnect after a server restart |
| `register USER` / `login USER` | `register Alice` then `login Alice` |
| `list [FOLDER]` | `list /Documents` |
| `cd FOLDER`, `cd ..`, `cd /`, `pwd` | `cd /Documents/Networks` |
| `search TEXT [filters]` | `search report type=text/plain uploader=Alice folder=Documents` |
| `upload LOCAL [REMOTE]` | `upload "C:/Users/dell/Downloads/report.pdf" /Documents/report.pdf` |
| `download REMOTE [LOCAL]` | `download /Documents/report.pdf` |
| `mkdir FOLDER` | `mkdir Projects` |
| `mkdirp FOLDER/PATH` | `mkdirp /Documents/University/Networks` |
| `delete FILE` | `delete /Documents/report.pdf` (confirm `yes`) |
| `rmdir FOLDER` | `rmdir /Projects` (empty only; confirm `yes`) |
| `protect PATH` | `protect /Documents` (resource password prompt) |
| `unprotect PATH` | `unprotect /Documents` |
| `access PATH` | `access /Documents` (resource password prompt) |
| `status` | Connected users and active transfer |
| `notifications` | Last 200 events received by this client |
| `help` / `exit` | Show help / disconnect and exit |

`search` accepts optional `type`, `uploader`, `folder`, and `created` substring
filters. For example, `created=2026-09` filters upload timestamps. Filters combine
with AND. File MIME types are inferred using Python `mimetypes`, based on the
filename extension; they are not content-verified. Metadata includes a unique
ID, full path, name, parent, size, MIME type, UTC upload time, uploader, protection
flag and SHA-256. Password hashes are never sent to clients.

## Permissions and behavior

This is a **shared workspace**: authenticated users may read, upload into,
create within, and delete unlocked resources, including files uploaded by other
users. This permits Bob to delete Alice's public file in the required scenario.
Only the resource creator can change or remove its password protection.

- All protected ancestors must be unlocked before accessing a descendant.
- A protected file requires its own unlock in addition to any ancestor unlocks.
- `access` grants permission for the current connection only. Unlock from the
  outermost folder inward. Reconnects require passwords again.
- Creating protection verifies the creator's new password by hashing it and
  grants that creator access for the current session. On a new session, even
  the creator must unlock protected content. Creators can reset their own
  resource password after unlocking its parent folders.
- Changing a password immediately invalidates other clients' old grants.
- Listings show a locked child's name/metadata so it can be selected for
  `access`. A locked folder's **contents** are hidden from listing and search.
  A protected file's own metadata is visible if its ancestors are accessible.
- Notifications about locked resources are sent only to clients with access.
  They are live events, not a persistent notification history.
- Non-empty folder deletion is rejected. Delete contents individually, then
  remove the empty folder. There is no recursive destructive-delete command.
- File and folder names share one case-insensitive namespace within each
  folder, making collision handling consistent across Windows and Linux.
  The same name in different folders is allowed.
- A transfer reserves its resource until completion/abort/disconnect. Deletion
  and protection changes that would invalidate it return `RESOURCE_BUSY`.
- Partial uploads are never listed as completed files. A size or checksum
  mismatch discards the upload. Failed downloads remove their local partial
  data. The client never overwrites an existing download target.

## Configuration

Edit `config/config.json` before startup, or supply a custom configuration:

```bat
py -3 -m server.server --config C:/path/server-config.json
py -3 -m client.interface --config C:/path/client-config.json
```

For the supplied config, relative paths resolve against the project directory.
For a custom config, they resolve against its containing directory, except a
file inside a directory named `config` resolves against that directory's parent.
Missing settings use defaults. A missing config file uses the defaults as well.
Default chunk size is 64 KiB; the file limit is 1 GiB, resource limit 10,000 and
connection limit 64. These are operational limits, not a one-level hierarchy
restriction. The standard client uses heartbeat requests to keep idle sessions
alive. The server closes idle/unresponsive raw clients after the configured
socket timeout. Per-connection queues are bounded to isolate slow clients.

For a trusted LAN, set the server's bind `host` to its LAN IP or `0.0.0.0`, and
set each client's `host` to the actual server LAN IP (never `0.0.0.0`). Allow the
chosen TCP port through the server firewall only on the intended network.

## Security boundaries and limitations

Passwords are stored as PBKDF2-HMAC-SHA256 hashes with 600,000 iterations and a
separate random 128-bit salt. They are not logged. Paths reject traversal,
absolute wire paths, symlinks, Windows reserved names and unsafe characters.
SQL parameters are bound, and server-side permission checks cannot be bypassed
by sending commands outside the console.

**TCP traffic is not encrypted.** This project does not implement TLS, MFA,
malware scanning or production-grade abuse protection. Use localhost for the
assignment demonstration. The ten-denial per-connection limit is basic; it can
be reset by reconnecting. Local server administrators can read stored files.
File passwords control application access; they do not encrypt stored content.

Paths use portable printable ASCII names (120 characters per component, 1,024
per full path). There is no transfer resume, rename/move, GUI or persistent
notification replay. Base64 adds approximately one-third to chunk bandwidth,
and each chunk waits for acknowledgement. Short storage operations and password
verification share a lock; this favors correctness over high throughput.
Temporary upload storage and completed storage should be on the same filesystem
because publication uses an atomic rename. Startup recovery handles persisted
staging/deleting intents; arbitrary hardware corruption and external edits are
outside that recovery guarantee. An OS-killed client can leave a temporary
local download file and an empty reserved destination; remove those manually
before retrying. Ordinary detected transfer failures clean them automatically.

## Troubleshooting

- `No module named server`: open a terminal in `file_sharing`, not `server`.
- Connection refused: start the server first; confirm matching host/port.
- Address already in use: stop the earlier server, or choose a new port in both
  configurations. Do not run two servers against the same data directory.
- Duplicate username: use `login`. For `USER_ONLINE`, close the older client.
- Access denied: unlock all protected folders from the top down, then the file.
- Duplicate name: choose a new name, another folder, or intentionally delete the
  existing item through the client first.
- Download target exists: choose another local filename; no automatic overwrite.
- Logs report a storage error: check disk space, directory permissions and that
  database/temp directories are outside the public storage tree.
