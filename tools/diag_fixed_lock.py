"""Diagnostic for the fixed-lock parent/child status mismatch.

Reproduces the review test's V1 arrangement (a child process takes
the profile lock through the fail-closed gate and reports 'held'
status; the parent then reads the status back) and prints every
value both sides see, so the exact divergence is visible:

- the child's own pid / BASE / status path (printed by the child
  BEFORE 'HELD', so the parent's first readline is NOT 'HELD' --
  this script reads lines until HELD on purpose),
- the parent's Popen pid / status path / read_status() result,
- the raw status file contents.

ASCII-only output on purpose (console encoding safety).
Run:  .venv-regression\Scripts\python.exe tools\diag_fixed_lock.py
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_fixed_diag_')
os.environ['LOCALAPPDATA'] = _TMP  # must precede core imports (BASE)
ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, ROOT)

from core import fixed_lock  # noqa: E402

CHILD = Path(_TMP) / 'diag_child.py'
CHILD.write_text(
    "import os, sys, time\n"
    f"sys.path.insert(0, r'{ROOT}')\n"
    "from core import fixed_lock\n"
    "from core.observation_profile import BASE\n"
    "print('CHILD pid=%d' % os.getpid(), flush=True)\n"
    "print('CHILD base=%s' % BASE, flush=True)\n"
    "print('CHILD status_path=%s' % fixed_lock.status_path(), flush=True)\n"
    "lock = fixed_lock.acquire_profile_lock_or_exit('owner')\n"
    "print('HELD', flush=True)\n"
    "time.sleep(30)\n", encoding='utf-8')


def run(label, env):
    print(f'--- {label} ---')
    proc = subprocess.Popen([sys.executable, str(CHILD)],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env)
    for _ in range(6):
        line = proc.stdout.readline()
        print('PIPE:', line.rstrip())
        if line.startswith('HELD'):
            break
    print('PARENT popen_pid=%d' % proc.pid)
    print('PARENT status_path=%s' % fixed_lock.status_path())
    status = fixed_lock.read_status()
    print('PARENT read_status=%r' % (status,))
    try:
        print('PARENT raw_file=%s'
              % fixed_lock.status_path().read_text(encoding='utf-8'))
    except OSError as exc:
        print('PARENT raw_file read failed: %r' % (exc,))
    print('PID_MATCH:', bool(status) and status.get('pid') == proc.pid)
    proc.kill()
    proc.wait(timeout=5)
    for _ in range(50):
        if not fixed_lock.probe_locked():
            break
        time.sleep(0.1)


run('A inherited env (review-test style)', None)
run('B explicit env=dict(os.environ) (controller style)', dict(os.environ))
print('DIAG DONE')
