# Requirement audit

This maps all 55 numbered sections of the supplied request to the integrated
implementation and evidence. Test numbers refer to named methods in
`tests/test_system.py` and `tests/test_console.py`. Functionality is implemented;
performance/security boundaries are documented in README rather than presented
as production guarantees. No optional GUI or third-party framework is used.

| Request section | Implementation / evidence |
| --- | --- |
| 1. Technology and architecture | Python standard library; `server/server.py`, `client/client.py`, supporting common/security/storage modules. Tests 01, 34. |
| 2. Main objective | Integrated shared workspace; console invokes server operations over TCP. `demo.py`; test 44. |
| 3. Socket communication | Server socket/bind/listen/accept; Client socket/connect; thread-per-session; close/shutdown. Tests 01, 18, 40. |
| 4. Custom protocol | Structured REQUEST/RESPONSE/ERROR/NOTIFICATION; `common/protocol.py`, `docs/PROTOCOL.md`. Tests 16, 32, 37. |
| 5. Multi-user functionality | Persistent case-insensitive unique usernames; registration/login; active-session uniqueness. Tests 01, 02, 27. |
| 6. Upload | UPLOAD/CHUNK/FINISH streaming, staging, progress, duplicate/size/input/storage checks. Tests 03, 08, 15, 21, 28, 36, 41, 43. |
| 7. Download | DOWNLOAD/CHUNK/FINISH, access checks, verified output and failure cleanup. Tests 04, 10, 15, 17, 22, 33. |
| 8. File search | SQLite-backed filename/type/uploader/folder/time filtering; `Storage.search`. Test 05. |
| 9. File metadata | Persistent resource rows created at upload; public fields returned to clients. Tests 03, 05, 38. |
| 10. Folder system | `Storage.mkdir`, `listing`; console cd/pwd/mkdirp; arbitrary nested levels within path limits. Tests 07, 44. |
| 11. Unique names | SQLite NOCASE unique path plus lock/reservation checks; same name in different parents allowed. Tests 08, 09, 19, 20. |
| 12. File deletion | `Storage.delete`: access, physical removal, metadata removal, event distribution. Tests 06, 14. |
| 13. Folder deletion | Empty-only; protected access required; non-empty rejection; root/path protection. Test 26. |
| 14. Protected files | PROTECT/ACCESS, optional upload password; salted PBKDF2. Tests 10, 12. |
| 15. Protected folders | Recursive chain checks on every descendant operation. Tests 11, 35. |
| 16. Access control | Server-enforced ancestor/file ACLs; creator-only protection changes; protected event filtering. Tests 10–12, 26, 30, 35. |
| 17. Notifications | `Server.notify`, per-session writer queues, client background receiver. Tests 13, 14, 30, 34. |
| 18. Upload status | UPLOAD_START/PROGRESS/COMPLETE; acknowledged storage byte counts. Test 15. |
| 19. Download status | DOWNLOAD_START/PROGRESS/COMPLETE; actual received-byte progress. Test 15. |
| 20. Event design | Resource mutation then ACL-filtered server event; bounded outbound queue and disconnected-client cleanup. Tests 13, 14, 18, 30. |
| 21. Path security | `clean_path`, `physical`: no absolute paths/traversal/symlinks or escaped roots. Tests 23, 42. |
| 22. Input validation | Usernames, paths, sizes, chunk data/offsets, IDs, frame bounds, search params. Tests 16, 23, 25, 27, 32, 36. |
| 23. Concurrency | Per-session threads, shared-state RLock, upload reservations/read leases. Tests 19, 20, 31. |
| 24. Metadata storage | SQLite WAL/FULL; staging/ready/deleting states and restart recovery. Tests 06, 21, 28, 38, 39, 41. |
| 25. Configuration | `common/config.py`, `config/config.json`, `--config` flags, validated defaults/paths. Test 25. |
| 26. Logging | Python logging to console and file; startup/shutdown/auth/activity/transfer/rejection/error events. Test 24; demo output. |
| 27. Error handling | Structured AppError and storage/protocol errors; timeout/disconnect handling; independent sessions. Tests 16–18, 21–23, 28, 32, 36, 40, 41, 43. |
| 28. Client interface | Console command loop, password prompts, navigation, transfers, notifications, reconnect/exit. Test 44. |
| 29. Server interface | Readable console logging with bound host/port and client/activity events. `demo-results.txt`. |
| 30. File storage | Dedicated physical hierarchy under configured root, private partial directory outside it. Tests 03, 07, 21, 23. |
| 31. Resource identification | UUID resource IDs and full canonical resource paths; separate transfer IDs. Tests 03, 09. |
| 32. File type detection | `mimetypes.guess_type(name)`; fallback application/octet-stream. Extension-based limitation documented. Tests 03, 05. |
| 33. Creation time | Server-generated `datetime.now(timezone.utc).isoformat()`. Test 03. |
| 34. Listing | Paginated public file/folder metadata; password flag, ownership, time, size and type. Tests 07, 11, 44. |
| 35. Search results | Console formatted JSON of real metadata; public fields exclude password hashes. Tests 03, 05, 44. |
| 36. Message framing | Four-byte network-order length; exact partial reads and sendall. Tests 32, 37. |
| 37. Chunking | Negotiated bounded base64 chunks; ACK per chunk; no whole-file buffering in production transfer code. Tests 04, 15, 36. |
| 38. Interrupted transfers | ABORT/finally cleanup, disconnected-session cleanup and durable staging recovery. Tests 21, 22, 28, 39, 41. |
| 39. Server state | Server/session/storage classes hold users, connections, grants, transfer handles and reservations; no mutable global server state. Tests 01, 18, 31. |
| 40. Organization | Cohesive server/client/common/config/tests/docs modules; README inventory. |
| 41. Dependencies | Standard-library-only imports; no package installation required. All executed tests run without third-party packages. |
| 42. Security design | PBKDF2 salts, ACLs, path/input guards, parameterized SQL, controlled root; plaintext TCP limitation explicit. Tests 10–12, 23, 24, 27, 35, 42. |
| 43. Server startup | `python -m server.server`; configuration/logging/storage/listener initialization. Tests 01, 38, 39. |
| 44. Client startup | `python -m client.interface`; connect, structured handshake, authentication and background events. Tests 01, 44. |
| 45. Automatic initialization | Directories, SQLite tables/indexes and logs created on startup; configured defaults available. Tests use initially empty temporary directories. |
| 46. Testing | Executable unittest suite covers all 30 requested minimum test categories; `test-results.txt` records executed results. |
| 47. Three-user test | Test 34 follows Alice/Bob/Charlie workflow; `demo.py` includes protected resources and actual byte comparison. |
| 48. Demonstration | `docs/DEMONSTRATION.md` manual commands and screenshots; executable `demo.py`; test 44 exercises console. |
| 49. Networking quality | Genuine socket-based transport for every client operation; framed events, transfer messages, concurrent connections and termination. Tests 01, 13–15, 18–22, 32, 34, 37. |
| 50. Performance/resources | Bounded chunks/queues, pagination, connection/resource limits, heartbeat, finally cleanup, leased open file handles. Tests 15, 18, 21, 22, 31. |
| 51. Final quality | Integrated application, full tests, demo, README, protocol and explicit limitations. See validation record. |
| 52. Development approach | Protocol/config/security → persistent operations → server → client → tests → defect fix → validation/docs/package. |
| 53. Debugging | Initial resource INSERT placeholder mismatch reproduced, fixed in `Storage.insert`, focused tests passed, then full suite passed. |
| 54. Final audit | Detailed checklist below, linked to implementation locations. |
| 55. Deliverables | ZIP includes every source/config/test file, samples, protocol, setup/run/commands, actual results, audit and limitations. Database initializes at runtime; no fabricated accounts/database supplied. |

