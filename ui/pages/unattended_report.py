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
from core.observation_sessions import JST, format_jst, get_runtime
from core.report_ai import analyze as ai_analyze, evidence_preview
from core.report_export import export_csv, export_json, export_pdf
from core.unattended_report import available_sources, build_report, compare_reports
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
        self._tick = 0
        self._sources = available_sources()
        # Pulse Pro default: fixed observation (capture_fixed) of the
        # streamer's own registered account. Other sources stay
        # available on the 詳細設定 tab and never mix into this profile.
        self._source = next(
            (s for s in self._sources if s.get('key') == 'capture_fixed'),
            self._sources[0] if self._sources else None)
        # Session lifetime belongs to the process-wide runtime, not to
        # this page: leaving the page never stops session recording.
        self._runtime = get_runtime(self._source['capture_dir']) if self._source else None
        self._active_session_id = None
        self._running_started_at = None
        self._transition = False  # start/stop reentrancy guard (Phase 4)
        self._sessions = []
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
        ctk.CTkLabel(
            title_box, anchor='w', justify='left', wraplength=760, text_color=MUTED,
            text='Pulseが観測できたバトルと同時視聴者数の記録を集計します。'
                 '配信全体の成果ではなく、音声・発言内容は含みません。'
                 '取得できなかった情報は「未取得」と表示します。',
            font=(theme.FONT_FAMILY, theme.FONT_SMALL)).pack(anchor='w', pady=(2, 0))
        ctk.CTkButton(head, text='更新', width=70, command=self.refresh).pack(side='right', padx=4)

        # ------------------------------------------------ status / actions
        bar = SectionCard(self, '観測の状態')
        bar.grid(row=1, column=0, sticky='ew', padx=24, pady=(6, 6))
        info = ctk.CTkFrame(bar.body, fg_color='transparent')
        info.pack(side='left', fill='x', expand=True)
        row1 = ctk.CTkFrame(info, fg_color='transparent')
        row1.pack(fill='x')
        ctk.CTkLabel(row1, text='観測対象:', text_color=MUTED, width=76, anchor='w').pack(side='left')
        self.target_label = ctk.CTkLabel(row1, text='未選択', text_color=TEXT, anchor='w',
                                         justify='left', wraplength=430)
        self.target_label.pack(side='left', fill='x', expand=True)
        self.badge = StatusBadge(row1, 'none')
        self.badge.pack(side='right', padx=(8, 0))
        row2 = ctk.CTkFrame(info, fg_color='transparent')
        row2.pack(fill='x', pady=(4, 0))
        ctk.CTkLabel(row2, text='観測開始:', text_color=MUTED, width=76, anchor='w').pack(side='left')
        self.started_label = ctk.CTkLabel(row2, text='—', text_color=TEXT, anchor='w')
        self.started_label.pack(side='left')
        ctk.CTkLabel(row2, text='経過時間:', text_color=MUTED, width=76, anchor='w').pack(side='left', padx=(18, 0))
        self.elapsed_label = ctk.CTkLabel(row2, text='—', text_color=TEXT, anchor='w')
        self.elapsed_label.pack(side='left')
        row3 = ctk.CTkFrame(info, fg_color='transparent')
        row3.pack(fill='x', pady=(6, 0))
        ctk.CTkLabel(row3, text='自分のTikTok ID:', text_color=MUTED, width=110, anchor='w').pack(side='left')
        self.account_entry = ctk.CTkEntry(row3, width=200, placeholder_text='@IDまたはLIVEのURL')
        self.account_entry.pack(side='left')
        saved_id = get_pro_tiktok_id()
        if saved_id:
            self.account_entry.insert(0, saved_id)
        ctk.CTkButton(row3, text='IDを保存', width=84,
                      command=self.save_account_id).pack(side='left', padx=8)
        ctk.CTkLabel(row3, text='収集の状態:', text_color=MUTED, width=76, anchor='w').pack(side='left', padx=(10, 0))
        self.collector_label = ctk.CTkLabel(row3, text='停止中', text_color=TEXT, anchor='w')
        self.collector_label.pack(side='left')
        row4 = ctk.CTkFrame(info, fg_color='transparent')
        row4.pack(fill='x', pady=(4, 0))
        ctk.CTkLabel(row4, text='実際に観測中のID:', text_color=MUTED, width=110, anchor='w').pack(side='left')
        self.observing_label = ctk.CTkLabel(row4, text='—', text_color=TEXT, anchor='w',
                                            justify='left', wraplength=560)
        self.observing_label.pack(side='left', fill='x', expand=True)
        ctk.CTkLabel(
            info, text_color=MUTED, anchor='w', justify='left', wraplength=760,
            font=(theme.FONT_FAMILY, theme.FONT_SMALL),
            text='本人確認は未実装です。登録IDは観測対象の設定であり、アカウント所有者として'
                 '認証されたものではありません。IDの変更は次回の分析開始から反映されます。'
                 '固定観測は自動スクロール（Battle Hunter）を使いません。').pack(
                     fill='x', pady=(4, 0))
        actions = ctk.CTkFrame(bar.body, fg_color='transparent')
        actions.pack(side='right', padx=(16, 0))
        self.start_button = ctk.CTkButton(actions, text='配信分析を開始', width=140, height=38,
                                          fg_color=theme.PRIMARY, hover_color=theme.PRIMARY_HOVER,
                                          command=self.start_session)
        self.start_button.pack(side='left', padx=4)
        self.stop_button = ctk.CTkButton(actions, text='配信分析を終了', width=140, height=38,
                                         command=self.stop_session, state='disabled')
        self.stop_button.pack(side='left', padx=4)
        self.show_report_button = ctk.CTkButton(actions, text='レポートを見る', width=140, height=38,
                                                fg_color=theme.PURPLE, hover_color=theme.PURPLE_HOVER,
                                                command=self.show_latest_report)
        self.show_report_button.pack(side='left', padx=4)

        # ------------------------------------------------ tabs
        self.tabs = ctk.CTkTabview(self, fg_color=CARD)
        self.tabs.grid(row=2, column=0, sticky='nsew', padx=24, pady=(4, 8))
        self._build_overview(self.tabs.add('概要'))
        self._build_battles(self.tabs.add('バトル履歴'))
        self._build_ai(self.tabs.add('AI改善提案'))
        self._build_export(self.tabs.add('レポート出力'))
        self._build_details(self.tabs.add('詳細設定'))

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
        ctk.CTkLabel(
            scroll, text_color=MUTED, wraplength=850, justify='left', anchor='w',
            text='観測データの管理用設定です。通常の利用では変更する必要はありません。'
                 '既存の観測方式（Battle Hunter / 固定観測 / TopWatch）の選択や、'
                 'セッション・期間を指定した集計はここから行います。'
                 'TopWatchの子プロセスデータは読み取り専用で扱います。').pack(
                     fill='x', padx=10, pady=(10, 6))

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
        row = ctk.CTkFrame(source_card.body, fg_color='transparent')
        row.pack(fill='x', pady=3)
        ctk.CTkLabel(row, text='観測モード', text_color=MUTED).pack(side='left')
        self.mode_menu = ctk.CTkOptionMenu(
            row, values=['Battle Hunter', '固定観測', 'TopWatch', '手動観測'], width=160)
        self.mode_menu.set('固定観測')
        self.mode_menu.pack(side='left', padx=8)
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
                    _, sessions, recovered = item
                    self._sessions = sessions
                    self._render_sessions(recovered)
                elif kind == 'report':
                    _, report, previous_path = item
                    self._report = report
                    self._render_report(previous_path)
                elif kind == 'ai':
                    _, payload, path, warning = item
                    self._ai_text = payload['answer']
                    self._render_ai(payload['answer'])
                    self.ai_status.configure(text=f'完了（保存: {path or "失敗"}）{warning}')
                    self.ai_button.configure(state='normal')
                elif kind == 'error':
                    _, message = item
                    self.status.configure(text=message)
                    self.ai_button.configure(state='normal')
                    self._set_generating(False)
        except queue.Empty:
            pass
        self._tick += 1
        if self._tick % 10 == 0:
            self._update_elapsed()
        if self._tick % 25 == 0:
            self._update_collector_status()
        self._poll = self.after(120, self._pump)

    def _update_elapsed(self):
        if self._running_started_at is not None:
            self.elapsed_label.configure(
                text=duration_clock(time.time() - self._running_started_at))

    def _set_generating(self, active):
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
        self._alive = False
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
            if state.get('state') in ('stalled', 'blocked'):
                return (f"固定観測コレクタが正常に収集できていません（{state.get('label', '')}）。"
                        'セッションだけが「観測中」の状態になっています。')
            return ''
        targets = [str(t) for t in (session.get('targets') or [])]
        if (state.get('state') == 'conflict'
                and str(state.get('external_target') or '') in targets):
            return ''  # an external collector observes the same target
        return ('固定観測コレクタが停止しています。セッションは「観測中」のままですが、'
                '現在データは収集されていません。')

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

    def change_source(self):
        label = self.source_menu.get()
        for source in self._sources:
            if source['label'] == label:
                self._source = source
                break
        self._runtime = get_runtime(self._source['capture_dir']) if self._source else None
        self._active_session_id = None
        self._running_started_at = None
        self.refresh()

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        runtime = self._runtime

        def worker():
            try:
                sessions, recovered = [], []
                if runtime is not None:
                    # Guarded recovery: sessions owned by this process,
                    # or with a fresh heartbeat, are never interrupted.
                    recovered = runtime.store.recover_interrupted()
                    runtime.ensure_all_sampling()
                    sessions = runtime.store.list_sessions(limit=50)
                self._queue.put(('sessions', sessions, recovered))
            except Exception as exc:  # never break the page on store errors
                logging.exception('session load failed')
                self._queue.put(('error', f'セッションの読み込みに失敗しました: {exc}'))
            finally:
                self._busy = False

        threading.Thread(target=worker, daemon=True).start()

    def _render_sessions(self, recovered):
        labels = []
        for session in self._sessions:
            labels.append(f"{session['started_jst']} / {session['mode']} / "
                          f"{END_LABELS.get(session['end_kind'], session['end_kind'])}")
        self.session_menu.configure(values=labels or ['セッションなし'])
        if labels:
            self.session_menu.set(labels[0])
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
        self.status.configure(text=note + ('TopWatchのデータは参照のみです（セッション開始は対象プロセス側）。'
                                           if self._is_topwatch() else
                                           'セッション終了時にレポートJSONを自動生成します（画面での集計・PDF・AI分析は手動操作です）。'))
        self._update_collector_status()

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
            self._runtime.stop_session(self._active_session_id, end_kind='normal')
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
        self._set_generating(True)
        self.status.configure(text='集計中…（収集は継続しています）')
        source = self._source

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
                self._queue.put(('report', report, previous_path))
            except Exception as exc:
                logging.exception('report build failed')
                self._queue.put(('error', f'レポート生成に失敗しました: {exc}'))

        threading.Thread(target=worker, daemon=True).start()

    def _render_report(self, previous_path):
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

        self._render_battle_list(report['battles'])
        labels = [f"{b['nickname']} / {b['first_seen_jst']}" for b in report['battles']]
        self.battle_menu.configure(values=labels or ['バトル未取得'])
        if labels:
            self.battle_menu.set(labels[0])
            self._selected_battle = report['battles'][0]
        else:
            self._selected_battle = None
        self._render_battle_detail()
        self.draw_charts()
        try:
            self._set_text(self.ai_preview, evidence_preview(report))
        except Exception:
            self._set_text(self.ai_preview, 'プレビューを生成できませんでした。')

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

        def worker():
            try:
                payload, path, warning = ai_analyze(report)
                self._queue.put(('ai', payload, path, warning))
            except Exception as exc:
                logging.exception('report AI failed')
                self._queue.put(('error', f'AI分析に失敗しました（統計レポートは利用できます）: {exc}'))

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
