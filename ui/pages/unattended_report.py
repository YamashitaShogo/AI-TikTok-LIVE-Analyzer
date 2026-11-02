"""Streaming report page (Pulse Pro) — formerly the unattended
observation report page.

The streamer-facing flow is: start analysis, let Pulse record the
battles and viewer counts it can observe, then read the report
(KPIs, charts, battle history), optionally run the AI improvement
analysis by hand, and export PDF/CSV/JSON.

Honesty rules kept from the observation report implementation:
- Only observed data is shown; an unobserved value is '未取得', never 0.
- A battle whose end was not confirmed has no final score; its latest
  known score is shown separately as a reference value.
- Missing intervals are gaps in the charts, never connected lines.
- Sessions are owned by the process-wide SessionRuntime: leaving this
  page never stops recording, and stopping a session auto-generates
  its JSON report (PDF output and AI analysis stay manual).
- AI analysis runs ONLY from its explicit button, after the exact
  payload (anonymised aggregates) is shown in the preview box.
- Advanced/observation-management controls (data source, Battle
  Hunter / fixed observation / TopWatch, session and period scopes)
  live on the 詳細設定 tab; TopWatch data stays read-only.
"""
import json
import logging
import queue
import re
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.fixed_observation import (get_fixed_controller, get_pro_tiktok_id,
                                    set_pro_tiktok_id)
from core.settings import SettingsLoadError, SettingsSaveError
from core.observation_sessions import JST, format_jst, get_runtime
from core.report_ai import analyze as ai_analyze, evidence_preview
from core.report_export import export_csv, export_json, export_pdf
from core.unattended_report import (available_sources, build_report,
                                    compare_reports, session_summaries)
from core.workspace_config import MODE_DEVELOPER
from core.workspace_manager import WorkspaceManager
from ui import theme
from ui.components.section_card import SectionCard
from ui.components.stat_card import StatCard
from ui.components.status_badge import StatusBadge

TEXT = ('#0F172A', '#F8FAFC')
MUTED = ('#64748B', '#94A3B8')
CARD = ('#FFFFFF', '#111C30')
END_LABELS = {'running': '観測中', 'normal': '正常終了', 'abnormal': '異常終了',
              'interrupted': '中断（再起動で検出）'}
MODE_LABELS = {'individual': '個人戦', 'team': 'チーム戦'}
PARTIAL_LABELS = {'full': '開始から観測', 'partial': '途中から観測', 'unknown': '観測の完全性は判定不可'}


def number(value):
    return '未取得' if value is None else f'{value:,.0f}'


def duration_text(seconds):
    if seconds is None:
        return '未取得'
    seconds = int(seconds)
    return f'{seconds // 3600}時間{(seconds % 3600) // 60}分'


def duration_clock(seconds):
    if seconds is None:
        return '未取得'
    seconds = max(0, int(seconds))
    return f'{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}'


def format_mode(mode):
    return MODE_LABELS.get(str(mode or ''), '形式不明')


def short_name(name, limit=26):
    name = str(name or '')
    return name if len(name) <= limit else name[:limit - 1] + '…'


def battle_score_text(battle):
    """Final-score cell text: confirmed final, reference, or 未取得."""
    if battle.get('score_known'):
        return number(battle.get('final_score'))
    if battle.get('last_known_score') is not None:
        return f"{battle['last_known_score']:,.0f}（参考・終了未確認）"
    return '未取得'


def kpi_items(report):
    """The eight headline KPI cards for a report dict (pure helper).

    Unknown values stay '未取得' here as well; nothing is zero-filled.
    """
    summary = (report or {}).get('summary') or {}
    if not summary:
        return []
    monitored = summary.get('monitored_seconds')
    if monitored is None:
        coverage = '実測不可'
        coverage_sub = '監視できた時間はセッション指定のレポートで表示します'
    else:
        coverage = f"監視 {duration_text(monitored)}"
        coverage_sub = (f"接続中断 {duration_text(summary.get('disconnected_seconds'))}"
                        f" ／ 未取得区間 {summary.get('gap_count', 0)} 件")
    return [
        {'title': '観測時間', 'value': duration_text(summary.get('observed_seconds')),
         'sub': '配信時間ではありません'},
        {'title': '記録バトル数', 'value': f"{summary.get('record_count', 0):,}",
         'sub': f"ユニーク {summary.get('unique_battle_count', 0):,} 件"},
        {'title': '正常終了バトル数', 'value': f"{summary.get('finished_confirmed', 0):,}",
         'sub': f"終了未確認 {summary.get('unfinished', 0):,} 件"},
        {'title': '最大確認スコア', 'value': number(summary.get('final_score_max')),
         'sub': f"確定スコア {summary.get('score_known_battles', 0):,} 件が対象"},
        {'title': 'スコア中央値', 'value': number(summary.get('final_score_median')),
         'sub': '終了が確認できたバトルの最終スコアのみ'},
        {'title': '視聴者数中央値', 'value': number(summary.get('viewer_median')),
         'sub': 'バトルごとの中央値の中央値'},
        {'title': '最大確認視聴者数', 'value': number(summary.get('viewer_peak_max')),
         'sub': f"視聴者数の記録 {summary.get('viewer_sample_total', 0):,} 回"},
        {'title': 'データ取得状況', 'value': coverage, 'sub': coverage_sub, 'value_size': 15},
    ]


_AI_MARKERS = [('summary', '①'), ('good', '②'), ('improve', '③'), ('next', '④')]


def split_ai_sections(answer):
    """Split the AI answer (①-④ format) into display sections.

    Returns (sections, found). When the markers are absent, ``found``
    is False and the caller shows the full text as-is instead of
    pretending it was structured.
    """
    text = str(answer or '')
    positions = []
    for key, marker in _AI_MARKERS:
        idx = text.find(marker)
        if idx >= 0:
            positions.append((idx, key, marker))
    if len(positions) < 2:
        return {'summary': '', 'good': '', 'improve': '', 'next': ''}, False
    positions.sort()
    sections = {'summary': '', 'good': '', 'improve': '', 'next': ''}
    for i, (idx, key, marker) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        body = text[idx + len(marker):end].strip()
        body = re.sub(r'^[^\n：:]{0,20}[：:]\s*', '', body, count=1) if '\n' not in body[:24] else body
        sections[key] = body
    return sections, True