## Minimum test categories requested in section 46

| Requested category | Test(s) |
| --- | --- |
| Server startup; client connection; three clients | 01, 34, 38 |
| Unique usernames | 02, 27 |
| Upload; download; search; metadata | 03–05 |
| File deletion | 06, 14 |
| Folder creation; nested folders | 07, 44 |
| Duplicate file/folder names | 08, 09, 19, 20 |
| Protected file; protected folder; wrong password; unauthorized access | 10–12, 26, 27, 35 |
| Real-time upload/deletion notifications | 13, 14, 30 |
| Upload/download progress | 15 |
| Invalid command; missing file/folder | 16, 17, 43 |
| Client disconnection | 18 |
| Simultaneous operations | 19, 20, 31 |
| Network interruption | 21, 22 |
| Path traversal | 23, 42 |
| Logging | 24 |
| Configuration | 25 |

## Section 54 checklist

| Implemented requirement | Location |
| --- | --- |
| [x] Python | server/server.py; client/client.py (real Python TCP sessions) |
| [x] Client-server architecture | server/server.py; client/client.py (real Python TCP sessions) |
| [x] Socket programming | server/server.py; client/client.py (real Python TCP sessions) |
| [x] TCP communication | server/server.py; client/client.py (real Python TCP sessions) |
| [x] At least three users | server/server.py; client/client.py (real Python TCP sessions) |
| [x] Multiple simultaneous clients | server/server.py; client/client.py (real Python TCP sessions) |
| [x] Unique usernames | server/server.py; client/client.py (real Python TCP sessions) |
| [x] File upload | Server.dispatch/abort; Client.upload/download |
| [x] File download | Server.dispatch/abort; Client.upload/download |
| [x] File search | Storage.search; Console.execute |
| [x] File deletion | Storage.delete; Server.notify |
| [x] File metadata | server/storage.py: resource schema, insert, public, search |
| [x] File size | server/storage.py: resource schema, insert, public, search |
| [x] File type | server/storage.py: resource schema, insert, public, search |
| [x] Creation time | server/storage.py: resource schema, insert, public, search |
| [x] Uploader username | server/storage.py: resource schema, insert, public, search |
| [x] Metadata storage | server/storage.py: resource schema, insert, public, search |
| [x] Metadata delivery | server/storage.py: resource schema, insert, public, search |
| [x] Metadata search | server/storage.py: resource schema, insert, public, search |
| [x] File creation | Server.dispatch/abort; Client.upload/download |
| [x] Folder creation | Storage.mkdir/folder/listing/free_name/delete |
| [x] Recursive folders | Storage.mkdir/folder/listing/free_name/delete |
| [x] Unique file names within folders | Storage.mkdir/folder/listing/free_name/delete |
| [x] Unique folder names within folders | Storage.mkdir/folder/listing/free_name/delete |
| [x] Password-protected files | server/security.py; Storage.check/access/protect |
| [x] Password-protected folders | server/security.py; Storage.check/access/protect |
| [x] Secure password handling | server/security.py; Storage.check/access/protect |
| [x] Access control | server/security.py; Storage.check/access/protect |
| [x] Real-time new-file notifications | Server.notify; Session.write_loop; Client.read_loop |
| [x] Real-time deletion notifications | Server.notify; Session.write_loop; Client.read_loop |
| [x] Upload status | Server.dispatch/abort; Client.upload/download |
| [x] Download status | Server.dispatch/abort; Client.upload/download |
| [x] Actual transfer progress | Server.dispatch/abort; Client.upload/download |
| [x] Custom application protocol | common/protocol.py; docs/PROTOCOL.md |
| [x] Message framing | common/protocol.py; docs/PROTOCOL.md |
| [x] Concurrent clients | server/server.py; client/client.py (real Python TCP sessions) |
| [x] Error handling | common/protocol.py AppError; Session.run; Console.run |
| [x] Logging | common/config.py; config/config.json |
| [x] Configuration | common/config.py; config/config.json |
| [x] Input validation | server/security.py; Server.dispatch |
| [x] Path traversal protection | server/security.py; Server.dispatch |
| [x] Chunked file transfer | Server.dispatch/abort; Client.upload/download |
| [x] Interrupted-transfer handling | Server.dispatch/abort; Client.upload/download |
| [x] Persistent metadata | server/storage.py: resource schema, insert, public, search |
| [x] Client interface | client/interface.py; server/server.py main/logging |
| [x] Server interface | client/interface.py; server/server.py main/logging |
| [x] Automated/manual testing | tests/test_system.py; tests/test_console.py; demo.py |
| [x] Three-user integration test | tests/test_system.py; tests/test_console.py; demo.py |
