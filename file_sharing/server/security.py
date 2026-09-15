"""PBKDF2 password hashing and portable storage path validation."""
import hashlib
import hmac
import re
import secrets
from common.protocol import AppError

def password_hash(password):
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise AppError('INVALID_INPUT', 'Password must contain 8-128 characters')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000)
    return '600000$' + salt + '$' + digest.hex()

def verify(password, stored):
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        return False
    iterations, salt, digest = stored.split('$')
    actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(iterations))
    return hmac.compare_digest(actual.hex(), digest)

def username(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{2,31}', value):
        raise AppError('INVALID_INPUT', 'Username: 3-32 letters, digits, _ or -; start with a letter')
    return value

def clean_path(value):
    if not isinstance(value, str) or len(value) > 1024:
        raise AppError('INVALID_PATH', 'Invalid resource path')
    if value == '':
        return value
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{p}{i}' for p in ('COM', 'LPT') for i in range(1, 10)}
    for part in value.split('/'):
        if (not part or part in ('.', '..') or len(part) > 120 or part.startswith('.')
                or part.endswith((' ', '.')) or any(ord(c) < 32 or ord(c) > 126 for c in part)
                or any(c in '<>:"\\|?*' for c in part) or part.split('.')[0].upper() in reserved):
            raise AppError('INVALID_PATH', 'Use safe relative paths with / separators; no traversal')
    return value

def physical(root, path):
    clean_path(path)
    target = root
    for part in path.split('/') if path else []:
        target = target / part
        if target.is_symlink():
            raise AppError('INVALID_PATH', 'Symbolic links are not allowed')
    if not target.resolve().is_relative_to(root.resolve()):
        raise AppError('INVALID_PATH', 'Path escapes storage')
    return target
