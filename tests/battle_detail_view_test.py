"""Battle detail view inside the バトル履歴 tab (PR #12).

D1  詳細 opens the detail INSIDE the battles tab (no tab jump),
    showing the clicked battle only.
D2  a finished battle shows 最終確定スコア; an unfinished one
    shows 参考スコア and is never labelled confirmed.
D3  viewer median/peak and sample counts come from the data.
D4  一覧に戻る restores the list and its scroll position.
D5  a display re-render keeps the open battle (auto refresh).
D6  switching the displayed session closes the detail and shows
    that session's battles.
D7  opening another battle never mixes the previous one's data.

Run: python tests/battle_detail_view_test.py  (GUI: needs a display)
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_battle_detail_')
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

CAP = BASE / 'capture_fixed'
DB_PATH = CAP / 'battle_dataset' / 'battles.sqlite3'
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
START, END = NOW - 5000, NOW - 1000


def payload(score, finished=True):
    entry = {"anchor_id": "1", "score": score, "score_known": True,
             "nickname": "mio", "unique_id": "mio__x6"}
    return json.dumps({"mode": "individual", "host_user_id": "1",
                       "host_nickname": "mio", "participants": [entry],
                       "active": not finished})


def battle(bid, first, last, status, score):
    _db.execute("INSERT INTO battles VALUES (?,?,?,?,?,?)",
                ('mio__x6', bid, first, last, status,
                 payload(score, status == 'finished')))


# Ten filler battles so the list overflows and scrolls.
for i in range(10):
    t = START + 100 + i * 300
    battle(100 + i, t, t + 200, 'finished', 100 + i)
# Target A: finished, confirmed 500, with score/viewer series.
battle(9001, START + 3300, START + 3600, 'finished', 500)
for j, (dt, sc) in enumerate(((0, 100), (100, 300), (200, 500))):
    _db.execute("INSERT INTO snapshots VALUES (?,?,?,?,?)",
                ('mio__x6', 9001, START + 3300 + dt, f'fp{j}',
                 payload(sc)))
for dt, viewers in ((0, 10), (100, 20), (200, 30)):
    _db.execute("INSERT INTO viewer_samples VALUES (?,?,?,?,?)",
                ('mio__x6', 9001, START + 3300 + dt, dt, viewers))
# Target B: still active — reference score only.
battle(9002, START + 3900, START + 4200, 'active', 300)
_db.commit()

store = get_runtime(str(CAP)).store
s1 = store.start_session('固定観測', targets=['mio__x6'],
                         profile='capture_fixed', now=START)
store.heartbeat(s1['session_id'], connected=3, now=START + 5)
store.stop_session(s1['session_id'], 'interrupted', now=END)
# A second session with its own battle, for the switch check.
battle(9003, END + 3600, END + 3900, 'finished', 777)
_db.commit()
s2 = store.start_session('固定観測', targets=['mio__x6'],
                         profile='capture_fixed', now=END + 3500)
store.heartbeat(s2['session_id'], connected=3, now=END + 3505)
store.stop_session(s2['session_id'], 'normal', now=END + 4000)

import tkinter.messagebox as messagebox
messagebox.showinfo = lambda *a, **k: None
messagebox.showerror = lambda *a, **k: None
messagebox.askyesno = lambda *a, **k: True

import ui.pages.unattended_report as page_module

root = ctk.CTk()
root.geometry('1500x950')
page = page_module.UnattendedReportPage(root)
page.pack(fill='both', expand=True)


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


def detail_rows():
    rows = []

    def walk(widget):
        if isinstance(widget, ctk.CTkButton) and widget.cget('text') == '詳細':
            rows.append(widget)
        for child in widget.winfo_children():
            walk(child)

    walk(page.battles_scroll)
    return rows


def battle_by_id(bid):
    return next(b for b in page._report['battles'] if b['battle_id'] == bid)


page.show_history_session(s1['session_id'])
check('setup: the report lists all session battles',
      wait_until(lambda: page._report is not None
                 and page._report['session']['session_id'] == s1['session_id']
                 and len(page._report['battles']) == 12))
page.tabs.set('バトル履歴')
pump(0.4)

# ------------------------------------------------------------- D1-D3
page._open_battle(battle_by_id(9001))
pump(0.4)
check('D1a 詳細 keeps the バトル履歴 tab selected',
      page.tabs.get() == 'バトル履歴')
check('D1b the detail view is shown and the list is hidden',
      page._battle_detail_view.winfo_ismapped()
      and not page._battles_list_view.winfo_ismapped())
check('D1c the open battle is the clicked one',
      page._battle_detail_key == ('mio__x6', 9001)
      and '@mio__x6' in page.bd_title.cget('text'))
check('D2a a finished battle shows its confirmed final score',
      '最終確定スコア' in page.bd_score.cget('text')
      and '500' in page.bd_score.cget('text'))
check('D3 the viewer median/peak and sample counts are shown',
      '中央値 20' in page.bd_stats.cget('text')
      and '最大 30' in page.bd_stats.cget('text')
      and 'スコア記録 3 回' in page.bd_stats.cget('text'))
check('D1d the detail charts drew the score series',
      len(page.bd_score_chart.find_all()) > 5)

# ------------------------------------------------------------- D4
canvas = page.battles_scroll._parent_canvas
page._close_battle_detail()
pump(0.3)
page.battles_scroll._parent_canvas.yview_moveto(0.5)
pump(0.3)
frac_before = canvas.yview()[0]
page._open_battle(battle_by_id(9002))
pump(0.3)
page.battle_back_button.invoke()
pump(0.4)
check('D4a back restores the list view',
      page._battles_list_view.winfo_ismapped()
      and not page._battle_detail_view.winfo_ismapped()
      and page._battle_detail_key is None)
check('D4b the list scroll position is restored',
      abs(canvas.yview()[0] - frac_before) < 0.15,
      f'{canvas.yview()[0]} vs {frac_before}')

# ------------------------------------------------------------- D2b/D7
page._open_battle(battle_by_id(9002))
pump(0.3)
check('D2b an unfinished battle shows a reference score only',
      '参考スコア' in page.bd_score.cget('text')
      and '最終確定スコア' not in page.bd_score.cget('text')
      and '確定スコアには含めていません' in page.bd_notes.cget('text'))
check('D7 no data from the previous battle leaks into this detail',
      '9001' not in page.bd_meta.cget('text')
      and '500' not in page.bd_score.cget('text'))

# ------------------------------------------------------------- D5
from core.unattended_report import build_report
fresh = build_report(str(DB_PATH), {'kind': 'session'},
                     session=store.get_session(s1['session_id']),
                     profile='capture_fixed')
page._report = fresh
page._render_report(None, display_only=True)
pump(0.3)
check('D5 a display re-render keeps the open battle detail',
      page._battle_detail_key == ('mio__x6', 9002)
      and page._battle_detail_view.winfo_ismapped()
      and '参考スコア' in page.bd_score.cget('text'))

# ------------------------------------------------------------- D6
page.show_history_session(s2['session_id'])
ok = wait_until(lambda: page._report is not None
                and page._report['session']['session_id'] == s2['session_id'])
pump(0.3)
# show_history_session lands on the 概要 tab by design; go back to
# the battles tab to see which of its two views is active.
page.tabs.set('バトル履歴')
pump(0.3)
check('D6 switching sessions closes the detail onto the new list',
      ok and page._battle_detail_key is None
      and page._battles_list_view.winfo_ismapped()
      and not page._battle_detail_view.winfo_ismapped()
      and [b['battle_id'] for b in page._report['battles']] == [9003])

page.destroy()
pump(0.2)
root.destroy()

print()
if FAILURES:
    print(f'{len(FAILURES)} FAILURES: {FAILURES}')
    sys.exit(1)
print('battle detail view tests passed')
