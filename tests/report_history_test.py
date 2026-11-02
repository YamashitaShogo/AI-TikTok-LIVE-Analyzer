"""Streaming-history tab tests for the report page (PR #12).

H1-H5  core: session_summaries mirrors build_report's counting
       (window, targets, confirmed-end + known score, battles that
       end after the window never count as confirmed); a missing
       database reads as unknown (None), never as zero;
       list_sessions_basic returns rows without event lists.
H6-H7  the 配信履歴 tab exists and lists sessions newest first
       with start time, targets, state, duration, battle counts and
       the max confirmed score.
H8     clicking a history row displays that session read-only:
       no report file is written and report_state is untouched.
H9     the auto refresh keeps re-aggregating the SELECTED past
       session — it never jumps back to the latest on its own.
H10    the viewing label names the displayed history (date/target).
H11    streamer and date filters narrow the list; clearing restores.
H12    pagination: 20 per page, older sessions stay reachable.
H13    "no history yet" and "history failed to load" are distinct.

Run: python tests/report_history_test.py  (GUI: needs a display)
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_report_history_')
os.environ['LOCALAPPDATA'] = _TMP  # must precede core imports (BASE)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pyaudiowpatch  # noqa: F401
except ImportError:
    sys.modules['pyaudiowpatch'] = types.ModuleType('pyaudiowpatch')

import customtkinter as ctk

from core.observation_sessions import format_jst, get_runtime
from core.observation_profile import BASE
from core.unattended_report import session_summaries

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


def payload(score, finished=True):
    entry = {"anchor_id": "1", "score": score, "score_known": True,
             "nickname": "host", "unique_id": "host"}
    return json.dumps({"mode": "individual", "host_user_id": "1",
                       "host_nickname": "host", "participants": [entry],
                       "active": not finished})


def battle(uid, bid, first, last, status, score):
    _db.execute("INSERT INTO battles VALUES (?,?,?,?,?,?)",
                (uid, bid, first, last, status, payload(score, status == 'finished')))


# Non-overlapping session windows, oldest first.
# S_old window: NOW-14000 .. NOW-10000 (mio)
battle('mio', 8001, NOW - 13800, NOW - 11000, 'finished', 500)  # confirmed
battle('mio', 8002, NOW - 13700, NOW - 9500, 'finished', 999)   # ends after window
# S_int window: NOW-9000 .. NOW-8000 (mio, interrupted)
battle('mio', 8003, NOW - 8800, NOW - 8300, 'active', 300)      # never confirmed
# S_alice window: NOW-7000 .. NOW-6000 (alice)
battle('alice', 8004, NOW - 6800, NOW - 6300, 'finished', 700)
# S_latest window: NOW-3000 .. NOW-2000 (mio)
battle('mio', 8005, NOW - 2800, NOW - 2300, 'active', 300)
_db.commit()
_db.close()

store = get_runtime(str(CAP_FIXED)).store


def make_session(targets, start, end, kind='normal'):
    s = store.start_session('固定観測', targets=targets,
                            profile='capture_fixed', now=start)
    store.stop_session(s['session_id'], kind, now=end)
    return s['session_id']


S_OLD = make_session(['mio'], NOW - 14000, NOW - 10000)
S_INT = make_session(['mio'], NOW - 9000, NOW - 8000, kind='interrupted')
S_ALICE = make_session(['alice'], NOW - 7000, NOW - 6000)
S_LATEST = make_session(['mio'], NOW - 3000, NOW - 2000)

passed = failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f'PASS {name}')
    else:
        failed += 1
        print(f'FAIL {name}')


# ---------------------------------------------------------------- core
basic = store.list_sessions_basic(limit=1000)
check('H5a list_sessions_basic returns all sessions newest first',
      [s['session_id'] for s in basic] == [S_LATEST, S_ALICE, S_INT, S_OLD])
check('H5b basic rows carry no event lists', all(s['events'] == [] for s in basic))

summaries = session_summaries(DB_PATH, basic, now=NOW)
old = summaries[S_OLD]
check('H1 the old session counts its in-window battles',
      old['record_count'] == 2)
check('H2 a battle ending after the window is not a confirmed final',
      old['score_known_battles'] == 1 and old['final_score_max'] == 500)
check('H3 an interrupted session keeps its fetched battles, unconfirmed',
      summaries[S_INT]['record_count'] == 1
      and summaries[S_INT]['score_known_battles'] == 0
      and summaries[S_INT]['final_score_max'] is None)
check('H4a the alice session aggregates independently',
      summaries[S_ALICE]['record_count'] == 1
      and summaries[S_ALICE]['final_score_max'] == 700)
check('H4b missing database reads as unknown, never zero',
      all(v is None for v in
          session_summaries(BASE / 'nope' / 'battles.sqlite3', basic).values()))

# ---------------------------------------------------------------- page
root = ctk.CTk()


def history_cards():
    return [c for c in page.history_list.winfo_children()
            if isinstance(c, ctk.CTkFrame)]


def card_text(card):
    texts = []

    def walk(widget):
        if isinstance(widget, ctk.CTkLabel):
            texts.append(widget.cget('text'))
        for child in widget.winfo_children():
            walk(child)

    walk(card)
    return ' '.join(texts)


def pump(seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


import ui.pages.unattended_report as page_module

page_module.messagebox.showerror = lambda *a, **k: None
page_module.messagebox.showwarning = lambda *a, **k: None
page_module.messagebox.showinfo = lambda *a, **k: None

page = page_module.UnattendedReportPage(root)
page.pack(fill='both', expand=True)
root.geometry('1500x900')

deadline = time.time() + 15
while time.time() < deadline and len(page._history_sessions) < 4:
    root.update()
    time.sleep(0.02)

check('H6a history is an always-visible panel, not a tab',
      '配信履歴' not in page.tabs._tab_dict
      and set(page.tabs._tab_dict) == {'概要', 'バトル履歴', 'AI改善提案',
                                       'レポート出力', '詳細設定'}
      and hasattr(page, 'history_list'))
pump(0.3)
check('H6b the detail tabs open on 概要 by default',
      page.tabs.get() == '概要')
cards = history_cards()
check('H7a one card per session, newest first', len(cards) == 4
      and S_LATEST in page._history_sessions[0]['session_id'])
first_text = card_text(cards[0]) if cards else ''
check('H7b cards show date, target, counts and the confirmed max',
      '記録バトル 1件' in first_text and '最大確認スコア 未取得' in first_text)
old_text = card_text(cards[3]) if len(cards) > 3 else ''
check('H7c the old card shows its confirmed score, not the clipped one',
      '最大確認スコア 500' in old_text and '確定 1件' in old_text
      and '正常終了' in old_text)

# ---------------------------------------------------------------- click
reports_dir = CAP_FIXED / 'observation_report' / 'reports'
before_files = set(reports_dir.glob('*.json')) if reports_dir.exists() else set()
# CTkFrame.bind registers on the frame's internal canvas, so the
# synthetic click is generated there (a real mouse click lands on
# the same canvas).
cards[3]._canvas.event_generate('<Button-1>', x=10, y=10)
deadline = time.time() + 15
while time.time() < deadline:
    root.update()
    time.sleep(0.02)
    if (page._report or {}).get('session', {}) .get('session_id') == S_OLD:
        break
check('H8a clicking a history row displays that session',
      (page._report or {}).get('session', {}).get('session_id') == S_OLD
      and page._report['summary']['record_count'] == 2)
check('H8b the click switches to the overview tab', page.tabs.get() == '概要')
after_files = set(reports_dir.glob('*.json')) if reports_dir.exists() else set()
check('H8c viewing writes no report file and marks nothing generated',
      after_files == before_files
      and store.get_session(S_OLD)['report_state'] == 'none')
check('H10 the detail header names the displayed history',
      '過去の配信を表示中' in page.history_viewing_label.cget('text')
      and format_jst(NOW - 14000)[:10]
      in page.detail_title_label.cget('text')
      and '@mio' in page.detail_title_label.cget('text'))

page._auto_refresh()
pump(1.2)
deadline = time.time() + 10
while time.time() < deadline and page._display_inflight is not None:
    root.update()
    time.sleep(0.02)
pump(0.5)
check('H9 auto refresh never steals the view back to the latest',
      page._display_request is not None
      and page._display_request.get('session_id') == S_OLD
      and page._display_request.get('auto') is False
      and (page._report or {}).get('session', {}).get('session_id') == S_OLD)

page.show_latest_display()
pump(0.6)
check('H9b "show latest" returns to following the latest session',
      page._display_request is None
      or page._display_request.get('auto') is True)

# ---------------------------------------------------------------- filter
page.history_filter_entry.insert(0, 'alice')
page.apply_history_filter()
pump(0.2)
check('H11a the streamer filter narrows to matching sessions',
      [s['session_id'] for s in page._filtered_history()] == [S_ALICE])
check('H11b the filtered list renders one card',
      len(history_cards()) == 1)
page.clear_history_filter()
page.history_date_entry.insert(0, '1999-01-01')
page.apply_history_filter()
pump(0.2)
check('H11c a date with no sessions shows the no-match note',
      page._filtered_history() == []
      and '条件に一致する履歴がありません' in page.history_note.cget('text'))
page.clear_history_filter()
pump(0.2)
check('H11d clearing restores the full list',
      len(page._filtered_history()) == 4)

# ------------------------------------------------------------- paging
for i in range(25):
    make_session(['mio'], NOW - 90000 - i * 100, NOW - 89900 - i * 100)
# Wait for the async load to actually land, re-asking whenever the
# loader is idle: refresh() during an in-flight load is recorded as
# pending by the page, and this loop must not mistake "still
# loading" for "loaded" on a slow machine.
db_total = len(store.list_sessions_basic(limit=1000))
page.refresh()
deadline = time.time() + 60
while time.time() < deadline and len(page._history_sessions) < db_total:
    root.update()
    if not page._busy:
        page.refresh()
    time.sleep(0.02)
pump(0.3)
page._history_signature = None
page._render_history()
print(f'  [diag H12] db_sessions={db_total} '
      f'page_history={len(page._history_sessions)} '
      f'filtered={len(page._filtered_history())} '
      f'cards={len(history_cards())} page_index={page._history_page} '
      f'label={page.history_page_label.cget("text")!r} busy={page._busy}')
check('H12a the first page shows 20 cards with a page indicator',
      len(history_cards()) == 20
      and '1 / 2 ページ（全29件）' in page.history_page_label.cget('text'))
page.history_next_page()
check('H12b the second page reaches the older sessions',
      len(history_cards()) == 9)
page.history_prev_page()

# ------------------------------------------------------- empty vs error
saved_sessions, saved_error = page._history_sessions, page._history_error
page._history_sessions, page._history_error = [], None
page._history_signature = None
page._render_history()
check('H13a zero history says so plainly',
      'まだ観測履歴がありません' in page.history_note.cget('text'))
page._history_error = '読み込みテスト用エラー'
page._history_signature = None
page._render_history()
check('H13b a load failure is shown as an error, not as empty',
      '読み込みに失敗しました' in page.history_note.cget('text'))
page._history_sessions, page._history_error = saved_sessions, saved_error

page.destroy()
pump(0.2)

print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
