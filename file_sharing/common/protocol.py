"""Four-byte big-endian length followed by bounded UTF-8 JSON."""
import json
import struct
MAX_FRAME = 2 * 1024 * 1024

class AppError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

def recv_exact(sock, size):
    result = bytearray()
    while len(result) < size:
        part = sock.recv(size - len(result))
        if not part:
            raise EOFError('Connection closed during receive')
        result.extend(part)
    return bytes(result)

def send_message(sock, message):
    payload = json.dumps(message, ensure_ascii=True, allow_nan=False,
                         separators=(',', ':')).encode('utf-8')
    if not 0 < len(payload) <= MAX_FRAME:
        raise AppError('PROTOCOL_ERROR', 'Message exceeds frame limit')
    sock.sendall(struct.pack('!I', len(payload)) + payload)

def recv_message(sock):
    size = struct.unpack('!I', recv_exact(sock, 4))[0]
    if not 0 < size <= MAX_FRAME:
        raise AppError('PROTOCOL_ERROR', 'Invalid frame length')
    try:
        value = json.loads(recv_exact(sock, size).decode('utf-8'),
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise AppError('PROTOCOL_ERROR', 'Invalid JSON') from exc
    if not isinstance(value, dict):
        raise AppError('PROTOCOL_ERROR', 'Message must be an object')
    return value