class UnattendedReportPage(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color='transparent', corner_radius=0)
        self._alive = True
        self._queue = queue.Queue()
        self._busy = False
        self._refresh_pending = False
        self._tick = 0
        self._workspace = WorkspaceManager()
        self._sources = available_sources()
        # Pulse Pro default: fixed observation (capture_fixed) of the
        # streamer's own registered account. In the streamer
        # workspace this is not just the default but the ONLY source:
        # the streamer product analyses the streamer's own LIVE, so
        # normal observation and TopWatch data must never be read
        # here (developer workspace keeps all three, see
        # change_source). The lock is enforced in logic, not only by
        # hiding the selector.
        self._source = next(
            (s for s in self._sources if s.get('key') == 'capture_fixed'),
            self._sources[0] if self._sources else None)
        # Generation of the asynchronous loads (session list,
        # history, generated reports, AI). Bumped on every source
        # change; results stamped with an older generation are
        # dropped by the pump so a slow load from the previous
        # source can never overwrite the new source's screen.
        self._load_gen = 0
        # Session lifetime belongs to the process-wide runtime, not to
        # this page: leaving the page never stops session recording.
        self._runtime = get_runtime(self._source['capture_dir']) if self._source else None
        self._active_session_id = None
        self._running_started_at = None
        self._transition = False  # start/stop reentrancy guard (Phase 4)
        # Read-only display auto-refresh: re-aggregates what is on
        # screen from the latest DB/session rows every few seconds.
        # Strictly separated from generate(): it never writes report
        # files, never marks a session's report as generated and never
        # runs AI. _display_gen invalidates results that arrive after
        # the target changed (session switch, source change, manual
        # generation, page destroy).
        self._generating = False
        self._display_gen = 0
        self._display_inflight = None  # gen of the running display worker
        self._display_request = None   # {'scope', 'session_id', 'auto'}
        self._sessions = []
        # History tab state: basic session rows (no event lists) for
        # the current source plus their light aggregates. Kept apart
        # from _sessions (the detail tab's list) so a long history
        # never slows the detail path down.
        self._history_sessions = []
        self._history_summaries = {}
        self._history_error = None
        self._history_filter_text = ''
        self._history_filter_date = ''
        self._history_page = 0
        self._history_signature = None
        self._history_cards = {}
        self._report = None
        self._ai_text = None
        self._selected_battle = None
        self._poll = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # ------------------------------------------------ header
        head = ctk.CTkFrame(self, fg_color='transparent')
        head.grid(row=0, column=0, sticky='ew', padx=24, pady=(20, 4))
        title_box = ctk.CTkFrame(head, fg_color='transparent')
        title_box.pack(side='left', fill='x', expand=True)
        ctk.CTkLabel(title_box, text='配信レポート', text_color=TEXT, anchor='w',
                     font=(theme.FONT_FAMILY, 26, 'bold')).pack(anchor='w')
        self._head_desc = ctk.CTkLabel(
            title_box, anchor='w', justify='left', wraplength=760, text_color=MUTED,
            text='Pulseが観測できたバトルと同時視聴者数の記録を集計します。'
                 '配信全体の成果ではなく、音声・発言内容は含みません。'
                 '取得できなかった情報は「未取得」と表示します。',
            font=(theme.FONT_FAMILY, theme.FONT_SMALL))
        self._head_desc.pack(anchor='w', pady=(2, 0))
        ctk.CTkButton(head, text='更新', width=70, command=self.refresh).pack(side='right', padx=4)

        # ------------------------------------------------ status card
        # The CURRENT collection state only — never the past session
        # selected below. Fields sit in a re-flowing grid (3/2/1
        # columns by measured width) and the actions live in their
        # own row, so they can never be squeezed off-screen by the
        # info column again (the 125%/150% failure this replaces).
        bar = SectionCard(self, '現在の観測状態')
        bar.grid(row=1, column=0, sticky='ew', padx=24, pady=(6, 6))
        layout = ctk.CTkFrame(bar.body, fg_color='transparent')
        layout.pack(fill='x')
        self._status_layout = layout
        self._status_cols = 4
        self._actions_stacked = False
        self._wrap_cache = {}
        fields = ctk.CTkFrame(layout, fg_color='transparent')
        fields.pack(fill='x')
        self._status_fields = fields

        def field_block(parent, caption, caption_width=76):
            block = ctk.CTkFrame(parent, fg_color='transparent')
            ctk.CTkLabel(block, text=caption, text_color=MUTED,
                         width=caption_width, anchor='w').pack(side='left')
            return block

        # Short fields share a re-flowing grid (4/2/1 columns). The
        # badge is packed BEFORE the flexible target label so its
        # parcel is reserved first and can never be starved by it.
        b_target = field_block(fields, '観測対象:')
        self.badge = StatusBadge(b_target, 'none')
        self.badge.pack(side='right', padx=(8, 0))
        self.target_label = ctk.CTkLabel(b_target, text='未選択', text_color=TEXT,
                                         anchor='w', justify='left', wraplength=300)
        self.target_label.pack(side='left', fill='x', expand=True)
        b_started = field_block(fields, '観測開始:')
        self.started_label = ctk.CTkLabel(b_started, text='—', text_color=TEXT, anchor='w')
        self.started_label.pack(side='left')
        b_elapsed = field_block(fields, '観測時間:')
        self.elapsed_label = ctk.CTkLabel(b_elapsed, text='—', text_color=TEXT, anchor='w',
                                          font=(theme.FONT_FAMILY, theme.FONT_BODY, 'bold'))
        self.elapsed_label.pack(side='left')
        b_observing = field_block(fields, '実際の観測ID:', caption_width=110)
        self.observing_label = ctk.CTkLabel(b_observing, text='—', text_color=TEXT,
                                            anchor='w', justify='left', wraplength=300)
        self.observing_label.pack(side='left', fill='x', expand=True)
        self._short_blocks = [b_target, b_started, b_elapsed, b_observing]
        # The ID row and the collection status get their OWN
        # full-width rows: equal grid columns starved exactly these
        # two at 125% (the save button squeezed below its requested
        # width, the long status crushed into a third of the card).
        b_id = field_block(layout, '自分のTikTok ID:', caption_width=110)
        b_id.pack(fill='x', pady=(2, 0))
        self._id_block = b_id
        self.account_entry = ctk.CTkEntry(b_id, width=200, placeholder_text='@IDまたはLIVEのURL')
        self.account_entry.pack(side='left')
        saved_id = get_pro_tiktok_id()
        if saved_id:
            self.account_entry.insert(0, saved_id)
        self._id_save_button = ctk.CTkButton(
            b_id, text='IDを保存', width=84, command=self.save_account_id)
        self._id_save_button.pack(side='left', padx=8)
        b_collector = field_block(layout, '収集状態:', caption_width=110)
        b_collector.pack(fill='x', pady=(2, 0))
        self.collector_label = ctk.CTkLabel(b_collector, text='停止中', text_color=TEXT,
                                            anchor='w', justify='left', wraplength=760)
        self.collector_label.pack(side='left', fill='x', expand=True)
        self._field_blocks = [b_target, b_started, b_elapsed,
                              b_observing, b_id, b_collector]
        self._grid_field_blocks()
        self._note_label = ctk.CTkLabel(
            layout, text_color=MUTED, anchor='w', justify='left', wraplength=760,
            font=(theme.FONT_FAMILY, theme.FONT_SMALL),
            text='※この表示は現在の収集状態です。下で選択している過去の配信とは別に表示します。'
                 '本人確認は未実装のため、登録IDは観測対象の設定であり、所有者として認証されたものではありません。')
        self._note_label.pack(fill='x', pady=(6, 0))
        # Action row: priority is explicit — レポート出力 is the
        # primary action (it generates the report file), 分析を開始
        # is secondary, 分析を終了 is the destructive action.
        actions = ctk.CTkFrame(layout, fg_color='transparent')
        actions.pack(fill='x', pady=(8, 0))
        self._status_actions = actions
        self.start_button = ctk.CTkButton(
            actions, text='分析を開始', width=140, height=38,
            fg_color='#EAF1FE', hover_color='#D6E4FC', text_color=theme.PRIMARY,
            command=self.start_session)
        self.start_button.pack(side='left', padx=4)
        self.stop_button = ctk.CTkButton(
            actions, text='分析を終了', width=140, height=38,
            fg_color='#FFFFFF', hover_color='#FDECEF', text_color=theme.DANGER,
            border_width=1, border_color=theme.DANGER,
            command=self.stop_session, state='disabled')
        self.stop_button.pack(side='left', padx=4)
        self.show_report_button = ctk.CTkButton(
            actions, text='レポート出力', width=170, height=38,
            fg_color=theme.PURPLE, hover_color=theme.PURPLE_HOVER,
            command=self.show_latest_report)
        self.show_report_button.pack(side='right', padx=4)
        self._action_buttons = [self.start_button, self.stop_button,
                                self.show_report_button]
        layout.bind('<Configure>', self._on_status_resize)

        # ------------------------------------------------ main split
        # Left: the always-visible history list. Right: the selected
        # session's detail (header + the five analysis tabs). The
        # split collapses to a vertical stack on narrow windows.
        main = ctk.CTkFrame(self, fg_color='transparent')
        main.grid(row=2, column=0, sticky='nsew', padx=24, pady=(4, 8))
        self._main = main
        self._main_mode = 'side'
        history_card = SectionCard(main, '配信履歴')
        self._history_panel = history_card
        self._build_history(history_card.body)
        detail_card = SectionCard(main, '現在表示中の配信')
        self._detail_panel = detail_card
        self._build_detail_header(detail_card.body)
        self.tabs = ctk.CTkTabview(detail_card.body, fg_color=CARD)
        self.tabs.pack(fill='both', expand=True, pady=(6, 0))
        self._build_overview(self.tabs.add('概要'))
        self._build_battles(self.tabs.add('バトル履歴'))
        self._build_ai(self.tabs.add('AI改善提案'))
        self._build_export(self.tabs.add('レポート出力'))
        self._build_details(self.tabs.add('詳細設定'))
        history_card.grid(row=0, column=0, sticky='ns')
        history_card.configure(width=400)
        detail_card.grid(row=0, column=1, sticky='nsew', padx=(12, 0))
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)
        main.bind('<Configure>', self._on_main_resize)

        # ------------------------------------------------ status line
        bottom = ctk.CTkFrame(self, fg_color='transparent')
        bottom.grid(row=3, column=0, sticky='ew', padx=26, pady=(0, 12))
        self.progress = ctk.CTkProgressBar(bottom, width=150, mode='indeterminate')
        self.progress.pack(side='left', padx=(0, 10))
        self.progress.pack_forget()
        self.status = ctk.CTkLabel(bottom, text='', text_color=MUTED, anchor='w')
        self.status.pack(side='left', fill='x', expand=True)
        self._schedule()
        self.refresh()

    # ------------------------------------------------------------ tab builders
    def _build_overview(self, tab):
        scroll = ctk.CTkScrollableFrame(tab, fg_color='transparent')
        scroll.pack(fill='both', expand=True)
        scroll.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform='kpi')
        self.empty_label = ctk.CTkLabel(
            scroll, text_color=MUTED, justify='left', anchor='w', wraplength=820,
            text='まだレポートを表示していません。\n'
                 '「分析を開始」して観測し、「レポートを表示」を押すと、ここに数値とグラフが出ます。\n'
                 '過去の観測がある場合は、観測しなくても「レポートを表示」で集計できます。',
            font=(theme.FONT_FAMILY, 13))
        self.empty_label.grid(row=0, column=0, columnspan=4, sticky='ew', padx=6, pady=(8, 4))
        self.kpi_cards = []
        for index, title in enumerate((
                '観測時間', '記録バトル数', '正常終了バトル数', '最大確認スコア',
                'スコア中央値', '視聴者数中央値', '最大確認視聴者数', 'データ取得状況')):
            card = StatCard(scroll, title, '—')
            card.grid(row=1 + index // 4, column=index % 4, sticky='nsew', padx=5, pady=5)
            self.kpi_cards.append(card)

        selector = ctk.CTkFrame(scroll, fg_color='transparent')
        selector.grid(row=3, column=0, columnspan=4, sticky='ew', padx=6, pady=(12, 2))
        ctk.CTkLabel(selector, text='グラフで見るバトル:', text_color=MUTED).pack(side='left')
        self.battle_menu = ctk.CTkOptionMenu(selector, values=['バトル未取得'], width=340,
                                             command=lambda _: self.select_battle())
        self.battle_menu.pack(side='left', padx=8)
        self.battle_detail = ctk.CTkLabel(scroll, text='', text_color=TEXT, anchor='w',
                                          justify='left', wraplength=860)
        self.battle_detail.grid(row=4, column=0, columnspan=4, sticky='ew', padx=6, pady=(2, 6))

        score_card = SectionCard(scroll, 'バトルスコア推移',
                                 note='未取得区間は線をつなぎません')
        score_card.grid(row=5, column=0, columnspan=4, sticky='ew', padx=4, pady=5)
        self.score_chart = tk.Canvas(score_card.body, highlightthickness=0, height=180)
        self.score_chart.pack(fill='x', expand=True)
        self.score_chart.bind('<Configure>', lambda _: self.draw_charts())
        viewer_card = SectionCard(scroll, '同時視聴者数推移',
                                  note='観測できた区間のみ表示します')
        viewer_card.grid(row=6, column=0, columnspan=4, sticky='ew', padx=4, pady=5)
        self.viewer_chart = tk.Canvas(viewer_card.body, highlightthickness=0, height=180)
        self.viewer_chart.pack(fill='x', expand=True)
        self.viewer_chart.bind('<Configure>', lambda _: self.draw_charts())

        notes_card = SectionCard(scroll, '集計の内訳と注意事項')
        notes_card.grid(row=7, column=0, columnspan=4, sticky='ew', padx=4, pady=5)
        self.summary_box = ctk.CTkTextbox(notes_card.body, wrap='word', height=170,
                                          font=(theme.FONT_FAMILY, 12))
        self.summary_box.pack(fill='both', expand=True)
        self.summary_box.configure(state='disabled')

    def _build_battles(self, tab):
        ctk.CTkLabel(tab, text_color=MUTED, anchor='w', justify='left', wraplength=850,
                     text='観測できたバトルの一覧です。「詳細」を押すと概要タブでグラフを確認できます。'
                          '終了が確認できていないバトルのスコアは「参考」と表示し、確定スコアには含めません。'
                     ).pack(fill='x', padx=10, pady=(10, 4))
        self.battles_scroll = ctk.CTkScrollableFrame(tab, fg_color='transparent')
        self.battles_scroll.pack(fill='both', expand=True, padx=6, pady=4)
        self.battles_empty = ctk.CTkLabel(self.battles_scroll, text='バトル履歴はまだありません。',
                                          text_color=MUTED)
        self.battles_empty.pack(pady=16)

    HISTORY_PAGE_SIZE = 20

    def _build_detail_header(self, body):
        row = ctk.CTkFrame(body, fg_color='transparent')
        row.pack(fill='x')
        left = ctk.CTkFrame(row, fg_color='transparent')
        left.pack(side='left', fill='x', expand=True)
        self.detail_title_label = ctk.CTkLabel(
            left, text='読み込んでいます…', text_color=TEXT, anchor='w',
            justify='left', wraplength=560,
            font=(theme.FONT_FAMILY, 17, 'bold'))
        self.detail_title_label.pack(anchor='w')
        sub = ctk.CTkFrame(left, fg_color='transparent')
        sub.pack(anchor='w', pady=(3, 0))
        self.detail_badge = ctk.CTkLabel(
            sub, text='', width=76, corner_radius=9,
            font=(theme.FONT_FAMILY, theme.FONT_SMALL, 'bold'))
        self.detail_badge.pack(side='left')
        self.history_viewing_label = ctk.CTkLabel(
            sub, text='最新の観測を表示中', text_color=MUTED, anchor='w')
        self.history_viewing_label.pack(side='left', padx=(8, 0))
        self.detail_latest_button = ctk.CTkButton(
            row, text='最新の観測に戻る', width=150, height=34,
            fg_color='#EAF1FE', hover_color='#D6E4FC', text_color=theme.PRIMARY,
            command=self.show_latest_display)
        self.detail_latest_button.pack(side='right', padx=(10, 0))

    def _build_history(self, body):
        ctk.CTkLabel(
            body, text='選択すると右側に分析が表示されます',
            text_color=MUTED, anchor='w', justify='left', wraplength=340,
            font=(theme.FONT_FAMILY, theme.FONT_SMALL)).pack(fill='x', pady=(0, 4))
        self.history_filter_entry = ctk.CTkEntry(
            body, placeholder_text='配信者で検索（例: mio）')
        self.history_filter_entry.pack(fill='x')
        self.history_filter_entry.bind('<Return>', lambda _e: self.apply_history_filter())
        date_row = ctk.CTkFrame(body, fg_color='transparent')
        date_row.pack(fill='x', pady=(4, 0))
        self.history_date_entry = ctk.CTkEntry(
            date_row, width=120, placeholder_text='日付 YYYY-MM-DD')
        self.history_date_entry.pack(side='left', fill='x', expand=True)
        self.history_date_entry.bind('<Return>', lambda _e: self.apply_history_filter())
        ctk.CTkButton(date_row, text='絞り込み', width=76,
                      command=self.apply_history_filter).pack(side='left', padx=(6, 0))
        ctk.CTkButton(date_row, text='クリア', width=64, fg_color='#EEF1F6',
                      hover_color='#E0E6EF', text_color=TEXT,
                      command=self.clear_history_filter).pack(side='left', padx=(6, 0))
        self.history_latest_button = ctk.CTkButton(
            body, text='最新の観測を表示', height=34,
            fg_color='#EAF1FE', hover_color='#D6E4FC', text_color=theme.PRIMARY,
            command=self.show_latest_display)
        self.history_latest_button.pack(fill='x', pady=(6, 0))
        self.history_note = ctk.CTkLabel(body, text='', text_color=MUTED, anchor='w',
                                         justify='left', wraplength=340)
        self.history_note.pack(fill='x', pady=(1, 0))
        self.history_list = ctk.CTkScrollableFrame(body, fg_color='transparent')
        self.history_list.pack(fill='both', expand=True, pady=2)
        pager = ctk.CTkFrame(body, fg_color='transparent')
        pager.pack(fill='x', pady=(2, 0))
        self.history_prev_button = ctk.CTkButton(
            pager, text='前のページ', width=92, command=self.history_prev_page)
        self.history_prev_button.pack(side='left')
        self.history_page_label = ctk.CTkLabel(pager, text='', text_color=MUTED)
        self.history_page_label.pack(side='left', padx=8)
        self.history_next_button = ctk.CTkButton(
            pager, text='次のページ', width=92, command=self.history_next_page)
        self.history_next_button.pack(side='left')

    def _build_ai(self, tab):
        scroll = ctk.CTkScrollableFrame(tab, fg_color='transparent')
        scroll.pack(fill='both', expand=True)
        ctk.CTkLabel(
            scroll, text_color=MUTED, wraplength=850, justify='left', anchor='w',
            text='AI改善分析は、ボタンを押したときだけ実行します（自動では実行しません）。'
                 '送信するのは下のプレビューにある集計値だけです。配信者は匿名コード化され、'
                 'コメント本文・Cookie・LIVE映像・名前や@IDは送りません。'
                 '未取得のデータを補完したり、因果関係を断定したりはしません。'
                 '既存AIサービスの利用枠・料金が適用されます。').pack(fill='x', padx=10, pady=(10, 4))
        controls = ctk.CTkFrame(scroll, fg_color='transparent')
        controls.pack(fill='x', padx=10, pady=4)
        self.ai_button = ctk.CTkButton(controls, text='AI改善分析を実行', width=170, height=38,
                                       fg_color=theme.PURPLE, hover_color=theme.PURPLE_HOVER,
                                       command=self.run_ai)
        self.ai_button.pack(side='left', padx=4)
        self.ai_status = ctk.CTkLabel(controls, text='未実行', text_color=MUTED)
        self.ai_status.pack(side='left', padx=10)
        ctk.CTkLabel(scroll, text='送信データのプレビュー（この内容がそのまま送信されます）',
                     text_color=MUTED, anchor='w').pack(fill='x', padx=12, pady=(8, 0))
        self.ai_preview = ctk.CTkTextbox(scroll, wrap='word', height=110,
                                         font=(theme.FONT_FAMILY, 11))
        self.ai_preview.pack(fill='x', padx=12, pady=4)
        self.ai_preview.configure(state='disabled')
        self.ai_boxes = {}
        for key, title, height in (
                ('summary', '観測結果の要約（AI）', 84),
                ('good', '1. 良かった傾向', 110),
                ('improve', '2. 改善を検討したい点', 110),
                ('next', '3. 次回の配信で試すこと', 130)):
            card = SectionCard(scroll, title)
            card.pack(fill='x', padx=6, pady=5)
            box = ctk.CTkTextbox(card.body, wrap='word', height=height,
                                 font=(theme.FONT_FAMILY, 13))
            box.pack(fill='both', expand=True)
            box.insert('1.0', 'AI改善分析を実行すると、ここに表示されます。')
            box.configure(state='disabled')
            self.ai_boxes[key] = box

    def _build_export(self, tab):
        ctk.CTkLabel(
            tab, text_color=MUTED, wraplength=850, justify='left', anchor='w',
            text='レポートの保存形式を選んでください。PDF出力とAI分析は手動操作です。'
                 'セッションを終了したときは、JSONレポートが自動で作成されます'
                 '（保存先: observation_report/reports）。').pack(fill='x', padx=12, pady=(12, 6))
        bar = ctk.CTkFrame(tab, fg_color='transparent')
        bar.pack(fill='x', padx=12, pady=6)
        for kind, label in (('pdf', 'PDF出力'), ('csv', 'CSV出力'), ('json', 'JSON出力')):
            ctk.CTkButton(bar, text=label, width=150, height=42,
                          command=lambda k=kind: self.export(k)).pack(side='left', padx=6)
        ctk.CTkLabel(tab, text='前回レポートとの比較', text_color=TEXT,
                     font=(theme.FONT_FAMILY, theme.FONT_SECTION_TITLE, 'bold')
                     ).pack(fill='x', padx=12, pady=(14, 2))
        self.compare_box = ctk.CTkTextbox(tab, wrap='word', font=(theme.FONT_FAMILY, 13))
        self.compare_box.pack(fill='both', expand=True, padx=12, pady=6)
        self.compare_box.configure(state='disabled')

    def _build_details(self, tab):
        scroll = ctk.CTkScrollableFrame(tab, fg_color='transparent')
        scroll.pack(fill='both', expand=True)
        intro = ('観測方式は固定観測（自分のTikTok LIVE）です。'
                 'セッション・期間を指定した集計はここから行います。') \
            if self._streamer_locked() else (
                '観測データの管理用設定です。通常の利用では変更する必要はありません。'
                '既存の観測方式（Battle Hunter / 固定観測 / TopWatch）の選択や、'
                'セッション・期間を指定した集計はここから行います。'
                'TopWatchの子プロセスデータは読み取り専用で扱います。')
        ctk.CTkLabel(
            scroll, text_color=MUTED, wraplength=850, justify='left', anchor='w',
            text=intro).pack(fill='x', padx=10, pady=(10, 6))

        source_card = SectionCard(scroll, 'データと観測方式')
        source_card.pack(fill='x', padx=6, pady=5)
        row = ctk.CTkFrame(source_card.body, fg_color='transparent')
        row.pack(fill='x', pady=3)
        ctk.CTkLabel(row, text='データ種別（通常観測／固定観測／TopWatch）', text_color=MUTED).pack(side='left')
        self.source_menu = ctk.CTkOptionMenu(
            row, values=[s['label'] for s in self._sources] or ['データなし'],
            command=lambda _: self.change_source())
        if self._source:
            self.source_menu.set(self._source['label'])
        self.source_menu.pack(side='left', padx=8)
        self.source_note = None
        if self._streamer_locked():
            # Streamer workspace: fixed observation only. The
            # selectors stay visible as read-only information (the
            # logic guard in change_source enforces the same rule
            # even if they were reached programmatically).
            self.source_menu.configure(values=['固定観測'], state='disabled')
            self.source_menu.set('固定観測')
            self.source_note = ctk.CTkLabel(
                source_card.body, text='観測方式：固定観測（自分のTikTok LIVE）',
                text_color=MUTED, anchor='w')
            self.source_note.pack(fill='x', pady=(4, 0))
        row = ctk.CTkFrame(source_card.body, fg_color='transparent')
        row.pack(fill='x', pady=3)
        ctk.CTkLabel(row, text='観測モード', text_color=MUTED).pack(side='left')
        self.mode_menu = ctk.CTkOptionMenu(
            row, values=['Battle Hunter', '固定観測', 'TopWatch', '手動観測'], width=160)
        self.mode_menu.set('固定観測')
        self.mode_menu.pack(side='left', padx=8)
        if self._streamer_locked():
            self.mode_menu.configure(state='disabled')
        ctk.CTkLabel(row, text='対象（@ID、カンマ区切り）', text_color=MUTED).pack(side='left', padx=(16, 0))
        self.target_entry = ctk.CTkEntry(row, width=230)
        self.target_entry.pack(side='left', padx=8)
        self.session_id_label = ctk.CTkLabel(source_card.body, text='セッションID: —',
                                             text_color=MUTED, anchor='w')
        self.session_id_label.pack(fill='x', pady=(6, 0))

        scope_card = SectionCard(scroll, '集計の範囲（セッション指定・配信者・期間）')
        scope_card.pack(fill='x', padx=6, pady=5)
        row = ctk.CTkFrame(scope_card.body, fg_color='transparent')
        row.pack(fill='x', pady=3)
        self.scope_menu = ctk.CTkOptionMenu(
            row, values=['最新セッション', 'セッション指定', '配信者', '期間'], width=140)
        self.scope_menu.pack(side='left')
        self.session_menu = ctk.CTkOptionMenu(row, values=['セッションなし'], width=300)
        self.session_menu.pack(side='left', padx=8)
        row = ctk.CTkFrame(scope_card.body, fg_color='transparent')
        row.pack(fill='x', pady=3)
        ctk.CTkLabel(row, text='期間', text_color=MUTED).pack(side='left')
        self.period_start = ctk.CTkEntry(row, width=110)
        self.period_start.pack(side='left', padx=6)
        ctk.CTkLabel(row, text='〜', text_color=MUTED).pack(side='left')
        self.period_end = ctk.CTkEntry(row, width=110)
        self.period_end.pack(side='left', padx=6)
        ctk.CTkLabel(row, text='(YYYY-MM-DD)', text_color=MUTED).pack(side='left')
        self.generate_button = ctk.CTkButton(row, text='この条件でレポート生成', width=170,
                                             command=self.generate)
        self.generate_button.pack(side='right')

        defs_card = SectionCard(scroll, 'データ取得に関する詳細情報')
        defs_card.pack(fill='both', expand=True, padx=6, pady=5)
        self.definitions_box = ctk.CTkTextbox(defs_card.body, wrap='word', height=190,
                                              font=(theme.FONT_FAMILY, 12))
        self.definitions_box.pack(fill='both', expand=True)
        self.definitions_box.configure(state='disabled')

    # ------------------------------------------------ status layout
    def _actions_req_width(self):
        return (sum(b.winfo_reqwidth() for b in self._action_buttons)
                + 8 * len(self._action_buttons))

    def _on_status_resize(self, event):
        if self._alive and event.width > 1:
            self._apply_status_layout(event.width)

    def _short_block_minimums(self, scaling):
        """Design minimums (physical px) for the four short blocks:
        the measured caption width plus a fixed minimum for the
        value. Deliberately NOT the labels' current requested
        widths — those follow the wrap pins, which would make the
        column decision circular (the 125% starvation bug)."""
        caps = []
        for block in self._short_blocks:
            caption = block.winfo_children()[0]
            caps.append(caption.winfo_reqwidth())
        label_mins = (int(120 * scaling) + self.badge.winfo_reqwidth() + 8,
                      int(150 * scaling), int(70 * scaling),
                      int(70 * scaling))
        return [cap + label_min for cap, label_min in zip(caps, label_mins)]

    def _apply_status_layout(self, width):
        """Responsive rearrangement of the status card.

        The four short field blocks re-flow between 4, 2 and 1 grid
        columns (natural column widths — never uniform, which
        starved the wide blocks at 125%); the ID row and the
        collection status always span the full card width below
        them. The action row stacks its buttons full-width only
        when even the row no longer fits. A hysteresis band keeps
        the column count from oscillating while a window is dragged.

        Driven both by <Configure> and by the page's pump: a child's
        requested width can settle AFTER the last size event (fonts
        and CTk scaling realise progressively), and the wrap widths
        depend on those requests — the pump pass makes the layout
        converge instead of freezing on a transient measurement.
        """
        if not self._alive or width <= 1:
            return
        actions_req = self._actions_req_width()
        if actions_req < 100:
            return  # widgets not realised yet; a later event corrects
        try:
            scaling = ctk.ScalingTracker.get_widget_scaling(self) or 1.0
        except Exception:
            scaling = 1.0
        mins = self._short_block_minimums(scaling)
        if min(mins) < 10:
            return
        need4 = sum(mins) + 36
        need2 = max(mins[0] + mins[1], mins[2] + mins[3]) + 12
        cols = self._status_cols
        if cols == 4 and width < need4:
            cols = 2 if width >= need2 - 24 else 1
        elif cols == 2 and width >= need4 + 48:
            cols = 4
        elif cols == 2 and width < need2 - 24:
            cols = 1
        elif cols == 1 and width >= need2 + 48:
            cols = 2
        if cols != self._status_cols:
            self._status_cols = cols
            self._grid_field_blocks()
        stacked = width < actions_req + 16
        if stacked != self._actions_stacked:
            self._actions_stacked = stacked
            self._pack_action_buttons()
        self._update_status_wraps(width)

    def _grid_field_blocks(self):
        cols = self._status_cols
        fields = self._status_fields
        for col in range(4):
            fields.grid_columnconfigure(col, weight=1 if col < cols else 0)
        for index, block in enumerate(self._short_blocks):
            last = index % cols == cols - 1
            block.grid(row=index // cols, column=index % cols,
                       sticky='ew', padx=(0, 0) if last else (0, 12),
                       pady=2)

    def _pack_action_buttons(self):
        for button in self._action_buttons:
            button.pack_forget()
        if self._actions_stacked:
            # Primary action first when the row becomes a stack.
            for button in (self.show_report_button, self.start_button,
                           self.stop_button):
                button.pack(side='top', fill='x', padx=4, pady=3)
        else:
            self.start_button.pack(side='left', padx=4)
            self.stop_button.pack(side='left', padx=4)
            self.show_report_button.pack(side='right', padx=4)

    def _update_status_wraps(self, layout_width):
        """Keep long status texts wrapping inside their field block:
        wrap lengths follow the block's actual column width.

        CTk treats width/wraplength as UNSCALED units and multiplies
        them by the widget scaling itself, while layout widths here
        are physical pixels — so the values are converted back, and
        width is pinned together with wraplength: wraplength alone
        does not cap a label's requested width (a long unbroken
        Japanese sentence requests its longest segment, which is how
        the info column outgrew the card at 125%/150% scaling)."""
        try:
            scaling = ctk.ScalingTracker.get_widget_scaling(self) or 1.0
        except Exception:
            scaling = 1.0
        cols = self._status_cols
        fallback = max(200, layout_width // cols)

        def cell_width(index):
            cell = self._status_fields.grid_bbox(index % cols, index // cols)
            return cell[2] if cell and cell[2] > 50 else fallback

        def caption_req(block):
            return block.winfo_children()[0].winfo_reqwidth()

        target_w = (cell_width(0) - caption_req(self._short_blocks[0])
                    - self.badge.winfo_reqwidth() - 20)
        observing_w = (cell_width(3) - caption_req(self._short_blocks[3]) - 12)
        collector_w = (layout_width
                       - caption_req(self._field_blocks[5]) - 12)
        wraps = (('target', self.target_label, max(140, target_w)),
                 ('observing', self.observing_label, max(140, observing_w)),
                 ('collector', self.collector_label, max(140, collector_w)),
                 ('note', self._note_label, max(140, layout_width - 8)),
                 ('head', self._head_desc,
                  max(200, layout_width - (int(78 * scaling) + 46))))
        for key, label, wrap_px in wraps:
            wrap = int(wrap_px / scaling)
            if abs(self._wrap_cache.get(key, 0) - wrap) > 4:
                self._wrap_cache[key] = wrap
                label.configure(width=wrap, wraplength=wrap)

    # ------------------------------------------------ main split layout
    def _on_main_resize(self, event):
        if self._alive and event.width > 1:
            self._apply_main_layout(event.width)

    def _apply_main_layout(self, width):
        """Side-by-side (history left ~400 units, detail right) when
        the measured widths fit; a vertical stack (history above,
        detail below) when they do not — with hysteresis, driven by
        <Configure> and the pump like the status card."""
        if not self._alive or width <= 1:
            return
        left_req = self._history_panel.winfo_reqwidth()
        if left_req < 100:
            return
        try:
            scaling = ctk.ScalingTracker.get_widget_scaling(self) or 1.0
        except Exception:
            scaling = 1.0
        need = left_req + int(600 * scaling) + 36
        mode = self._main_mode
        if mode == 'side' and width < need - 24:
            mode = 'stack'
        elif mode == 'stack' and width >= need + 48:
            mode = 'side'
        if mode == 'stack':
            # Cap the history panel's height: at its natural height
            # it would take the whole main area on short windows and
            # leave the detail row 0px tall (Tk then never re-lays
            # the detail panel out at all). ~45% of the main height,
            # clamped, keeps both panes usable and scrollable.
            main_h = self._main.winfo_height()
            if main_h > 1:
                target = max(230, min(340, int(main_h * 0.45)))
                if abs(target - getattr(self, '_stack_hist_h', 0)) > 4:
                    self._stack_hist_h = target
                    self._history_panel.configure(height=target)
                    # The panel's content is PACKED, so it is pack
                    # propagation that must stop for the height to hold.
                    self._history_panel.pack_propagate(False)
        elif getattr(self, '_stack_hist_h', 0):
            self._stack_hist_h = 0
            self._history_panel.pack_propagate(True)
        if mode == self._main_mode:
            return
        self._main_mode = mode
        self._history_panel.grid_forget()
        self._detail_panel.grid_forget()
        if mode == 'side':
            self._history_panel.grid(row=0, column=0, sticky='ns')
            self._detail_panel.grid(row=0, column=1, sticky='nsew',
                                    padx=(12, 0))
            self._main.grid_columnconfigure(0, weight=0)
            self._main.grid_columnconfigure(1, weight=1)
            self._main.grid_rowconfigure(0, weight=1)
            self._main.grid_rowconfigure(1, weight=0)
        else:
            self._history_panel.grid(row=0, column=0, sticky='ew')
            self._detail_panel.grid(row=1, column=0, sticky='nsew',
                                    pady=(12, 0))
            self._main.grid_columnconfigure(0, weight=1)
            self._main.grid_columnconfigure(1, weight=0)
            self._main.grid_rowconfigure(0, weight=0)
            self._main.grid_rowconfigure(1, weight=1)

    # ------------------------------------------------------------ plumbing
    def _schedule(self):
        self._poll = self.after(120, self._pump)

    def _pump(self):
        if not self._alive:
            return
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == 'sessions':
                    _, gen, sessions, recovered = item
                    if gen != self._load_gen:
                        continue  # stale: from the previous source
                    self._sessions = sessions
                    self._render_sessions(recovered)
                elif kind == 'report':
                    _, gen, report, previous_path = item
                    if gen != self._load_gen:
                        continue  # stale: generated for the old source
                    self._report = report
                    self._render_report(previous_path)
                elif kind == 'display_report':
                    _, gen, report = item
                    was_inflight = gen == self._display_inflight
                    if was_inflight:
                        self._display_inflight = None
                    if gen == self._display_gen:
                        self._report = report
                        self._render_report(None, display_only=True)
                    elif was_inflight:
                        # A newer request (e.g. a history click) is
                        # already waiting: chase it now instead of at
                        # the next auto-refresh tick.
                        self._start_display_refresh()
                elif kind == 'display_error':
                    _, gen, message = item
                    was_inflight = gen == self._display_inflight
                    if was_inflight:
                        self._display_inflight = None
                    if gen == self._display_gen:
                        self.status.configure(text=message)
                    elif was_inflight:
                        self._start_display_refresh()
                elif kind == 'history':
                    _, gen, sessions, summaries, error = item
                    if gen != self._load_gen:
                        continue  # stale: from the previous source
                    self._history_sessions = sessions
                    self._history_summaries = summaries
                    self._history_error = error
                    self._render_history()
                elif kind == 'ai':
                    _, gen, payload, path, warning = item
                    if gen != self._load_gen:
                        continue  # stale: analysed the old source
                    self._ai_text = payload['answer']
                    self._render_ai(payload['answer'])
                    self.ai_status.configure(text=f'完了（保存: {path or "失敗"}）{warning}')
                    self.ai_button.configure(state='normal')
                elif kind == 'error':
                    _, gen, message = item
                    if gen != self._load_gen:
                        continue  # stale: raised against the old source
                    self.status.configure(text=message)
                    self.ai_button.configure(state='normal')
                    self._set_generating(False)
        except queue.Empty:
            pass
        try:
            layout_width = self._status_layout.winfo_width()
        except Exception:
            layout_width = 0
        if layout_width > 1:
            self._apply_status_layout(layout_width)
        try:
            main_width = self._main.winfo_width()
        except Exception:
            main_width = 0
        if main_width > 1:
            self._apply_main_layout(main_width)
        if self._refresh_pending and not self._busy:
            self._refresh_pending = False
            self.refresh()
        self._tick += 1
        if self._tick % 10 == 0:
            self._update_elapsed()
        if self._tick % 25 == 0:
            self._update_collector_status()
        if self._tick % 50 == 0:
            self._auto_refresh()  # ~6s: sessions + read-only display
        self._poll = self.after(120, self._pump)

    def _update_elapsed(self):
        if self._running_started_at is not None:
            self.elapsed_label.configure(
                text=duration_clock(time.time() - self._running_started_at))

    def _set_generating(self, active):
        self._generating = active
        state = 'disabled' if active else 'normal'
        self.generate_button.configure(state=state)
        self.show_report_button.configure(state=state)
        if active:
            self.progress.pack(side='left', padx=(0, 10), before=self.status)
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def destroy(self):
        # Deliberately does NOT stop any sampler or session: recording
        # is owned by the SessionRuntime and continues across pages.
        # Display auto-refresh, on the other hand, belongs to this
        # page: the pump stops below and in-flight display results are
        # invalidated, so nothing updates a page the user left.
        self._alive = False
        self._display_gen += 1
        if self._poll is not None:
            try:
                self.after_cancel(self._poll)
            except Exception:
                pass
        super().destroy()

    def _set_text(self, box, text):
        box.configure(state='normal')
        box.delete('1.0', 'end')
        box.insert('1.0', text)
        box.configure(state='disabled')

    # ------------------------------------------------------------ sessions
    def _is_topwatch(self):
        return bool(self._source and str(self._source['key']).startswith('topwatch:'))

    def _is_fixed_source(self):
        """The standard Pulse Pro source: the fixed profile's own DB.

        TopWatch children also use the fixed profile internally, but
        they are research-mode sources and are excluded here.
        """
        return bool(self._source and self._source.get('key') == 'capture_fixed')

    def save_account_id(self):
        try:
            tiktok_id = set_pro_tiktok_id(self.account_entry.get())
        except ValueError as exc:
            messagebox.showerror('自分のTikTok ID', str(exc))
            return
        except (SettingsSaveError, SettingsLoadError) as exc:
            # The ID was NOT saved; say so plainly (existing settings
            # are untouched) instead of leaking an unhandled error.
            messagebox.showerror(
                '設定保存エラー',
                'TikTok IDを保存できませんでした。既存の設定は変更されていません。'
                '時間をおいて再度お試しください。\n\n'
                f'{exc}')
            return
        self.account_entry.delete(0, 'end')
        self.account_entry.insert(0, tiktok_id)
        self.status.configure(
            text=f'自分のTikTok IDを保存しました: @{tiktok_id}'
                 '（観測対象の設定です。本人確認済みという意味ではありません）')

    def _fixed_collection_alert(self, session):
        """Warning when a session is 'running' but nothing is actually
        collecting for it on the fixed source; '' when collection is
        genuinely underway (our collector running healthily, or an
        external collector observing the SAME target). Unknown state
        yields '' — never fabricate either way."""
        if session is None or not self._is_fixed_source():
            return ''
        try:
            state = get_fixed_controller(self._source['capture_dir']).status()
        except Exception:
            return ''
        if state.get('running'):
            if state.get('state') in ('stalled', 'blocked', 'not_found'):
                return (f"固定観測コレクタが正常に収集できていません（{state.get('label', '')}）。"
                        'セッションだけが「観測中」の状態になっています。')
            return ''
        targets = [str(t) for t in (session.get('targets') or [])]
        if (state.get('state') == 'conflict'
                and str(state.get('external_target') or '') in targets):
            return ''  # an external collector observes the same target
        if state.get('state') == 'not_found':
            return ('対象ユーザーが見つかりません（IDをご確認ください）。'
                    'セッションは「観測中」のままですが、現在データは収集されていません。')
        return ('固定観測コレクタが停止しています。セッションは「観測中」のままですが、'
                '現在データは収集されていません。')

    def _no_connection_note(self, session, now=None):
        """Note for a running fixed session that has never connected.

        Waiting offline is legitimate, so this is not an alarm: it
        states the fact and the ambiguity. After the grace period a
        session with zero connected time is just as consistent with
        a mistyped ID or a login-required profile as with a streamer
        who simply has not gone live — the user cannot tell from a
        plain '待機中', and a zero-record report at the end should
        not be the first time they learn nothing was collected.
        """
        if session is None or not self._is_fixed_source():
            return ''
        if session.get('end_kind') != 'running':
            return ''
        now = time.time() if now is None else now
        if now - float(session.get('started_at') or now) < 300:
            return ''
        if float(session.get('monitored_seconds') or 0) > 0:
            return ''
        return ('開始から接続が確立した時間がありません。対象が配信していない場合は'
                '待機が正常ですが、IDの誤りやログインが必要な状態でも同じ表示に'
                'なります。')

    def _update_collector_status(self):
        if not self._is_fixed_source():
            self.collector_label.configure(text='固定観測ではありません')
            self.observing_label.configure(text='—')
            return
        try:
            controller = get_fixed_controller(self._source['capture_dir'])
            state = controller.status()
        except Exception:
            self.collector_label.configure(text='状態を取得できません')
            return
        text = state['label']
        if state.get('last_data'):
            text += f" ／ 最終データ {format_jst(state['last_data'])}"
        self.collector_label.configure(text=text)
        # Show the ACTUAL observation target, kept distinct from the
        # registered ID: a running session's targets are authoritative,
        # then our controller's target, then an external holder's.
        observing = ''
        active = next((s for s in self._sessions
                       if s['session_id'] == self._active_session_id), None)
        if active and active.get('targets'):
            observing = str(active['targets'][0])
        elif state.get('running') and state.get('target_id'):
            observing = str(state['target_id'])
        elif state.get('state') == 'conflict':
            external = state.get('external_target') or ''
            self.observing_label.configure(
                text=f'別の固定観測が動作中です（対象 @{external}）'
                     '。この画面からは開始・停止できません' if external else
                     '別の固定観測が動作中です。この画面からは開始・停止できません')
            return
        if observing:
            note = f'@{observing}'
            registered = get_pro_tiktok_id()
            if registered and registered != observing:
                note += '（登録IDと異なります。変更は次回の分析開始から反映されます）'
            if active is not None and self._fixed_collection_alert(active):
                note += '（コレクタ停止中：現在は収集していません）'
            self.observing_label.configure(text=note)
        else:
            self.observing_label.configure(text='—')

    def _streamer_locked(self):
        """True while the streamer workspace is active.

        Read fresh from settings on every call, so a page that
        outlives a workspace switch still enforces the current
        workspace's rule. Only the developer workspace may leave
        the fixed-observation source.
        """
        return self._workspace.get_mode() != MODE_DEVELOPER

    def change_source(self):
        label = self.source_menu.get()
        target = next((s for s in self._sources if s['label'] == label),
                      None)
        if (target is not None and target.get('key') != 'capture_fixed'
                and self._streamer_locked()):
            # Streamer workspace: fixed observation only. Refuse the
            # switch even when change_source is invoked
            # programmatically, and snap the selector back so the UI
            # never claims another source is in use.
            fixed = next((s for s in self._sources
                          if s.get('key') == 'capture_fixed'), None)
            if fixed is not None:
                self.source_menu.set(fixed['label'])
                if self._source is not fixed:
                    self._source = fixed
                    self._runtime = get_runtime(fixed['capture_dir'])
                    self._load_gen += 1
                    self._display_gen += 1
                    self._display_request = None
                    self._report = None
                    self.refresh()
            return
        if target is not None:
            self._source = target
        self._runtime = get_runtime(self._source['capture_dir']) if self._source else None
        self._active_session_id = None
        self._running_started_at = None
        # The old source's report/refresh state must not leak into the
        # new source: invalidate in-flight display results and let the
        # auto display retarget to this source's latest session.
        self._load_gen += 1
        self._display_gen += 1
        self._set_generating(False)
        self._display_request = None
        self._report = None
        self._selected_battle = None
        self._history_sessions = []
        self._history_summaries = {}
        self._history_error = None
        self._history_page = 0
        self._history_signature = None
        self.refresh()

    def refresh(self):
        if self._busy:
            # A load is already in flight. Do not drop this request:
            # record it, and the pump runs it as soon as the current
            # load finishes (a bare skip could leave the session list
            # and the history stale until the next periodic cycle —
            # and a caller waiting on fresh data would time out).
            self._refresh_pending = True
            return
        self._busy = True
        runtime = self._runtime
        database = self._source['database'] if self._source else None
        gen = self._load_gen

        def worker():
            try:
                sessions, recovered = [], []
                history_sessions, summaries, history_error = [], {}, None
                if runtime is not None:
                    # Guarded recovery: sessions owned by this process,
                    # or with a fresh heartbeat, are never interrupted.
                    recovered = runtime.store.recover_interrupted()
                    runtime.ensure_all_sampling()
                    sessions = runtime.store.list_sessions(limit=50)
                    try:
                        history_sessions = runtime.store.list_sessions_basic(
                            limit=1000)
                        if database is not None:
                            summaries = session_summaries(database,
                                                          history_sessions)
                    except Exception as exc:
                        # The history tab distinguishes "no history
                        # yet" from "history failed to load".
                        logging.exception('history load failed')
                        history_sessions, summaries = [], {}
                        history_error = str(exc)
                self._queue.put(('sessions', gen, sessions, recovered))
                self._queue.put(('history', gen, history_sessions,
                                 summaries, history_error))
            except Exception as exc:  # never break the page on store errors
                logging.exception('session load failed')
                self._queue.put(('error', gen,
                                 f'セッションの読み込みに失敗しました: {exc}'))
            finally:
                self._busy = False

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------ display auto-refresh
    def _auto_refresh(self):
        """Periodic while the page is open (~6s from the pump tick):
        reload the session list and re-aggregate the on-screen report
        from the latest database rows. Read-only — see generate() for
        the file-writing path; the two never mix."""
        if not self._alive:
            return
        self.refresh()
        self._start_display_refresh()

    def _display_target_session(self):
        running = next((s for s in self._sessions if s['end_kind'] == 'running'), None)
        return running or (self._sessions[0] if self._sessions else None)

    def _retarget_display(self):
        """Aim an AUTO display request at the live session (or the
        latest one). A request the user generated explicitly (session
        指定・配信者・期間) is sticky and never retargeted."""
        target = self._display_target_session()
        if target is None:
            return
        req = self._display_request
        if req is not None and not req.get('auto'):
            return
        if req is not None and req.get('session_id') == target['session_id']:
            return
        self._display_request = {'scope': {'kind': 'session'},
                                 'session_id': target['session_id'],
                                 'auto': True}
        self._display_gen += 1

    def _start_display_refresh(self):
        """Aggregate the current display request in a worker thread.

        One aggregation at a time (an in-flight one is never
        duplicated), never while a manual generate() runs, and the
        result is applied only when its generation is still current
        when it lands — a session switch or source change in the
        meantime drops it instead of overwriting the newer view.
        """
        if not self._alive or self._source is None:
            return
        if self._display_inflight is not None or self._generating:
            return
        req = self._display_request
        if req is None:
            return
        scope = dict(req['scope'])
        session = None
        if scope.get('kind') == 'session':
            session = next((s for s in self._sessions
                            if s['session_id'] == req.get('session_id')), None)
            if session is None and self._runtime is not None:
                # A history entry older than the detail list's window:
                # load that one session on demand.
                try:
                    session = self._runtime.store.get_session(req.get('session_id'))
                except Exception:
                    session = None
            if session is None:
                if req.get('auto'):
                    self._display_request = None
                return
        gen = self._display_gen
        self._display_inflight = gen
        source = self._source

        def worker():
            try:
                report = build_report(source['database'], scope, session=session,
                                      profile=source['profile'],
                                      generation_trigger='display')
                self._queue.put(('display_report', gen, report))
            except Exception as exc:
                logging.exception('display refresh failed')
                self._queue.put(('display_error', gen,
                                 f'表示の自動更新に失敗しました: {exc}'))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------ history tab
    def _filtered_history(self):
        text = self._history_filter_text.strip().lstrip('@').lower()
        date = self._history_filter_date.strip().replace('/', '-')
        out = []
        for session in self._history_sessions:
            if text:
                targets = ' '.join(session.get('targets') or []).lower()
                if (text not in targets
                        and text not in (session.get('mode') or '').lower()):
                    continue
            if date and not str(session.get('started_jst') or '').startswith(date):
                continue
            out.append(session)
        return out

    @staticmethod
    def _state_badge(end_kind):
        """(short label, background, foreground) for a session state.
        Colour supports the text, never replaces it."""
        if end_kind == 'running':
            return '観測中', '#D9F7E8', '#0E7A44'
        if end_kind == 'normal':
            return '正常終了', '#E3EBFA', '#2F5AA8'
        if end_kind == 'interrupted':
            return '中断', '#FDEBD2', '#9A6206'
        if end_kind == 'abnormal':
            return '異常終了', '#FFDEE4', '#B32346'
        return END_LABELS.get(end_kind, str(end_kind)), '#E8ECF2', '#5B6B82'

    def _history_card_texts(self, session):
        """(date, targets, stats_rows) for one history card.

        stats_rows is a list of rows of (caption, value) pairs laid
        out as two short lines — never one long sentence, which
        wrapped into awkward fragments inside the narrow card."""
        summary = self._history_summaries.get(session['session_id'])
        targets = session.get('targets') or []
        targets_text = '、'.join(f'@{t}' for t in targets) if targets else '対象指定なし'
        started = datetime.fromtimestamp(session['started_at'], JST)
        date_text = f'{started.month}月{started.day}日 {started:%H:%M}'
        duration = duration_clock(session.get('elapsed_seconds'))
        if summary is None:
            return date_text, targets_text, None
        best = summary['final_score_max']
        best_text = f'{best:,}' if best is not None else '未取得'
        rows = [[('観測時間：', duration),
                 ('バトル：', f"{summary['record_count']}件")],
                [('確定：', f"{summary['score_known_battles']}件"),
                 ('最大スコア：', best_text)]]
        return date_text, targets_text, rows

    def _update_viewing_label(self):
        """Refresh the detail header (title / state badge / mode
        line) so it always names the session actually on display —
        current observation and past history are never conflated."""
        if not hasattr(self, 'history_viewing_label'):
            return
        report_session = (self._report or {}).get('session') or {}
        session = None
        if report_session.get('session_id'):
            session = next((s for s in self._history_sessions + self._sessions
                            if s['session_id'] == report_session['session_id']),
                           None) or report_session
        req = self._display_request
        if session is not None:
            targets = session.get('targets') or []
            targets_text = ('、'.join(f'@{t}' for t in targets)
                            if targets else '対象指定なし')
            started_jst = session.get('started_jst') or format_jst(session['started_at'])
            self.detail_title_label.configure(
                text=f'{started_jst} ／ {targets_text}')
            label, bg, fg = self._state_badge(session.get('end_kind'))
            self.detail_badge.configure(text=label, fg_color=bg, text_color=fg)
        else:
            self.detail_title_label.configure(text='読み込んでいます…')
            self.detail_badge.configure(text='', fg_color='transparent')
        if req is None or req.get('auto'):
            text = '最新の観測を表示中'
        elif req.get('session_id'):
            text = '過去の配信を表示中（自動更新はこの配信に対して行われます）'
        else:
            text = '詳細設定で指定した条件の集計を表示中'
        self.history_viewing_label.configure(text=text)

    def _render_history(self):
        if not hasattr(self, 'history_list'):
            return
        self._update_viewing_label()
        filtered = self._filtered_history()
        pages = max(1, (len(filtered) + self.HISTORY_PAGE_SIZE - 1)
                    // self.HISTORY_PAGE_SIZE)
        self._history_page = min(self._history_page, pages - 1)
        start = self._history_page * self.HISTORY_PAGE_SIZE
        visible = filtered[start:start + self.HISTORY_PAGE_SIZE]
        displayed = (self._report or {}).get('session') or {}
        displayed_id = displayed.get('session_id')
        if self._history_error:
            note = f'履歴の読み込みに失敗しました: {self._history_error}'
        elif not self._history_sessions:
            note = ('まだ観測履歴がありません。配信分析を開始すると、'
                    'ここに履歴が残ります。')
        elif not filtered:
            note = '条件に一致する履歴がありません。'
        else:
            note = ''
        signature = (
            tuple((s['session_id'], s['end_kind'],
                   (self._history_summaries.get(s['session_id']) or {}).get('record_count'),
                   (self._history_summaries.get(s['session_id']) or {}).get('score_known_battles'),
                   (self._history_summaries.get(s['session_id']) or {}).get('final_score_max'))
                  for s in visible),
            displayed_id, note, self._history_page, pages, len(filtered))
        if signature == self._history_signature:
            return
        self._history_signature = signature
        fraction = self._scroll_fraction(self.history_list)
        for child in self.history_list.winfo_children():
            child.destroy()
        self._history_cards = {}
        for session in visible:
            card = self._build_history_card(session,
                                            session['session_id'] == displayed_id)
            self._history_cards[session['session_id']] = card
        self.history_note.configure(
            text=note, text_color=theme.DANGER if self._history_error else MUTED)
        self.history_page_label.configure(
            text=f'{self._history_page + 1} / {pages} ページ（全{len(filtered)}件）')
        self.history_prev_button.configure(
            state='normal' if self._history_page > 0 else 'disabled')
        self.history_next_button.configure(
            state='normal' if self._history_page < pages - 1 else 'disabled')
        self._restore_scroll(self.history_list, fraction)

    def _build_history_card(self, session, selected):
        """One clickable history card: date + state badge on top,
        targets in the middle, observation stats at the bottom. The
        selected card gets a tinted background, a primary border and
        a left accent bar so the current selection is unmistakable."""
        card = ctk.CTkFrame(
            self.history_list, corner_radius=10,
            fg_color='#EAF1FE' if selected else '#FFFFFF',
            border_width=2 if selected else 1,
            border_color=theme.PRIMARY if selected else '#D5DCE8')
        card.pack(fill='x', padx=4, pady=3)
        card.session_id = session['session_id']
        # height=1: an empty CTkFrame otherwise requests its 200px
        # default height and inflates the whole card.
        accent = ctk.CTkFrame(card, width=5, height=1, corner_radius=0,
                              fg_color=theme.PRIMARY if selected else 'transparent')
        accent.pack(side='left', fill='y')
        inner = ctk.CTkFrame(card, fg_color='transparent')
        inner.pack(side='left', fill='both', expand=True, padx=(9, 10), pady=5)
        date_text, targets_text, stats_rows = self._history_card_texts(session)
        top = ctk.CTkFrame(inner, fg_color='transparent')
        top.pack(fill='x')
        date_label = ctk.CTkLabel(
            top, text=date_text, text_color=TEXT, anchor='w',
            font=(theme.FONT_FAMILY, 14, 'bold'))
        date_label.pack(side='left')
        badge_text, badge_bg, badge_fg = self._state_badge(session['end_kind'])
        badge_label = ctk.CTkLabel(
            top, text=badge_text, width=76, corner_radius=9,
            fg_color=badge_bg, text_color=badge_fg,
            font=(theme.FONT_FAMILY, theme.FONT_SMALL, 'bold'))
        badge_label.pack(side='right')
        target_label = ctk.CTkLabel(inner, text=targets_text, text_color=MUTED,
                                    anchor='w')
        target_label.pack(fill='x', pady=(1, 0))
        if stats_rows is None:
            duration = duration_clock(session.get('elapsed_seconds'))
            ctk.CTkLabel(inner, text=f'観測時間：{duration} ・ バトル集計は未取得',
                         text_color=MUTED, anchor='w').pack(fill='x', pady=(1, 0))
        else:
            for row in stats_rows:
                line = ctk.CTkFrame(inner, fg_color='transparent')
                line.pack(fill='x', pady=(1, 0))
                for caption, value in row:
                    ctk.CTkLabel(line, text=caption, text_color=MUTED,
                                 anchor='w').pack(side='left', padx=(0, 0))
                    ctk.CTkLabel(line, text=value, text_color=TEXT, anchor='w',
                                 font=(theme.FONT_FAMILY, theme.FONT_BODY,
                                       'bold')).pack(side='left',
                                                      padx=(0, 10))
        sid = session['session_id']

        def _click(_event, sid=sid):
            self.show_history_session(sid)

        def _bind(widget):
            widget.bind('<Button-1>', _click)
            for child in widget.winfo_children():
                _bind(child)

        _bind(card)
        return card

    def show_history_session(self, session_id):
        """Show one past session, read-only (history card click).

        Sticky like a manual generate() — the auto refresh keeps
        re-aggregating THIS session and never jumps back to the
        latest — but viewing never writes a report file."""
        self._display_gen += 1
        self._display_request = {'scope': {'kind': 'session'},
                                 'session_id': session_id, 'auto': False}
        self.tabs.set('概要')
        self._render_history()
        self._start_display_refresh()

    def show_latest_display(self):
        """Back to following the latest / running session (read-only)."""
        self._display_gen += 1
        self._display_request = None
        self._retarget_display()
        self._render_history()
        self._start_display_refresh()

    def apply_history_filter(self):
        self._history_filter_text = self.history_filter_entry.get()
        self._history_filter_date = self.history_date_entry.get()
        self._history_page = 0
        self._history_signature = None
        self._render_history()

    def clear_history_filter(self):
        self.history_filter_entry.delete(0, 'end')
        self.history_date_entry.delete(0, 'end')
        self._history_filter_text = ''
        self._history_filter_date = ''
        self._history_page = 0
        self._history_signature = None
        self._render_history()

    def history_prev_page(self):
        if self._history_page > 0:
            self._history_page -= 1
            self._render_history()

    def history_next_page(self):
        self._history_page += 1
        self._render_history()

    def _render_sessions(self, recovered):
        previous = self._selected_session()
        labels = []
        for session in self._sessions:
            labels.append(f"{session['started_jst']} / {session['mode']} / "
                          f"{END_LABELS.get(session['end_kind'], session['end_kind'])}")
        self.session_menu.configure(values=labels or ['セッションなし'])
        if labels:
            chosen = labels[0]
            if previous is not None:
                for session, text in zip(self._sessions, labels):
                    if session['session_id'] == previous['session_id']:
                        chosen = text
                        break
            self.session_menu.set(chosen)
        running = next((s for s in self._sessions if s['end_kind'] == 'running'), None)
        latest = self._sessions[0] if self._sessions else None
        current = running or latest
        alert = self._fixed_collection_alert(running)
        if running is not None:
            self._active_session_id = running['session_id']
            self._running_started_at = running['started_at']
            # A running session whose collector is gone must not look
            # like healthy observation.
            self.badge.set_status('collector_stopped' if alert else 'running')
            self.stop_button.configure(state='normal')
            self.start_button.configure(state='disabled')
            self.elapsed_label.configure(
                text=duration_clock(time.time() - running['started_at']))
        else:
            self._active_session_id = None
            self._running_started_at = None
            self.stop_button.configure(state='disabled')
            self.start_button.configure(state='disabled' if self._is_topwatch() else 'normal')
            if latest is not None:
                self.badge.set_status(latest['end_kind'])
                self.elapsed_label.configure(text=duration_clock(latest.get('elapsed_seconds')))
            else:
                self.badge.set_status('none')
                self.elapsed_label.configure(text='—')
        if current is not None:
            targets = current.get('targets') or []
            target_text = '、'.join(f'@{t}' for t in targets) if targets else '指定なし'
            source_label = self._source['label'] if self._source else 'データなし'
            self.target_label.configure(text=f'{source_label} ／ {target_text}')
            self.started_label.configure(text=current['started_jst'])
            self.session_id_label.configure(text=f"セッションID: {current['session_id']}")
        else:
            self.target_label.configure(text='未選択')
            self.started_label.configure(text='—')
            self.session_id_label.configure(text='セッションID: —')
        note = f'前回の未完了セッション{len(recovered)}件を「中断」として記録しました。' if recovered else ''
        if alert:
            note = f'⚠ {alert} ' + note
        no_conn = self._no_connection_note(current)
        if no_conn:
            note = f'{no_conn} ' + note
        self.status.configure(text=note + ('TopWatchのデータは参照のみです（セッション開始は対象プロセス側）。'
                                           if self._is_topwatch() else
                                           'セッション終了時にレポートJSONを自動生成します（画面は自動更新・PDF・AI分析は手動操作です）。'))
        self._update_collector_status()
        # Opening the page (or a session starting/stopping) shows the
        # latest session's aggregation without waiting for a button:
        # retarget the auto display request, and aggregate immediately
        # when nothing is on screen yet or the target just changed.
        # The periodic tick covers the steady-state updates.
        display_gen_before = self._display_gen
        self._retarget_display()
        if self._report is None or self._display_gen != display_gen_before:
            self._start_display_refresh()

    def _targets(self):
        raw = self.target_entry.get() or ''
        return [part.strip().lstrip('@') for part in raw.replace('、', ',').split(',')
                if part.strip()]

    def start_session(self):
        if self._transition:
            return  # a start/stop is already in flight (double-click guard)
        if self._source is None or self._is_topwatch() or self._runtime is None:
            return
        self._transition = True
        self.start_button.configure(state='disabled')
        self.stop_button.configure(state='disabled')
        try:
            self._start_session_inner()
        finally:
            self._transition = False
            self.refresh()

    def _start_session_inner(self):
        if self._is_fixed_source():
            # Pulse Pro standard flow: the registered account is the
            # observation target. Save the ID first (this only sets the
            # target; it is NOT ownership verification), then start the
            # fixed collector for that account and bind the session to
            # it ONLY when the collector provably observes that ID
            # (start_ex), so another streamer's observation can never
            # be bound to this streamer's session.
            try:
                tiktok_id = set_pro_tiktok_id(
                    self.account_entry.get() or get_pro_tiktok_id())
            except ValueError as exc:
                messagebox.showerror('自分のTikTok ID', str(exc))
                return
            except (SettingsSaveError, SettingsLoadError) as exc:
                # Without a saved target ID, neither the collector
                # nor a session may start.
                messagebox.showerror(
                    '設定保存エラー',
                    'TikTok IDを保存できなかったため、配信分析を開始しませんでした。'
                    '既存の設定は変更されていません。時間をおいて再度お試しください。\n\n'
                    f'{exc}')
                return
            self.account_entry.delete(0, 'end')
            self.account_entry.insert(0, tiktok_id)
            controller = get_fixed_controller(self._source['capture_dir'])
            try:
                result = controller.start_ex(tiktok_id)
            except Exception as exc:
                logging.exception('fixed collector start failed')
                messagebox.showerror('配信分析', f'固定観測を開始できませんでした: {exc}')
                return
            outcome = result['outcome']
            if outcome == 'already_other':
                messagebox.showwarning(
                    '配信分析',
                    f'固定観測は既に別のID（@{result["target_id"]}）で動作しています。\n'
                    '対象を切り替えるには、先に「配信分析を終了」を押して現在の観測を'
                    '終了してください。今回はセッションを開始しませんでした。')
                return
            if outcome == 'conflict':
                other = result.get('target_id') or ''
                messagebox.showwarning(
                    '配信分析',
                    '別の固定観測が既に動作しているため開始できませんでした'
                    + (f'（対象 @{other}）' if other else '')
                    + '。\nTop固定観測など、他の固定観測を停止してからお試しください。'
                      '今回はセッションを開始しませんでした。')
                return
            if outcome != 'started' and outcome != 'already_same':
                messagebox.showerror(
                    '配信分析',
                    '固定観測を開始できませんでした: '
                    + str(result.get('message') or '起動を確認できませんでした')
                    + '\nセッションは開始していません。')
                return
            try:
                session = self._runtime.start_session('固定観測', [tiktok_id],
                                                      profile='capture_fixed')
            except Exception as exc:
                logging.exception('session start failed after collector start')
                if outcome == 'started':
                    controller.stop()  # roll back only the collector WE started
                messagebox.showerror('配信分析', f'セッションを開始できませんでした: {exc}')
                return
            self._active_session_id = session['session_id']
            self._running_started_at = session['started_at']
            self.badge.set_status('running')
            self.status.configure(
                text=f'配信分析を開始しました（固定観測: @{tiktok_id}）。'
                     '配信がオフラインの間は「待機中」と表示されます。'
                     '画面を切り替えても記録は継続します。')
            self._update_collector_status()
            return
        session = self._runtime.start_session(self.mode_menu.get(), self._targets(),
                                              profile=self._source['profile'])
        self._active_session_id = session['session_id']
        self._running_started_at = session['started_at']
        self.badge.set_status('running')
        self.status.configure(text='分析を開始しました。画面を切り替えても記録は継続します。')

    def stop_session(self):
        if self._transition:
            return  # double-click guard
        if self._active_session_id is None or self._runtime is None:
            return
        self._transition = True
        self.start_button.configure(state='disabled')
        self.stop_button.configure(state='disabled')
        need_refresh = True
        try:
            if self._is_fixed_source():
                # Ordering (Phase 4 review): the collector must be
                # CONFIRMED stopped before the session is closed as a
                # normal end and its final JSON is generated, so the
                # JSON is built from complete data and no collector
                # writes can land after the session's end.
                try:
                    collector_stopped = get_fixed_controller(
                        self._source['capture_dir']).stop()
                except Exception:
                    logging.exception('fixed collector stop failed')
                    collector_stopped = False
                if not collector_stopped:
                    # Never record a normal end the data does not
                    # support: the session stays running (collection
                    # state unchanged) and the user can retry. No
                    # refresh here — re-rendering would overwrite this
                    # message; the buttons are restored directly.
                    need_refresh = False
                    self.stop_button.configure(state='normal')
                    self.status.configure(
                        text='固定観測の停止を確認できなかったため、セッションを終了しませんでした。'
                             '観測は継続しています。もう一度「配信分析を終了」を押してください。')
                    self._update_collector_status()
                    return
            try:
                self._runtime.stop_session(self._active_session_id,
                                           end_kind='normal')
            except Exception:
                # The collector is already confirmed stopped, but the
                # session record could not be closed (e.g. the
                # sessions database was momentarily locked). Never let
                # the exception escape the button handler and never
                # claim the session ended: it stays 'running' in the
                # record, the collector-stopped alert will show, and
                # pressing stop again retries the close.
                logging.exception('session stop failed')
                need_refresh = False
                self.stop_button.configure(state='normal')
                self.status.configure(
                    text='セッションの終了処理に失敗しました（記録用データベースが'
                         '使用中だった可能性があります）。セッションは継続中として'
                         '残っています。もう一度「配信分析を終了」を押してください。')
                self._update_collector_status()
                return
            self.badge.set_status('normal')
            self.status.configure(
                text='配信分析を終了しました。レポートJSONは自動生成されます（画面集計・PDF・AIは手動）。')
            self._active_session_id = None
            self._running_started_at = None
            self._update_collector_status()
        finally:
            self._transition = False
            if need_refresh:
                self.refresh()

    # ------------------------------------------------------------ report
    def _selected_session(self):
        label = self.session_menu.get()
        for session, text in zip(self._sessions, [
                f"{s['started_jst']} / {s['mode']} / {END_LABELS.get(s['end_kind'], s['end_kind'])}"
                for s in self._sessions]):
            if text == label:
                return session
        return None

    def _reports_dir(self):
        return Path(self._source['capture_dir']) / 'observation_report' / 'reports'

    def _previous_report_path(self, before):
        folder = self._reports_dir()
        if not folder.exists():
            return None
        candidates = sorted(folder.glob('report_*.json'))
        earlier = [p for p in candidates if p.stat().st_mtime < before]
        return earlier[-1] if earlier else None

    def show_latest_report(self):
        """Header shortcut: aggregate the latest session (or all data)."""
        if self._sessions:
            self.scope_menu.set('最新セッション')
        self.generate()

    def generate(self):
        if self._source is None:
            messagebox.showinfo('配信レポート', '読み取りできるデータがありません。')
            return
        scope_kind = self.scope_menu.get()
        session = None
        scope = {'kind': 'all'}
        if scope_kind in ('最新セッション', 'セッション指定'):
            session = (self._sessions[0] if self._sessions else None) \
                if scope_kind == '最新セッション' else self._selected_session()
            if session is None:
                messagebox.showinfo('配信レポート', '対象セッションがありません。先に「分析を開始」してください。')
                return
            scope = {'kind': 'session'}
        elif scope_kind == '配信者':
            targets = self._targets()
            if not targets:
                messagebox.showinfo('配信レポート', '対象の@IDを詳細設定で入力してください。')
                return
            scope = {'kind': 'streamer', 'streamers': targets}
        elif scope_kind == '期間':
            try:
                start = datetime.strptime(self.period_start.get().strip(), '%Y-%m-%d').replace(tzinfo=JST)
                end = datetime.strptime(self.period_end.get().strip(), '%Y-%m-%d').replace(tzinfo=JST) \
                    + timedelta(days=1) - timedelta(seconds=1)
            except ValueError:
                messagebox.showinfo('配信レポート', '期間は YYYY-MM-DD で入力してください。')
                return
            scope = {'kind': 'period', 'start': start.timestamp(), 'end': end.timestamp(),
                     'streamers': self._targets()}
        # A manual generation supersedes any display refresh in
        # flight, and the auto refresh from here on re-aggregates
        # exactly what the user asked to see (read-only).
        self._display_gen += 1
        self._display_request = {'scope': dict(scope),
                                 'session_id': session['session_id'] if session else None,
                                 'auto': False}
        self._set_generating(True)
        self.status.configure(text='集計中…（収集は継続しています）')
        source = self._source

        gen = self._load_gen
        def worker():
            try:
                began = time.time()
                report = build_report(source['database'], scope, session=session,
                                      profile=source['profile'])
                folder = self._reports_dir()
                folder.mkdir(parents=True, exist_ok=True)
                previous_path = self._previous_report_path(began)
                stamp = datetime.now(JST).strftime('%Y%m%d_%H%M%S')
                export_json(report, folder / f'report_{stamp}.json')
                if session is not None:
                    get_runtime(source['capture_dir']).store.mark_report(
                        session['session_id'], 'generated')
                self._queue.put(('report', gen, report, previous_path))
            except Exception as exc:
                logging.exception('report build failed')
                self._queue.put(('error', gen,
                                 f'レポート生成に失敗しました: {exc}'))

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _scroll_fraction(frame):
        try:
            return frame._parent_canvas.yview()[0]
        except Exception:
            return None

    def _restore_scroll(self, frame, fraction):
        if not self._alive:
            return
        try:
            frame._parent_canvas.yview_moveto(fraction)
        except Exception:
            pass

    def _render_report(self, previous_path, display_only=False):
        self._set_generating(False)
        report = self._report
        summary = report['summary']
        self.empty_label.configure(
            text=f"観測期間: {summary['window_start_jst']} 〜 {summary['window_end_jst']}"
                 '（この期間に観測できたデータの集計です。配信全体の成果ではありません）')
        for card, item in zip(self.kpi_cards, kpi_items(report)):
            card.set_value(item['value'], item['sub'])
            if item.get('value_size'):
                card._value.configure(font=(theme.FONT_FAMILY, item['value_size'], 'bold'))

        lines = [
            f"観測対象数: {summary['streamer_count']} / 記録バトル数: {summary['record_count']}"
            f"（ユニーク {summary['unique_battle_count']} 件）",
            f"実際に監視できた時間: {duration_text(summary['monitored_seconds'])} / "
            f"接続中断: {duration_text(summary['disconnected_seconds'])}",
            f"最終スコア確定（終了確認済み）: {summary['score_known_battles']} / それ以外: {summary['score_unknown_battles']}",
            f"終了未確認で参考スコアがあるバトル: {summary.get('last_known_score_battles', 0)}（最終スコアには含めていません）",
            f"期間をまたいだバトル: {summary.get('window_clipped_battles', 0)}（集計は期間内サンプルのみ）",
            f"スコアの記録回数: {summary['score_sample_total']} / 視聴者数の記録回数: {summary['viewer_sample_total']}",
            f"途中から観測したバトル: {summary['partial_battles']}（完全な成績としては扱いません）",
            f"データ未取得区間: {summary['gap_count']} 件（0では補完していません）",
            f"接続中断・収集エラー: {number(summary['error_count']) if summary['error_count'] is not None else '実測不可（セッション指定時のみ）'}",
            '',
            '配信者別:',
        ]
        for row in report['per_streamer']:
            lines.append(
                f"  {row['nickname']} (@{row['unique_id']}): 記録{row['records']}件 / "
                f"スコア中央値 {number(row['score_median'])} / 最大 {number(row['score_max'])} / "
                f"視聴者中央値 {number(row['viewer_median'])}")
        lines += ['', '注意事項:'] + ['・' + note for note in report['data_notes']]
        self._set_text(self.summary_box, '\n'.join(lines))

        definitions = ['用語の定義:'] + \
            [f'・{key}: {value}' for key, value in (report.get('definitions') or {}).items()] + \
            ['', 'データの注意事項:'] + ['・' + note for note in report['data_notes']]
        self._set_text(self.definitions_box, '\n'.join(definitions))

        # Keep the user's place across re-renders (auto refresh must
        # not yank the battle selection or the list scroll): remember
        # the selected battle by identity and the list's scroll top.
        selected_key = None
        if self._selected_battle is not None:
            selected_key = (self._selected_battle.get('unique_id'),
                            self._selected_battle.get('battle_id'))
        scroll_fraction = self._scroll_fraction(self.battles_scroll)
        self._render_battle_list(report['battles'])
        if scroll_fraction is not None:
            self.after_idle(lambda f=scroll_fraction:
                            self._restore_scroll(self.battles_scroll, f))
        labels = [f"{b['nickname']} / {b['first_seen_jst']}" for b in report['battles']]
        self.battle_menu.configure(values=labels or ['バトル未取得'])
        if labels:
            chosen = report['battles'][0]
            if selected_key is not None:
                for battle in report['battles']:
                    if (battle.get('unique_id'), battle.get('battle_id')) == selected_key:
                        chosen = battle
                        break
            self.battle_menu.set(f"{chosen['nickname']} / {chosen['first_seen_jst']}")
            self._selected_battle = chosen
        else:
            self._selected_battle = None
        self._render_battle_detail()
        self.draw_charts()
        try:
            self._set_text(self.ai_preview, evidence_preview(report))
        except Exception:
            self._set_text(self.ai_preview, 'プレビューを生成できませんでした。')

        if display_only:
            # No file was written and nothing was marked as generated;
            # the comparison box (a manual-generation feature) stays
            # exactly as it was.
            self.status.configure(
                text='表示を最新の観測データに更新しました（この更新ではファイルは保存していません）。')
            self._render_history()
            return

        comparison_text = '比較できる前回レポートがありません。'
        if previous_path is not None:
            try:
                previous = json.loads(Path(previous_path).read_text(encoding='utf-8'))
                report['comparison'] = compare_reports(report, previous)
                rows = [f"前回: {report['comparison']['previous_generated_jst']}"]
                for row in report['comparison']['rows']:
                    delta = '比較不可' if not row['comparable'] else f"{row['delta']:+,}"
                    rows.append(f"{row['label']}: 前回 {number(row['previous'])} → "
                                f"今回 {number(row['current'])}（差 {delta}）")
                comparison_text = '\n'.join(rows)
            except (OSError, ValueError) as exc:
                comparison_text = f'前回レポートを読み込めませんでした: {exc}'
        self._set_text(self.compare_box, comparison_text)
        self.status.configure(text='レポートを表示しました。JSONは observation_report/reports に保存済みです。')
        self._render_history()

    # ------------------------------------------------------------ battles / charts
    def _render_battle_list(self, battles):
        for child in self.battles_scroll.winfo_children():
            child.destroy()
        if not battles:
            ctk.CTkLabel(self.battles_scroll, text='この条件で観測できたバトルはありません。',
                         text_color=MUTED).pack(pady=16)
            return
        for battle in battles:
            row = ctk.CTkFrame(self.battles_scroll, fg_color=CARD, corner_radius=theme.RADIUS_SMALL,
                               border_width=1, border_color=theme.BORDER)
            row.pack(fill='x', padx=4, pady=4)
            row.grid_columnconfigure(0, weight=1)
            main = ctk.CTkFrame(row, fg_color='transparent')
            main.grid(row=0, column=0, sticky='ew', padx=12, pady=8)
            ctk.CTkLabel(main, text=f"{short_name(battle['nickname'])}（@{battle['unique_id']}）",
                         text_color=TEXT, anchor='w',
                         font=(theme.FONT_FAMILY, 14, 'bold')).pack(anchor='w')
            partial = PARTIAL_LABELS.get(battle['partial_state'], '')
            if battle['window_clipped']:
                partial += '・期間をまたぐ'
            ctk.CTkLabel(
                main, text_color=MUTED, anchor='w', justify='left', wraplength=780,
                text=f"{battle['first_seen_jst']} ／ {format_mode(battle['mode'])} ／ "
                     f"最終スコア {battle_score_text(battle)} ／ "
                     f"視聴者 中央値 {number(battle['viewer_median'])}・最大 {number(battle['viewer_peak'])} ／ "
                     f"{battle['status_label']} ／ {partial}").pack(anchor='w')
            ctk.CTkButton(row, text='詳細', width=72,
                          command=lambda b=battle: self._open_battle(b)).grid(
                              row=0, column=1, padx=10, pady=8)

    def _open_battle(self, battle):
        self._selected_battle = battle
        if self._report:
            labels = [f"{b['nickname']} / {b['first_seen_jst']}" for b in self._report['battles']]
            for text, item in zip(labels, self._report['battles']):
                if item is battle:
                    self.battle_menu.set(text)
                    break
        self.tabs.set('概要')
        self._render_battle_detail()
        self.draw_charts()

    def _render_battle_detail(self):
        battle = self._selected_battle
        if not battle:
            self.battle_detail.configure(text='バトルが選択されていません。')
            return
        partial = PARTIAL_LABELS.get(battle['partial_state'], '')
        if battle['window_clipped']:
            partial += '・期間をまたぐ（期間内サンプルのみ集計）'
        self.battle_detail.configure(
            text=f"{battle['nickname']}（@{battle['unique_id']}） ／ {battle['first_seen_jst']} 開始観測 ／ "
                 f"{format_mode(battle['mode'])} ／ 状態: {battle['status_label']} ／ "
                 f"最終スコア: {battle_score_text(battle)} ／ "
                 f"視聴者 中央値 {number(battle['viewer_median'])}・最大 {number(battle['viewer_peak'])} ／ "
                 f"スコア記録 {battle['score_sample_count']} 回・視聴者記録 {battle['viewer_sample_count']} 回 ／ "
                 f"未取得区間 {len(battle['gaps'])} 件 ／ {partial}")

    def select_battle(self):
        if not self._report:
            return
        label = self.battle_menu.get()
        for battle, text in zip(self._report['battles'],
                                [f"{b['nickname']} / {b['first_seen_jst']}"
                                 for b in self._report['battles']]):
            if text == label:
                self._selected_battle = battle
                break
        self._render_battle_detail()
        self.draw_charts()

    def draw_charts(self):
        self._draw_series(self.score_chart, 'score')
        self._draw_series(self.viewer_chart, 'viewer')

    def _draw_series(self, canvas, kind):
        canvas.delete('all')
        width = max(canvas.winfo_width(), 400)
        height = max(canvas.winfo_height(), 160)
        dark = ctk.get_appearance_mode() == 'Dark'
        bg = '#111C30' if dark else '#FFFFFF'
        grid = '#334155' if dark else '#E2E8F0'
        fg = '#F8FAFC' if dark else '#0F172A'
        canvas.configure(bg=bg)
        battle = self._selected_battle
        if not battle:
            canvas.create_text(20, 20, anchor='nw', text='データなし（レポートを表示すると描画されます）', fill=fg)
            return
        points = battle['score_series'] if kind == 'score' else battle['viewer_series']
        known = [p for p in points if p.get('v') is not None]
        if not known:
            canvas.create_text(20, 20, anchor='nw', text='未取得（このバトルの記録がありません）', fill=fg)
            return
        left, top, right, bottom = 70, 16, width - 16, height - 36
        t0, t1 = points[0]['t'], points[-1]['t']
        span = max(1.0, t1 - t0)
        vmax = max(p['v'] for p in known) or 1
        for frac in (0, 0.5, 1.0):
            y = bottom - (bottom - top) * frac
            canvas.create_line(left, y, right, y, fill=grid)
            canvas.create_text(6, y, anchor='w', text=f'{int(vmax * frac):,}', fill=fg)
        color = theme.PRIMARY if kind == 'score' else theme.SUCCESS
        previous = None
        for point in points:
            if point.get('v') is None:
                previous = None  # gap: never connect across missing data
                continue
            x = left + (right - left) * (point['t'] - t0) / span
            y = bottom - (bottom - top) * (point['v'] / vmax)
            if previous is not None:
                canvas.create_line(previous[0], previous[1], x, y, fill=color, width=2)
            previous = (x, y)
        canvas.create_text(left, bottom + 8, anchor='w', text=f'開始 {format_jst(t0)}', fill=fg)
        canvas.create_text(right, bottom + 8, anchor='e', text=f'終了 {format_jst(t1)}', fill=fg)

    # ------------------------------------------------------------ AI / export
    def _render_ai(self, answer):
        sections, found = split_ai_sections(answer)
        if found:
            for key, box in self.ai_boxes.items():
                self._set_text(box, sections.get(key) or '（この区分の記載はありませんでした）')
        else:
            self._set_text(self.ai_boxes['good'], answer)
            self._set_text(self.ai_boxes['summary'], '（AIの回答を区分できませんでした。全文を下に表示します）')
            self._set_text(self.ai_boxes['improve'], '（全文は「1. 良かった傾向」欄に表示しています）')
            self._set_text(self.ai_boxes['next'], '（全文は「1. 良かった傾向」欄に表示しています）')

    def run_ai(self):
        if self._report is None:
            messagebox.showinfo('AI改善提案', '先にレポートを表示してください。')
            return
        self.ai_button.configure(state='disabled')
        self.ai_status.configure(text='AI分析中…')
        report = self._report
        gen = self._load_gen

        def worker():
            try:
                payload, path, warning = ai_analyze(report)
                self._queue.put(('ai', gen, payload, path, warning))
            except Exception as exc:
                logging.exception('report AI failed')
                self._queue.put(('error', gen,
                                 f'AI分析に失敗しました（統計レポートは利用できます）: {exc}'))

        threading.Thread(target=worker, daemon=True).start()

    def export(self, kind):
        if self._report is None:
            messagebox.showinfo('レポート出力', '先にレポートを表示してください。')
            return
        stamp = datetime.now(JST).strftime('%Y%m%d_%H%M%S')
        specs = {'json': ('JSONファイル', '*.json', export_json),
                 'csv': ('CSVファイル', '*.csv', export_csv),
                 'pdf': ('PDFファイル', '*.pdf', None)}
        label, pattern, func = specs[kind]
        path = filedialog.asksaveasfilename(
            title=f'配信レポートを{kind.upper()}で保存', defaultextension=pattern[1:],
            initialfile=f'streaming_report_{stamp}{pattern[1:]}',
            filetypes=[(label, pattern), ('すべてのファイル', '*.*')])
        if not path:
            return
        try:
            if kind == 'pdf':
                export_pdf(self._report, path, ai_text=self._ai_text)
            else:
                func(self._report, path)
            self.status.configure(text=f'{kind.upper()}を保存しました: {path}')
        except Exception as exc:
            logging.exception('export failed')
            messagebox.showerror('レポート出力', f'保存に失敗しました: {exc}')
