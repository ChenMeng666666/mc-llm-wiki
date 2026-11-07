"""Cooperative local locking and recoverable UTF-8 file batches (macOS/Linux/Windows)."""
try:
    import fcntl
except ImportError:  # Windows has no fcntl; use msvcrt byte-range locking instead
    fcntl = None
    import msvcrt
import hashlib
import json
import os
import tempfile
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


class WikiError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code, self.data = code, data


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def digest(content):
    return hashlib.sha256(content.encode('utf-8')).hexdigest() if content is not None else None


def path_key(relative):
    # A portable store rejects aliases even on case-sensitive Linux volumes.
    return unicodedata.normalize('NFC', unicodedata.normalize('NFC', relative).casefold())


def safe(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative or '\x00' in relative:
        raise WikiError('invalid_path', 'Expected a relative POSIX path')
    p = PurePosixPath(relative)
    if p.is_absolute() or any(x in ('', '.', '..') for x in relative.split('/')):
        raise WikiError('invalid_path', 'Absolute paths and dot components are forbidden')
    current = root
    for i, part in enumerate(p.parts):
        current = current / part
        if current.is_symlink():
            raise WikiError('symlink', f'Symlink is outside the supported storage contract: {relative}')
        if i < len(p.parts) - 1 and current.exists() and not current.is_dir():
            raise WikiError('path_conflict', f'Parent is a file: {relative}')
    return current


def read(root, relative):
    p = safe(root, relative)
    if not p.exists():
        return None
    # Preserve CRLF: hashes and rollback images describe actual stored bytes.
    with p.open('r', encoding='utf-8', newline='') as stream:
        return stream.read()


def json_read(root, relative, default=None):
    content = read(root, relative)
    return json.loads(content) if content is not None else default


def encode(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.wiki-', dir=path.parent)
    try:
        stream = os.fdopen(fd, 'wb') if isinstance(content, bytes) else os.fdopen(fd, 'w', encoding='utf-8', newline='')
        with stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        try:
            folder = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return  # Windows cannot open a directory for fsync; os.replace is durable enough
        try:
            os.fsync(folder)
        finally:
            os.close(folder)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _flock(stream, write):
    """Non-blocking lock; raises BlockingIOError when another holder exists."""
    if fcntl is not None:
        fcntl.flock(stream.fileno(), (fcntl.LOCK_EX if write else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        return
    stream.seek(0)
    try:
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        raise BlockingIOError('lock held') from None


def _funlock(stream):
    if fcntl is not None:
        return  # fcntl.flock releases on close; msvcrt needs an explicit unlock
    stream.seek(0)
    try:
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


@contextmanager
def locked(root, write=False):
    path = safe(root, 'state/lock')
    if not path.exists():
        raise WikiError('not_initialized', 'Run init first')
    with path.open('r+') as stream:
        try:
            _flock(stream, write)
        except BlockingIOError:
            raise WikiError('busy', 'Another local operation holds the wiki lock') from None
        try:
            yield
        finally:
            _funlock(stream)


def journals(root):
    folder = safe(root, 'state/transactions')
    return [(p, json_read(root, p.relative_to(root).as_posix())) for p in sorted(folder.glob('*.json'))]


def no_pending(root):
    history = [t for _, t in journals(root)]
    pending = [t['id'] for t in history if t['status'] == 'pending']
    if pending:
        raise WikiError('recovery_required', 'Run recover before another mutation', {'transactions': pending})
    return history


def rollback(root, tx):
    # Check the entire batch before restoring anything, preserving intervening edits.
    for c in tx['changes']:
        current = read(root, c['path'])
        if current not in (c['before'], c['after']):
            raise WikiError('recovery_conflict', f'Intervening edit: {c["path"]}')
    for c in reversed(tx['changes']):
        path = safe(root, c['path'])
        if c['before'] is None:
            path.unlink(missing_ok=True)
        else:
            atomic(path, c['before'])


def transact(root, changes, reason, operation='pages'):
    history = no_pending(root)
    seen, prepared = set(), []
    for c in changes:
        key = path_key(c['path'])
        if key in seen:
            raise WikiError('duplicate_path', c['path'])
        seen.add(key)
        before = read(root, c['path'])
        if digest(before) != c['expected_sha256']:
            raise WikiError('version_conflict', f'Re-read and rebase {c["path"]}')
        prepared.append({'path': c['path'], 'before': before, 'after': c['content']})
    for key in seen:
        parts = key.split('/')
        if any('/'.join(parts[:i]) in seen for i in range(1, len(parts))):
            raise WikiError('path_conflict', 'A batch target is the parent file of another target')
    tx = {'id': uuid.uuid4().hex, 'status': 'pending', 'at': now(), 'reason': reason,
          'operation': operation, 'sequence': max((t.get('sequence', 0) for t in history), default=0) + 1,
          'changes': prepared}
    journal = safe(root, f'state/transactions/{tx["id"]}.json')
    atomic(journal, encode(tx))
    try:
        for c in prepared:
            atomic(safe(root, c['path']), c['after'])
        tx['status'] = 'committed'
        atomic(journal, encode(tx))
    except BaseException:
        rollback(root, tx)
        tx['status'] = 'rolled_back'
        atomic(journal, encode(tx))
        raise
    return tx['id']
