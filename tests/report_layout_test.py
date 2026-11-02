"""Responsive layout tests for the redesigned report page (PR #12).

Structure under test: the status card's fields re-flow between
3/2/1 grid columns and its action row (own row, never beside the
fields) stacks only on very narrow windows; the main area is a
two-pane split (history left, detail right) that collapses to a
vertical stack on narrow windows. At every CTk scaling the three
action buttons must stay fully inside the page at full width —
the original 125%/150% failure was real clipping, so these checks
measure geometry, and dump it on failure.

G1  Wide: buttons in one row inside the page, primary rightmost;
    main area side by side.
G2  Narrow: buttons still inside; fields re-flow; main stacks.
G3  Very narrow: the buttons themselves stack (primary first).
G4  Widening again restores the row and the side-by-side split.
G5  A long collection-status text wraps instead of clipping.
G6  The report auto-refresh still works after the relayouts, and
    the buttons keep their commands.

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
    try:
        scaling = ctk.ScalingTracker.get_widget_scaling(root)
    except Exception:
        scaling = '?'
    print(f'  [diag {context}] cols={page._status_cols} '
          f'stacked={page._actions_stacked} main={page._main_mode} '
          f'widget_scaling={scaling} page_w={page.winfo_width()}')
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


# ---------------------------------------------------------------- G1
set_width(1500)
check('G1a wide window keeps the action row in one row',
      page._actions_stacked is False)
check('G1b all three action buttons are fully inside the page',
      buttons_inside('G1b'))
check('G1c the primary action (レポート出力) sits rightmost',
      page.show_report_button.winfo_rootx() > page.stop_button.winfo_rootx()
      > page.start_button.winfo_rootx())
check('G1d the main area is side by side (history left of detail)',
      page._main_mode == 'side'
      and page._history_panel.winfo_rootx() + page._history_panel.winfo_width()
      <= page._detail_panel.winfo_rootx() + 2)
check('G1e the status fields are actually placed (gridded + mapped)',
      all(b.winfo_ismapped() and b.winfo_height() > 10
          for b in page._field_blocks)
      and page.target_label.winfo_ismapped()
      and page.account_entry.winfo_ismapped())
check('G1f history cards keep a natural card height (no inflation)',
      # ~105 logical px of content; the bound scales with the DPI
      # factor — what it guards against is the 200px phantom height
      # an empty CTkFrame requests by default.
      all(c.winfo_height()
          < 130 * (ctk.ScalingTracker.get_widget_scaling(root) or 1.0)
          for c in page._history_cards.values()))

# ---------------------------------------------------------------- G2
set_width(780)
check('G2a narrow window still shows all buttons fully inside',
      buttons_inside('G2a'))
check('G2b the status fields re-flow to fewer columns',
      page._status_cols in (1, 2))
check('G2c the main area stacks (detail below history)',
      page._main_mode == 'stack'
      and page._detail_panel.winfo_rooty()
      >= page._history_panel.winfo_rooty()
      + page._history_panel.winfo_height() - 2)

# ---------------------------------------------------------------- G3
set_width(470)
check('G3a very narrow window stacks the buttons themselves',
      page._actions_stacked is True)
check('G3b stacked buttons are fully inside the page',
      buttons_inside('G3b'))
check('G3c the primary action leads the stack',
      page.show_report_button.winfo_rooty() < page.start_button.winfo_rooty()
      < page.stop_button.winfo_rooty())

# ---------------------------------------------------------------- G4
set_width(1500)
check('G4a widening restores the action row and the split',
      page._actions_stacked is False and page._main_mode == 'side')
check('G4b buttons are fully inside again after the round trip',
      buttons_inside('G4b'))

# ---------------------------------------------------------------- G5
set_width(780)
_LONG_STATUS = ('固定観測コレクタが正常に収集できていません（接続エラーが発生したため再試行しています）。'
                'セッションだけが「観測中」の状態になっています。 ／ 最終データ 2026-11-02 01:23:45')
page.collector_label.configure(text=_LONG_STATUS)
pump(0.3)
if '正常に収集できていません' not in page.collector_label.cget('text'):
    # The periodic health refresh overwrote the label mid-measure;
    # set the long text once more and measure on idle layout.
    page.collector_label.configure(text=_LONG_STATUS)
    root.update_idletasks()
check('G5a the long collection status stays inside the page',
      page.collector_label.winfo_rootx() + page.collector_label.winfo_width()
      <= page.winfo_rootx() + page.winfo_width() + 1)
check('G5b the long collection status wraps to multiple lines',
      # reqheight is the wrapped text's own measure (the actual
      # height differs by CTk's fixed internal padding; the
      # no-clipping property itself is covered by G5a).
      page.collector_label.winfo_reqheight() >= 34)

# ---------------------------------------------------------------- G6
set_width(1500)
deadline = time.time() + 10
while time.time() < deadline and page._report is None:
    root.update()
    time.sleep(0.02)
check('G6a report auto-refresh still displays after relayouts',
      page._report is not None
      and page._report['summary']['record_count'] == 1)
check('G6b the action buttons kept their commands',
      all(b.cget('command') for b in buttons))
# ---------------------------------------------------------------- G9
# Stack mode must keep BOTH panes usable — not merely on screen:
# the history list needs a real viewport (>= ~80 logical px, about
# two thirds of a card, scrollable for the rest) and the detail
# pane a real area, fully inside the page. (At 150% the side/stack
# decision and the stack split used to mix physical and logical
# units: a maximised window stacked, the history panel took a
# floor value in the wrong unit and the detail row collapsed.)
_SCALING = ctk.ScalingTracker.get_widget_scaling(root) or 1.0


def _logical(px):
    return px / _SCALING


def set_size(width, height):
    root.geometry(f'{width}x{height}')
    pump(0.5)


_first_sid = next(iter(page._history_cards))
page.show_history_session(_first_sid)
_deadline = time.time() + 30
while time.time() < _deadline and not (
        page._report is not None
        and page._report['session']['session_id'] == _first_sid):
    pump(0.1)
_canvas = page.history_list._parent_canvas
set_size(900, 1000)
check('G9a a narrow window stacks the main area', page._main_mode == 'stack')
check('G9b the stacked history list keeps a usable viewport',
      _logical(_canvas.winfo_height()) >= 80)
check('G9c the stacked detail pane keeps a usable area inside the page',
      _logical(page._detail_panel.winfo_height()) >= 150
      and page._detail_panel.winfo_rooty()
      + page._detail_panel.winfo_height()
      <= page.winfo_rooty() + page.winfo_height() + 2)
_card0 = page._history_cards[_first_sid]
_rel_top = _card0.winfo_rooty() - _canvas.winfo_rooty()
check('G9d the first history card is (at least partly) in the viewport',
      -2 <= _rel_top < _canvas.winfo_height())
# A deliberately undersized window (850 tall, long status text):
# the split degrades gracefully — neither pane collapses to zero
# and the detail pane stays inside the page.
set_size(900, 850)
check('G9e a short stack still gives both panes a visible share',
      page._main_mode == 'stack'
      and _logical(_canvas.winfo_height()) >= 50
      and _logical(page._detail_panel.winfo_height()) >= 110
      and page._detail_panel.winfo_rooty()
      + page._detail_panel.winfo_height()
      <= page.winfo_rooty() + page.winfo_height() + 2)
set_size(1500, 950)
check('G9f widening restores side-by-side and keeps the selection',
      page._main_mode == 'side'
      and page._report is not None
      and page._report['session']['session_id'] == _first_sid)

# ---------------------------------------------------------------- G7
# Repro of the Windows 125% report: the badge and the ID save
# button were starved by equal grid columns, and the long
# collection status was crushed into a third of the card. At a
# realistic app width all three must keep their full geometry.
set_width(1300)
_LONG2 = ('固定観測コレクタが正常に収集できていません（接続エラーが発生したため再試行しています）。'
          'セッションだけが「観測中」の状態になっています。 ／ 最終データ 2026-11-02 01:47:42')
page.collector_label.configure(text=_LONG2)
pump(0.3)
if '正常に収集できていません' not in page.collector_label.cget('text'):
    page.collector_label.configure(text=_LONG2)
    root.update_idletasks()


def _full(widget):
    return (widget.winfo_ismapped()
            and widget.winfo_width() >= widget.winfo_reqwidth() - 2
            and widget.winfo_rootx() >= page.winfo_rootx() - 1
            and widget.winfo_rootx() + widget.winfo_width()
            <= page.winfo_rootx() + page.winfo_width() + 1)


check('G7a the status badge keeps its full width at app width',
      _full(page.badge))
check('G7b the ID save button keeps its full width and stays inside',
      _full(page._id_save_button))
check('G7c the long collection status is fully laid out (no clipping)',
      page.collector_label.winfo_height()
      >= page.collector_label.winfo_reqheight() - 4
      and page.collector_label.winfo_rootx()
      + page.collector_label.winfo_width()
      <= page.winfo_rootx() + page.winfo_width() + 1
      and '2026-11-02 01:47:42' in page.collector_label.cget('text'))

# ---------------------------------------------------------------- G8
from core.fixed_observation import get_pro_tiktok_id

page.account_entry.delete(0, 'end')
page.account_entry.insert(0, 'qa_save_user')
page._id_save_button.invoke()
pump(0.3)
check('G8 the ID save button actually saves the entered ID',
      get_pro_tiktok_id() == 'qa_save_user')

page.destroy()
pump(0.2)

print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
