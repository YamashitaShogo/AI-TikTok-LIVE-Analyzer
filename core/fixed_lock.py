"""Cross-process exclusion for the fixed-observation profile.

One fixed profile (one app-data BASE, hence one capture_fixed and
one webview_profile_fixed) may be written by exactly ONE collector
process at a time, no matter who launched it: Pulse Pro, the
standalone top_viewer.py, another Pulse instance, or a parallel
install sharing the same app-data folder.

Design (the lock is held by the COLLECTOR, not by a launcher):
- A launcher (GUI) can die while its collector keeps running; if the
  launcher held the lock, the profile would look free while data is
  still being written. The collector is the writer, so the collector
  acquires the lock at startup and holds it for its whole life.
- The lock is an OS file lock (msvcrt on Windows, fcntl elsewhere)
  on ``<BASE>/fixed_viewer.lock`` — the same file top_viewer.py has
  always used, so the location stays compatible. The lock STATE is
  the truth, never the file's existence: the file may sit on disk
  forever, and the OS releases the lock automatically when the
  holding process dies, however it dies (requirement: a force-killed
  collector never bricks the profile).
- PID-reuse cannot fool an OS lock, and nobody ever stops a process
  they do not own based on lock data.
- ``fixed_lock_status.json`` next to it is INFORMATIONAL only (which
  target the holder observes, its pid, when it started), always
  corroborated by a lock probe and the collector heartbeat before
  the UI draws conclusions from it.
"""
import json
import os
import sys
import time
from pathlib import Path

try:
    from .observation_profile import BASE
except ImportError:  # direct-script import style
    from observation_profile import BASE

LOCK_FILENAME = 'fixed_viewer.lock'
STATUS_FILENAME = 'fixed_lock_status.json'
CONFLICT_FILENAME = 'fixed_lock_conflict.json'

# Per-process record of lock outcomes, used to protect the owner
# status file: a process whose acquire FAILED for a profile may not
# rewrite that profile's owner information (state held/released).
# Its conflict note goes to a separate file instead. Exclusion
# decisions never depend on either file — the OS lock is the truth.
_HELD_PATHS = {}
_FAILED_PATHS = set()


def lock_path(base=None):
    return Path(base or BASE) / LOCK_FILENAME


def status_path(base=None):
    return Path(base or BASE) / STATUS_FILENAME


def conflict_path(base=None):
    return Path(base or BASE) / CONFLICT_FILENAME


def target_id_from_url(url):
    """'@id' portion of a TikTok LIVE URL ('' when unparsable)."""
    text = str(url or '')
    if '@' not in text:
        return ''
    return text.split('@', 1)[1].split('/', 1)[0].strip()


class ProfileLock:
    """Non-blocking OS file lock for one fixed profile."""

    def __init__(self, base=None):
        self._path = lock_path(base)
        self._handle = None

    @property
    def held(self):
        return self._handle is not None

    def acquire(self):
        if self._handle is not None:
            return True
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            handle = self._path.open('a+b')
            try:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b'0')
                    handle.flush()
                handle.seek(0)
                if sys.platform == 'win32':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                _FAILED_PATHS.add(str(self._path))
                return False
            self._handle = handle
            _HELD_PATHS[str(self._path)] = self
            return True
        except OSError:
            _FAILED_PATHS.add(str(self._path))
            return False

    def release(self):
        handle, self._handle = self._handle, None
        _HELD_PATHS.pop(str(self._path), None)
        if handle is None:
            return
        try:
            if sys.platform == 'win32':
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            handle.close()
        except OSError:
            pass


def probe_locked(base=None):
    """True when some live process currently holds the profile lock.

    This is only a pre-flight check: it briefly acquires and releases
    when free. The collector's own acquire at startup is the atomic
    gate that actually decides between competing launches.
    """
    lock = ProfileLock(base)
    if lock.acquire():
        lock.release()
        return False
    return True


def write_status(state, target_id=None, base=None, pid=None):
    """Record lock state information. Returns the payload, or None
    when the write was refused.

    Protection rules (the OS lock stays the only exclusion truth):
    - 'conflict' notes are written to fixed_lock_conflict.json, NEVER
      to the owner status file, so a competing process that failed to
      acquire cannot clobber the legitimate owner's information.
    - 'held'/'released' writes are refused (None) when THIS process
      previously failed to acquire this profile's lock.
    """
    payload = {
        'state': state,  # 'held' | 'conflict' | 'released'
        'pid': pid if pid is not None else os.getpid(),
        'target_id': target_id or '',
        'updated_at': time.time(),
    }
    if state == 'conflict':
        path = conflict_path(base)
    else:
        if str(lock_path(base)) in _FAILED_PATHS:
            return None
        path = status_path(base)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        tmp.replace(path)
    except OSError:
        pass
    return payload


def read_status(base=None):
    try:
        data = json.loads(status_path(base).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def read_conflict(base=None):
    try:
        data = json.loads(conflict_path(base).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def acquire_profile_lock_or_exit(target_id, base=None):
    """Fail-closed gate for the fixed collector (Phase 4 review).

    Returns the held ProfileLock on success. On ANY failure —
    contention, lock-infra error, or a status write that cannot be
    verified — raises SystemExit so the collector process ends
    BEFORE collecting any data:
    - exit 3: another collector legitimately holds the profile;
    - exit 4: initialization/verification failure.
    """
    lock = ProfileLock(base)
    try:
        acquired = lock.acquire()
    except Exception as exc:
        print(f'固定観測コレクタ: 排他ロックの初期化に失敗したため終了します: {exc!r}',
              flush=True)
        raise SystemExit(4)
    if not acquired:
        write_status('conflict', target_id=target_id, base=base)
        print('固定観測コレクタ: 同じプロファイルの固定観測が既に動作中のため終了します'
              f' (target=@{target_id})', flush=True)
        raise SystemExit(3)
    written = write_status('held', target_id=target_id, base=base)
    verified = read_status(base)
    if (written is None or not verified
            or verified.get('state') != 'held'
            or verified.get('pid') != os.getpid()):
        lock.release()
        print('固定観測コレクタ: ロック所有者情報を検証できなかったため終了します',
              flush=True)
        raise SystemExit(4)
    return lock
