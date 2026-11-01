"""Responsive layout tests for the streaming report page (PR #12).

The 観測の状態 card used to place the info column and the three
action buttons side by side unconditionally: at Windows 150%
scaling (and in small windows at 125%) the info column's requested
width squeezed the buttons off the right edge, and the long
collection-status text was clipped.

L1  Wide window: buttons beside the info, fully inside the page.
L2  Narrow window: buttons move below the info, still fully inside.
L3  Very narrow: the buttons themselves stack full-width.
L4  Widening again restores the side-by-side layout (no oscillation
    damage, no lost widgets).
L5  A long collection-status text wraps inside its own row instead
    of running off the right edge.
L6  The report auto-refresh still works after the relayouts, and
    the start/stop/report buttons keep their commands.

Run: python tests/report_layout_test.py  (GUI: needs a display)
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_report_layout_')
os.environ['LOCALAPPDATA'] = _TMP  # must precede core imports (BASE)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pyaudiowpatch  # noqa: F401
except ImportError:
    sys.modules['pyaudiowpatch'] = types.ModuleType('pyaudiowpatch')

import customtkinter as ctk

from core.observation_sessions import get_runtime
from core.observation_profile import BASE

CAP_FIXED = BASE / 'capture_fixed'
DB_PATH = CAP_FIXED / 'battle_dataset' / 'battles.sqlite3'
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_db = sqlite3.connect(DB_PATH)
_db.executescript("""
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
""")
NOW = time.time()
_entry = {"anchor_id": "1", "score": 500, "score_known": True,
          "nickname": "mio", "unique_id": "mio"}
_payload = json.dumps({"mode": "individual", "host_user_id": "1",
                       "host_nickname": "mio", "participants": [_entry],
                       "active": False,
                       "start_time_ms": int((NOW - 600) * 1000)})
_db.execute("INSERT INTO battles VALUES (?,?,?,?,?,?)",
            ('mio', 8001, NOW - 600, NOW - 300, 'finished', _payload))
_db.commit()
_db.close()

store = get_runtime(str(CAP_FIXED)).store
s1 = store.start_session('固定観測', targets=['mio'], profile='capture_fixed',
                         now=NOW - 900)
store.stop_session(s1['session_id'], 'normal', now=NOW - 60)

passed = failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f'PASS {name}')
    else:
        failed += 1
        print(f'FAIL {name}')


root = ctk.CTk()


def pump(seconds=0.35):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def set_width(width):
    root.geometry(f'{width}x820')
    pump(0.45)
    root.update_idletasks()


import ui.pages.unattended_report as page_module

page_module.messagebox.showerror = lambda *a, **k: None
page_module.messagebox.showwarning = lambda *a, **k: None
page_module.messagebox.showinfo = lambda *a, **k: None

page = page_module.UnattendedReportPage(root)
page.pack(fill='both', expand=True)
buttons = [page.start_button, page.stop_button, page.show_report_button]


def inside(widget):
    return (widget.winfo_rootx() >= page.winfo_rootx() - 1
            and widget.winfo_rootx() + widget.winfo_width()
            <= page.winfo_rootx() + page.winfo_width() + 1
            and widget.winfo_width() >= widget.winfo_reqwidth() - 2)


def dump_geometry(context):
    """Failure diagnostics: real clipping vs measurement error is
    decided from these numbers, not from the pass/fail bit alone."""
    try:
        scaling = ctk.ScalingTracker.get_widget_scaling(root)
    except Exception:
        scaling = '?'
    print(f'  [diag {context}] mode={page._status_mode} '
          f'stacked={page._actions_stacked} widget_scaling={scaling} '
          f'page_rootx={page.winfo_rootx()} page_w={page.winfo_width()} '
          f'layout_w={page._status_layout.winfo_width()} '
          f'info_req={page._status_info.winfo_reqwidth()} '
          f'actions_w={page._status_actions.winfo_width()} '
          f'actions_req={page._status_actions.winfo_reqwidth()}')
    for name, b in zip(('start', 'stop', 'show'), buttons):
        print(f'  [diag {context}] {name}: rootx={b.winfo_rootx()} '
              f'w={b.winfo_width()} req={b.winfo_reqwidth()} '
              f'right={b.winfo_rootx() + b.winfo_width()} '
              f'page_right={page.winfo_rootx() + page.winfo_width()}')


def buttons_inside(context):
    ok = all(inside(b) for b in buttons)
    if not ok:
        dump_geometry(context)
    return ok


# ---------------------------------------------------------------- L1
set_width(1500)
check('L1a wide window uses the side-by-side layout',
      page._status_mode == 'h')
check('L1b all three action buttons are fully inside the page',
      buttons_inside('L1b'))
check('L1c actions sit beside the info, not below it',
      page._status_actions.winfo_rootx()
      >= page._status_info.winfo_rootx() + page._status_info.winfo_width() - 2
      and page._status_actions.winfo_rooty()
      < page._status_info.winfo_rooty() + page._status_info.winfo_height())

# ---------------------------------------------------------------- L2
set_width(780)
check('L2a narrow window switches to the stacked layout',
      page._status_mode == 'v')
check('L2b all three action buttons are still fully inside',
      buttons_inside('L2b'))
check('L2c actions are below the info in the stacked layout',
      page._status_actions.winfo_rooty()
      >= page._status_info.winfo_rooty() + page._status_info.winfo_height() - 2)

# ---------------------------------------------------------------- L3
set_width(470)
check('L3a very narrow window stacks the buttons themselves',
      page._actions_stacked is True)
check('L3b stacked buttons are fully inside and full-width',
      buttons_inside('L3b')
      and all(b.winfo_width() >= page._status_actions.winfo_width() - 24
              for b in buttons))
check('L3c stacked buttons run top to bottom in order',
      buttons[0].winfo_rooty() < buttons[1].winfo_rooty()
      < buttons[2].winfo_rooty())

# ---------------------------------------------------------------- L4
set_width(1500)
check('L4a widening restores the side-by-side layout',
      page._status_mode == 'h' and page._actions_stacked is False)
check('L4b buttons are fully inside again after the round trip',
      buttons_inside('L4b'))

# ---------------------------------------------------------------- L5
set_width(780)
page.collector_label.configure(
    text='固定観測コレクタが正常に収集できていません（接続エラーが発生したため再試行しています）。'
         'セッションだけが「観測中」の状態になっています。 ／ 最終データ 2026-11-02 01:23:45')
pump(0.3)
check('L5a the long collection status stays inside the page',
      page.collector_label.winfo_rootx() + page.collector_label.winfo_width()
      <= page.winfo_rootx() + page.winfo_width() + 1)
check('L5b the long collection status wraps to multiple lines',
      page.collector_label.winfo_height() >= 34)

# ---------------------------------------------------------------- L6
deadline = time.time() + 10
while time.time() < deadline and page._report is None:
    root.update()
    time.sleep(0.02)
check('L6a report auto-refresh still displays after relayouts',
      page._report is not None
      and page._report['summary']['record_count'] == 1)
check('L6b the action buttons kept their commands',
      all(b.cget('command') for b in buttons))
page.destroy()
pump(0.2)

print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
