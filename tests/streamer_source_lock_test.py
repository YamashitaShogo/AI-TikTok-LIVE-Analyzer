"""Streamer workspace = fixed-observation only (PR #12).

W1  the streamer page starts on the capture_fixed source.
W2  the source/mode selectors are read-only in streamer mode and
    the read-only note names the fixed observation.
W3  a programmatic switch to 通常観測 is refused in streamer mode.
W4  a programmatic switch to TopWatch is refused in streamer mode.
W5  the developer workspace can still switch between all sources.
W6  developer(TopWatch) -> streamer restores the fixed source.
W7  after the restore, no TopWatch session/report remains on screen.
W8  a stale load result (older generation) never overwrites the
    screen, while a current-generation result is applied.
W9  the streamer history lists capture_fixed sessions only.
W10 the other sources' SQLite files are untouched by streamer use.

Run: python tests/streamer_source_lock_test.py  (GUI: needs a display)
"""
import hashlib
import os
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_streamer_lock_')
os.environ['LOCALAPPDATA'] = _TMP  # must precede core imports (BASE)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pyaudiowpatch  # noqa: F401
except ImportError:
    sys.modules['pyaudiowpatch'] = types.ModuleType('pyaudiowpatch')

import customtkinter as ctk

FAILURES = []


def check(name, condition, detail=''):
    print(('PASS ' if condition else 'FAIL ') + name
          + (f'  [{detail}]' if detail and not condition else ''))
    if not condition:
        FAILURES.append(name)


from core.observation_profile import BASE
from core.observation_sessions import get_runtime
from core.settings import Settings
from core.workspace_manager import WorkspaceManager

NOW = time.time()
SCHEMA = """
CREATE TABLE battles (unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
    first_seen REAL NOT NULL, last_seen REAL NOT NULL, status TEXT NOT NULL,
    payload TEXT NOT NULL, PRIMARY KEY(unique_id, battle_id));
CREATE TABLE snapshots (unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
    received_at REAL NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
    UNIQUE(unique_id, battle_id, fingerprint));
CREATE TABLE comments (unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
    received_at REAL NOT NULL, username TEXT NOT NULL, comment TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE);
CREATE TABLE excluded_battles (unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
    reason TEXT NOT NULL, excluded_at REAL NOT NULL, PRIMARY KEY(unique_id, battle_id));
CREATE TABLE viewer_samples (unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
    received_at REAL NOT NULL, elapsed_seconds REAL, viewer_count INTEGER NOT NULL,
    PRIMARY KEY(unique_id, battle_id, received_at));
"""


def make_battle_db(capture_dir):
    path = Path(capture_dir) / 'battle_dataset' / 'battles.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    return path


def seed_session(capture_dir, mode, targets, profile, start, end,
                 end_kind='interrupted'):
    store = get_runtime(str(capture_dir)).store
    session = store.start_session(mode, targets=targets, profile=profile,
                                  now=start)
    store.heartbeat(session['session_id'], connected=1, now=start + 5)
    store.stop_session(session['session_id'], end_kind, now=end)
    return session['session_id']


FIXED = BASE / 'capture_fixed'
NORMAL = BASE / 'capture'
TW_DIR = (BASE / 'top_watch' / 'tw_user' / 'AI-TikTok-LIVE-Analyzer'
          / 'capture_fixed')
for folder in (FIXED, NORMAL, TW_DIR):
    make_battle_db(folder)

fixed_ids = [
    seed_session(FIXED, '固定観測', ['mio__x6'], 'capture_fixed',
                 NOW - 3000, NOW - 2900),
    seed_session(FIXED, '固定観測', ['mio__x6'], 'capture_fixed',
                 NOW - 2000, NOW - 1900),
]
normal_id = seed_session(NORMAL, 'Battle Hunter', ['someone'], 'capture',
                         NOW - 2500, NOW - 2400)
tw_id = seed_session(TW_DIR, '固定観測', ['tw_user'], 'capture_fixed',
                     NOW - 1500, NOW - 1400)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_files(folder):
    return [Path(folder) / 'battle_dataset' / 'battles.sqlite3',
            Path(folder) / 'observation_report' / 'sessions.sqlite3']


other_before = {p: digest(p) for group in (NORMAL, TW_DIR)
                for p in source_files(group) if p.exists()}

import tkinter.messagebox as messagebox
messagebox.showinfo = lambda *a, **k: None
messagebox.showerror = lambda *a, **k: None
messagebox.askyesno = lambda *a, **k: True

import ui.pages.unattended_report as page_module

