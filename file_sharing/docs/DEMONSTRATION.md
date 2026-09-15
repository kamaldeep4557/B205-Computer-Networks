# Manual practical and screenshot guide

Run this after the README setup. Keep server, Alice, Bob and Charlie terminals
open together. Choose your own passwords at the prompts. Commands below assume
each client starts in server root and no demonstration files already exist.
The `samples` paths work when the client starts in the project directory.

## 1. Establish three sessions

Server terminal: `py -3 -m server.server`.

Each client terminal: `py -3 -m client.interface`.

Register then log in as Alice, Bob and Charlie using their respective terminals.
If an account already exists, log in only. In Alice's terminal enter `status`.
It must list all three users. Passwords are never shown on screen.

## 2. Nested folders, upload and notifications

Alice:

```text
mkdirp /Documents/University/Networks
upload samples/report.txt /Documents/University/Networks/report.txt
list /Documents/University/Networks
```

Bob and Charlie receive `FILE_UPLOADED` automatically, without typing refresh.
Type `notifications` if the immediate event has scrolled out of view.
Alice's terminal shows START, acknowledged bytes/progress and COMPLETE.

Charlie:

```text
search report type=text/plain uploader=Alice
cd /Documents/University/Networks
pwd
list
cd /
```

The response includes actual metadata, not example or hard-coded records.

## 3. Shared projects and duplicate names

Bob:

```text
mkdir /Projects
```

Alice:

```text
upload samples/project.zip /Projects/project.zip
upload samples/project.zip /Projects/project.zip
mkdir /Projects
```

The first upload succeeds. The second upload and repeated folder creation return
`DUPLICATE_NAME`. To prove names can repeat across folders, Alice can upload
`samples/report.txt` to `/Projects/report.txt` as well.

Charlie:

```text
download /Projects/project.zip
```

The ZIP is saved in `downloads/project.zip`. Open it using File Explorer to
inspect its two sample files. Choose another destination if it already exists:
`download /Projects/project.zip downloads/project-copy.zip`.

## 4. Protect a folder and validate inherited access

Alice:

```text
protect /Documents
```

Enter a resource password (8–128 characters). Tell Bob and Charlie this
resource password for the demonstration; do not share Alice's account password.

Charlie:

```text
list /Documents/University/Networks
download /Documents/University/Networks/report.txt
access /Documents
```

The first two operations are denied. At the first `access` prompt, intentionally
enter an incorrect resource password to show rejection. Then enter:

```text
access /Documents
list /Documents/University/Networks
download /Documents/University/Networks/report.txt
```

Supply the correct resource password. Access to the descendant folder now works,
and the download shows actual bytes received and successful completion.

## 5. Protect a file independently

Alice:

```text
protect /Projects/project.zip
```

Charlie:

```text
download /Projects/project.zip downloads/protected-project.zip
access /Projects/project.zip
download /Projects/project.zip downloads/protected-project.zip
```

The first attempt is denied and its local partial output is cleaned. Enter the
correct file password for `access`; the second download succeeds. Folder and
file protections combine when a protected file is inside a protected folder.

Bob can also attempt `protect /Projects/project.zip`: it is denied because Alice
created the file. Only Alice can change that file's protection.

## 6. Delete a shared file and receive events

Bob:

```text
access /Documents
delete /Documents/University/Networks/report.txt
```

Enter the correct folder password, then confirm deletion with `yes`. Alice and
Charlie receive `FILE_DELETED`. Charlie's `search report folder=Documents`
returns no matching file. The file and metadata have both been removed.

Alice can demonstrate safe folder deletion:

```text
rmdir /Documents
rmdir /Documents/University/Networks
```

Confirm each with `yes`. The non-empty parent is rejected; the now-empty Networks
folder can be deleted. No recursive deletion is performed.

## 7. Disconnection and persistence

Bob enters `exit`. Alice enters `status` to show that Bob has been removed from
the connected-user list. Exit other clients and stop the server with Ctrl+C.
Restart it, start a client and log in to the same account. Existing folders and
remaining files are still present. A protected resource needs a fresh `access`
command after reconnecting.

## Screenshots to capture from your actual run

These are suggested evidence images; none are fabricated or pre-populated.
Use Windows Snipping Tool (**Win+Shift+S**) and save images with meaningful names.

| Evidence | Capture | Suggested report caption |
| --- | --- | --- |
| 01 | Server startup with host/port and all three clients logged in; `status` lists their names | Figure 1: TCP server with three simultaneously connected clients. |
| 02 | `mkdirp`, `cd`, `pwd` and nested folder listing | Figure 2: Creation and navigation of a nested server folder hierarchy. |
| 03 | Upload START/PROGRESS/COMPLETE and actual byte counts | Figure 3: Chunked file upload with acknowledged byte-based progress. |
| 04 | Bob/Charlie notification displayed automatically | Figure 4: Real-time server notification received by other clients. |
| 05 | Search results showing path, size, MIME type, UTC time, uploader and ID | Figure 5: Metadata-based search of uploaded files. |
| 06 | Rejected duplicate filename and folder name | Figure 6: Server-side enforcement of unique names within a folder. |
| 07 | Protected ancestor denies child listing/download; incorrect password denied | Figure 7: Recursive folder access control and password rejection. |
| 08 | Correct password access and successful file download with progress | Figure 8: Authorized download with transfer completion verification. |
| 09 | Independent file protection and unauthorized protection change rejected | Figure 9: File-level protection and creator-only protection management. |
| 10 | Bob deletion, other-client notifications and empty search result | Figure 10: File deletion, metadata removal and real-time notifications. |
| 11 | Non-empty folder rejection and empty-folder deletion | Figure 11: Safe folder deletion behavior. |
| 12 | Your `unittest` final summary and selected named tests | Figure 12: Executed automated integration test results. |
| 13 | Server activity log and successful login/listing after restart | Figure 13: Server logging and persistent resource recovery after restart. |

For larger visible progress, choose a local non-sensitive file several MiB in
size. Progress is always derived from real transferred bytes. Do not invent
intermediate percentages or alter screenshots to imply unexecuted tests.
