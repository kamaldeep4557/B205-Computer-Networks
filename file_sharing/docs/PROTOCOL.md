# Application protocol version 1

## Framing and envelopes

Each frame is a 4-byte unsigned big-endian payload length followed by that many
UTF-8 JSON bytes. Maximum payload: 2 MiB. `recv_exact` loops until complete;
`sendall` handles partial writes. File bytes are base64-encoded in bounded JSON
chunk frames, so events and file data have unambiguous boundaries on one socket.
No request reads or sends a whole file in memory.

Request:

```json
{"type":"REQUEST","id":"unique-request-id","op":"LIST","params":{"path":"Documents","offset":0}}
```

Success:

```json
{"type":"RESPONSE","id":"unique-request-id","op":"LIST","data":{"items":[],"next_offset":null,"path":"Documents"}}
```

Operation error:

```json
{"type":"ERROR","id":"unique-request-id","code":"ACCESS_DENIED","message":"Protected resource: use access on locked ancestors first"}
```

Unrecoverable framing errors use `id: null` and close the connection. Malformed
operation parameters normally return a correlated error and keep the session.

Asynchronous server event (not tied to a request):

```json
{"type":"NOTIFICATION","event":"FILE_UPLOADED","actor":"Alice","path":"Documents/report.txt","resource_id":"resource-uuid"}
```

The server has a reader/handler thread and one writer thread per connection.
Only the writer sends frames; a bounded queue prevents frame interleaving and
keeps slow recipients from blocking the operation that generated an event.
The client reader dispatches correlated responses to request queues and emits
notifications immediately. One client operation request is outstanding at a
time; other clients remain independent. A heartbeat maintains idle sessions.

## Operations

`path` is a root-relative slash-separated resource path. Empty string is root
for listing/navigation; root cannot be created, protected or deleted. Resource
IDs identify metadata; paths select operations unambiguously. Required parameters
are listed first; optional parameters appear in brackets.

| Operation | Parameters | Successful response data |
| --- | --- | --- |
| CONNECT | none | protocol, chunk_size, max_file_size, idle_timeout |
| REGISTER | username, password | registration message; does not log in |
| LOGIN | username, password | canonical username |
| LIST | [path="", offset=0] | items (up to 100), next_offset, canonical path |
| SEARCH | [query, type, uploader, folder, created, offset=0] | matching file items, next_offset |
| CREATE_FOLDER | path, [parents=false] | folder metadata |
| DELETE_FILE | path | removed file metadata |
| DELETE_FOLDER | path | removed empty folder metadata |
| PROTECT | path, password | protected flag; null password removes protection |
| ACCESS | path, [password] | path, access="granted" |
| STATUS | none | connected usernames and current transfer mode/bytes/total |
| UPLOAD | path, size, [password] | transfer_id, UPLOAD_START, bytes, total |
| UPLOAD_CHUNK | transfer_id, offset, data (base64) | UPLOAD_PROGRESS, acknowledged bytes, total |
| UPLOAD_FINISH | transfer_id, sha256 | UPLOAD_COMPLETE, resource metadata |
| DOWNLOAD | path | transfer_id, DOWNLOAD_START, resource metadata |
| DOWNLOAD_CHUNK | transfer_id, offset | DOWNLOAD_PROGRESS, base64 data, bytes, total |
| DOWNLOAD_FINISH | transfer_id, sha256 | DOWNLOAD_COMPLETE |
| ABORT | none | ABORTED; close active transfer and release reservation |
| DISCONNECT | none | goodbye, then connection closes |

Only CONNECT, REGISTER, LOGIN and DISCONNECT are available before authentication.
`STATUS` includes only usernames, never account hashes or passwords. Unknown
operations produce `UNKNOWN_COMMAND`. SQL search uses literal case-insensitive
substrings, not client-provided SQL. LIST and SEARCH are paginated to remain
below the frame-size limit even with many resources.

## Upload state machine

1. Client opens local file, obtains its size and requests UPLOAD.
2. Server validates identity, parent access, size, name uniqueness and limits.
   It persists a staging row, reserves the path, and opens a private temporary
   file. An optional file password is hashed before any transfer starts.
3. Client sends successive UPLOAD_CHUNK requests. Offsets must equal the
   server's current received-byte count. No chunk exceeds the negotiated size;
   no transfer may exceed its declared size. Server writes and hashes the bytes,
   then acknowledges its real byte count. The client displays that progress.
4. Client sends UPLOAD_FINISH with its streaming SHA-256 digest. Server checks
   exact length and digest, flushes/fsyncs, renames the file into storage, and
   marks its metadata ready. Only then is completion returned and notification
   sent. The resource remains hidden while staging.
5. Error, ABORT or disconnect closes/removes partial data and staging metadata.
   Restart recovery removes unpublished staging rows/data after abrupt stops.

## Download state machine

1. Client reserves a new local target without overwriting existing files and
   creates a temporary output file. It requests DOWNLOAD.
2. Server checks all ancestor/file access, opens the stored file and obtains a
   read lease; the response includes size and stored SHA-256.
3. Client requests DOWNLOAD_CHUNK using the expected offset. The server sends
   bounded chunks. The client writes/hashes them and displays received bytes.
4. Client checks length and checksum and sends DOWNLOAD_FINISH with its digest.
   Server validates its own byte count and digest and releases the read lease.
   The client flushes/fsyncs and renames the output to the reserved destination.
5. Error/disconnect cleans local partial output and releases the server lease.
   Empty files skip the chunk loop and still pass checksum verification.

Progress at 100% means all content bytes were acknowledged/received. A transfer
is successful only after its explicit COMPLETE result; no timer-based progress
is used. SHA-256 checks integrity, not authenticity against an active attacker.

## Principal error codes

AUTH_REQUIRED, DUPLICATE_USER, USER_ONLINE, ALREADY_LOGGED_IN, ACCESS_DENIED,
RATE_LIMITED, INVALID_INPUT, INVALID_PATH, INVALID_REQUEST, UNKNOWN_COMMAND,
NOT_FOUND, WRONG_TYPE, DUPLICATE_NAME, NOT_EMPTY, RESOURCE_BUSY, TRANSFER_BUSY,
INVALID_TRANSFER, INVALID_OFFSET, INVALID_CHUNK, INCOMPLETE_TRANSFER,
LIMIT_EXCEEDED, STORAGE_ERROR, SERVER_ERROR, PROTOCOL_ERROR. The client additionally
uses CONNECTION_LOST and TIMEOUT; local filesystem exceptions are displayed.

## Data schema and consistency

`users`: username (case-insensitive primary key), password_hash.

`resources`: id, path (case-insensitive unique), parent, name, kind, size, type,
creation_time, uploader, password_hash (nullable), sha256, state.

`protected` is derived from password_hash and returned without the hash. UTC
creation_time is generated by the server, not trusted from the client. Resource
state is staging, ready or deleting. Metadata and filesystem operations are
serialized using a reentrant server lock; no socket I/O holds that lock. SQLite
WAL and synchronous FULL preserve committed intent. Ready rows are the only
ones listed/searched. Deletion first persists its intent, removes the actual
file/empty folder, then removes the row. An ordinary filesystem error restores
the ready row; recovery finishes interrupted delete intents on restart.