root = ctk.CTk()
root.geometry('1500x950')


def pump(seconds=0.25):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def wait_until(predicate, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        root.update()
        if predicate():
            return True
        time.sleep(0.03)
    return predicate()


# ---------------------------------------------------------------- W1-W4
page = page_module.UnattendedReportPage(root)
page.pack(fill='both', expand=True)
check('W1 the streamer page starts on capture_fixed',
      page._source is not None
      and page._source['key'] == 'capture_fixed')
check('W2a the source selector is disabled in streamer mode',
      str(page.source_menu.cget('state')) == 'disabled'
      and page.source_menu.cget('values') == ['固定観測']
      and page.source_menu.get() == '固定観測')
check('W2b the mode selector is disabled and the note names the lock',
      str(page.mode_menu.cget('state')) == 'disabled'
      and page.source_note is not None
      and '固定観測（自分のTikTok LIVE）' in page.source_note.cget('text'))
tw_label = next(s['label'] for s in page._sources
                if s['key'].startswith('topwatch:'))
for label, name in (('通常観測', 'W3'), (tw_label, 'W4')):
    page.source_menu.set(label)
    page.change_source()
    check(f'{name} a switch to {label} is refused in streamer mode',
          page._source['key'] == 'capture_fixed'
          and page.source_menu.get() == '固定観測')
    page.source_menu.set('固定観測')  # disabled menu kept the refused value

# ---------------------------------------------------------------- W9
check('W9 the streamer history lists capture_fixed sessions only',
      wait_until(lambda: len(page._history_sessions) == len(fixed_ids))
      and {s['session_id'] for s in page._history_sessions}
      == set(fixed_ids))

# ---------------------------------------------------------------- W8
fixed_sessions = get_runtime(str(FIXED)).store.list_sessions(limit=50)
marker_before = list(page._sessions)
page._queue.put(('sessions', page._load_gen - 1,
                 [dict(fixed_sessions[0], session_id='STALE-MARKER')], []))
page._queue.put(('history', page._load_gen - 1,
                 [dict(fixed_sessions[0], session_id='STALE-MARKER')],
                 {}, None))
page._pump()
check('W8a stale load results are dropped',
      page._sessions == marker_before
      and all(s['session_id'] != 'STALE-MARKER'
              for s in page._history_sessions))
page._queue.put(('sessions', page._load_gen, fixed_sessions, []))
page._pump()
check('W8b a current-generation result is applied',
      [s['session_id'] for s in page._sessions]
      == [s['session_id'] for s in fixed_sessions])

# ---------------------------------------------------------------- W10
check('W10 the other sources files are untouched by streamer use',
      all(digest(p) == h for p, h in other_before.items()))

# ---------------------------------------------------------------- W5-W7
page.destroy()
pump(0.2)
Settings.update({'developer_mode_enabled': True,
                 'workspace_mode': 'developer'})
page2 = page_module.UnattendedReportPage(root)
page2.pack(fill='both', expand=True)
check('W5a the developer source selector is enabled with all sources',
      str(page2.source_menu.cget('state')) == 'normal'
      and '通常観測' in page2.source_menu.cget('values')
      and tw_label in page2.source_menu.cget('values'))
page2.source_menu.set('通常観測')
page2.change_source()
check('W5b the developer workspace can switch to normal observation',
      page2._source['key'] == 'capture')
page2.source_menu.set(tw_label)
page2.change_source()
check('W5c the developer workspace can switch to TopWatch',
      page2._source['key'].startswith('topwatch:'))
check('W6a the TopWatch history loads in developer mode',
      wait_until(lambda: [s['session_id'] for s in page2._history_sessions]
                 == [tw_id]))
page2.destroy()
pump(0.2)
WorkspaceManager().set_mode('streamer')
page3 = page_module.UnattendedReportPage(root)
page3.pack(fill='both', expand=True)
check('W6b back in streamer mode the source is fixed again',
      page3._source['key'] == 'capture_fixed')
check('W7a no TopWatch data remains: history is the fixed source only',
      wait_until(lambda: len(page3._history_sessions) == len(fixed_ids))
      and {s['session_id'] for s in page3._history_sessions}
      == set(fixed_ids))
check('W7b the displayed report belongs to a fixed session',
      wait_until(lambda: page3._report is not None)
      and page3._report['session']['session_id'] in set(fixed_ids))
page3.destroy()
pump(0.2)
root.destroy()

print()
if FAILURES:
    print(f'{len(FAILURES)} FAILURES: {FAILURES}')
    sys.exit(1)
print('streamer source lock tests passed')
