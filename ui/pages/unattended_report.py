"""Unattended observation report page.

Reads the collection database read-only and shows a streamer's-eye
summary of an observation session / period. AI analysis runs only from
the explicit button on the AI tab, after the exact payload (aggregates
with anonymised codes) is shown in the preview box.
"""
import json
import logging
import queue
import threading
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.observation_sessions import JST, SessionSampler, SessionStore, format_jst
from core.report_ai import analyze as ai_analyze, evidence_preview
from core.report_export import export_csv, export_json, export_pdf
from core.unattended_report import available_sources, build_report, compare_reports
from ui import theme

TEXT = ('#0F172A', '#F8FAFC')
MUTED = ('#64748B', '#94A3B8')
CARD = ('#FFFFFF', '#111C30')
END_LABELS = {'running': '観測中', 'normal': '正常終了', 'abnormal': '異常終了',
              'interrupted': '中断（再起動で検出）'}


def number(value):
    return '未取得' if value is None else f'{value:,.0f}'


def duration_text(seconds):
    if seconds is None:
        return '未取得'
    seconds = int(seconds)
    return f'{seconds // 3600}時間{(seconds % 3600) // 60}分'


class UnattendedReportPage(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color='transparent', corner_radius=0)
        self._alive = True
        self._queue = queue.Queue()
        self._busy = False
        self._sources = available_sources()
        self._source = self._sources[0] if self._sources else None
        self._store = None
        self._sampler = None
        self._active_session_id = None
        self._sessions = []
        self._report = None
        self._ai_text = None
        self._selected_battle = None
        self._poll = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        head = ctk.CTkFrame(self, fg_color='transparent')
        head.grid(row=0, column=0, sticky='ew', padx=24, pady=(22, 8))
        ctk.CTkLabel(head, text='無人観測レポート', text_color=TEXT,
                     font=(theme.FONT_FAMILY, 24, 'bold')).pack(side='left')
        ctk.CTkButton(head, text='更新', width=75, command=self.refresh).pack(side='right', padx=6)

        controls = ctk.CTkFrame(self, fg_color='transparent')
        controls.grid(row=1, column=0, sticky='ew', padx=24, pady=4)
        ctk.CTkLabel(controls, text='データ種別', text_color=MUTED).pack(side='left')
        self.source_menu = ctk.CTkOptionMenu(
            controls, values=[s['label'] for s in self._sources] or ['データなし'],
            command=lambda _: self.change_source())
        if self._sources:
            self.source_menu.set(self._sources[0]['label'])
        self.source_menu.pack(side='left', padx=6)
        ctk.CTkLabel(controls, text='対象（@ID、カンマ区切り）', text_color=MUTED).pack(side='left', padx=(14, 0))
        self.target_entry = ctk.CTkEntry(controls, width=220)
        self.target_entry.pack(side='left', padx=6)

        session_bar = ctk.CTkFrame(self, fg_color='transparent')
        session_bar.grid(row=2, column=0, sticky='ew', padx=24, pady=4)
        self.mode_menu = ctk.CTkOptionMenu(
            session_bar, values=['Battle Hunter', '固定観測', 'TopWatch', '手動観測'], width=150)
        self.mode_menu.pack(side='left')
        self.start_button = ctk.CTkButton(session_bar, text='観測セッション開始', width=150,
                                          command=self.start_session)
        self.start_button.pack(side='left', padx=6)
        self.stop_button = ctk.CTkButton(session_bar, text='観測セッション終了', width=150,
                                         command=self.stop_session, state='disabled')
        self.stop_button.pack(side='left', padx=6)
        self.session_label = ctk.CTkLabel(session_bar, text='セッション未開始', text_color=MUTED)
        self.session_label.pack(side='left', padx=10)

        scope_bar = ctk.CTkFrame(self, fg_color='transparent')
        scope_bar.grid(row=3, column=0, sticky='ew', padx=24, pady=4)
        self.scope_menu = ctk.CTkOptionMenu(
            scope_bar, values=['最新セッション', 'セッション指定', '配信者', '期間'], width=130)
        self.scope_menu.pack(side='left')
        self.session_menu = ctk.CTkOptionMenu(scope_bar, values=['セッションなし'], width=280)
        self.session_menu.pack(side='left', padx=6)
        self.period_start = ctk.CTkEntry(scope_bar, width=105)
        self.period_start.pack(side='left', padx=(10, 2))
        ctk.CTkLabel(scope_bar, text='〜', text_color=MUTED).pack(side='left')
        self.period_end = ctk.CTkEntry(scope_bar, width=105)
        self.period_end.pack(side='left', padx=2)
        ctk.CTkLabel(scope_bar, text='(期間は YYYY-MM-DD)', text_color=MUTED).pack(side='left')
        self.generate_button = ctk.CTkButton(scope_bar, text='レポート生成', width=120,
                                             command=self.generate)
        self.generate_button.pack(side='right')

        self.tabs = ctk.CTkTabview(self, fg_color=CARD)
        self.tabs.grid(row=4, column=0, sticky='nsew', padx=24, pady=(4, 12))

        overview = self.tabs.add('概要')
        self.summary_box = ctk.CTkTextbox(overview, wrap='word', font=(theme.FONT_FAMILY, 13))
        self.summary_box.pack(fill='both', expand=True, padx=8, pady=8)
        self.summary_box.configure(state='disabled')

        battles_tab = self.tabs.add('バトル一覧')
        self.battles_box = ctk.CTkTextbox(battles_tab, wrap='none', font=(theme.FONT_FAMILY, 12))
        self.battles_box.pack(fill='both', expand=True, padx=8, pady=8)
        self.battles_box.configure(state='disabled')

        trend = self.tabs.add('推移')
        trend.grid_columnconfigure(0, weight=1)
        trend.grid_rowconfigure(3, weight=1)
        self.battle_menu = ctk.CTkOptionMenu(trend, values=['バトル未取得'],
                                             command=lambda _: self.select_battle())
        self.battle_menu.grid(row=0, column=0, sticky='ew', padx=10, pady=10)
        self.trend_info = ctk.CTkLabel(trend, text='', text_color=MUTED, anchor='w',
                                       justify='left', wraplength=850)
        self.trend_info.grid(row=1, column=0, sticky='ew', padx=12, pady=4)
        self.plot_mode = ctk.CTkSegmentedButton(trend, values=['本人スコア', '視聴者数'],
                                                command=lambda _: self.draw())
        self.plot_mode.set('本人スコア')
        self.plot_mode.grid(row=2, column=0, sticky='w', padx=12, pady=8)
        self.chart = tk.Canvas(trend, highlightthickness=0, height=250)
        self.chart.grid(row=3, column=0, sticky='nsew', padx=12, pady=8)
        self.chart.bind('<Configure>', lambda _: self.draw())

        ai_tab = self.tabs.add('AI改善')
        ctk.CTkLabel(
            ai_tab,
            text='ボタンを押したときだけ、下のプレビューにある集計値（配信者は匿名コード化）'
                 'とグラフを既存AIサーバーへ送信します。コメント本文・Cookie・LIVE映像・名前や@IDは送りません。'
                 '既存AIサービスの利用枠・料金が適用されます。AIが使えない場合でも統計レポートは生成できます。',
            text_color=MUTED, wraplength=850, justify='left').pack(fill='x', padx=12, pady=8)
        ai_controls = ctk.CTkFrame(ai_tab, fg_color='transparent')
        ai_controls.pack(fill='x', padx=12, pady=4)
        self.ai_button = ctk.CTkButton(ai_controls, text='AI改善分析を実行', command=self.run_ai)
        self.ai_button.pack(side='left', padx=4)
        self.ai_status = ctk.CTkLabel(ai_controls, text='未実行', text_color=MUTED)
        self.ai_status.pack(side='left', padx=8)
        ctk.CTkLabel(ai_tab, text='送信データのプレビュー（この内容がそのまま送信されます）',
                     text_color=MUTED).pack(fill='x', padx=12, pady=(6, 0))
        self.ai_preview = ctk.CTkTextbox(ai_tab, wrap='word', height=120, font=(theme.FONT_FAMILY, 11))
        self.ai_preview.pack(fill='x', padx=12, pady=4)
        self.ai_preview.configure(state='disabled')
        self.ai_output = ctk.CTkTextbox(ai_tab, wrap='word', font=(theme.FONT_FAMILY, 13))
        self.ai_output.pack(fill='both', expand=True, padx=12, pady=8)
        self.ai_output.configure(state='disabled')

        export_tab = self.tabs.add('比較・出力')
        export_bar = ctk.CTkFrame(export_tab, fg_color='transparent')
        export_bar.pack(fill='x', padx=12, pady=10)
        ctk.CTkButton(export_bar, text='JSON出力', width=110,
                      command=lambda: self.export('json')).pack(side='left', padx=4)
        ctk.CTkButton(export_bar, text='CSV出力', width=110,
                      command=lambda: self.export('csv')).pack(side='left', padx=4)
        ctk.CTkButton(export_bar, text='PDF出力', width=110,
                      command=lambda: self.export('pdf')).pack(side='left', padx=4)
        self.compare_box = ctk.CTkTextbox(export_tab, wrap='word', font=(theme.FONT_FAMILY, 13))
        self.compare_box.pack(fill='both', expand=True, padx=12, pady=8)
        self.compare_box.configure(state='disabled')

        self.status = ctk.CTkLabel(self, text='', text_color=MUTED, anchor='w')
        self.status.grid(row=5, column=0, sticky='ew', padx=26, pady=(0, 12))
        self._schedule()
        self.refresh()

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
                    self._set_text(self.ai_output, payload['answer'])
                    self.ai_status.configure(text=f'完了（保存: {path or "失敗"}）{warning}')
                    self.ai_button.configure(state='normal')
                elif kind == 'error':
                    _, message = item
                    self.status.configure(text=message)
                    self.ai_button.configure(state='normal')
                    self.generate_button.configure(state='normal')
        except queue.Empty:
            pass
        self._poll = self.after(120, self._pump)

    def destroy(self):
        self._alive = False
        if self._poll is not None:
            try:
                self.after_cancel(self._poll)
            except Exception:
                pass
        if self._sampler is not None:
            try:
                self._sampler.stop()
            except Exception:
                pass
        super().destroy()

    def _set_text(self, box, text):
        box.configure(state='normal')
        box.delete('1.0', 'end')
        box.insert('1.0', text)
        box.configure(state='disabled')

    # ------------------------------------------------------------ sessions
    def _store_for_source(self):
        if self._source is None:
            return None
        return SessionStore(self._source['capture_dir'])

    def _is_topwatch(self):
        return bool(self._source and str(self._source['key']).startswith('topwatch:'))

    def change_source(self):
        label = self.source_menu.get()
        for source in self._sources:
            if source['label'] == label:
                self._source = source
                break
        if self._sampler is not None:
            self._sampler.stop()
            self._sampler = None
        self._active_session_id = None
        self.refresh()

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        source = self._source

        def worker():
            try:
                sessions, recovered = [], []
                if source is not None:
                    store = SessionStore(source['capture_dir'])
                    recovered = store.recover_interrupted()
                    sessions = store.list_sessions(limit=50)
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
        if running is not None:
            self._active_session_id = running['session_id']
            self.session_label.configure(
                text=f"観測中: {running['started_jst']} 開始 / {running['mode']}")
            self.stop_button.configure(state='normal')
        note = f'前回の未完了セッション{len(recovered)}件を「中断」として記録しました。' if recovered else ''
        self.status.configure(text=note + ('TopWatchのデータは参照のみです（セッション開始は対象プロセス側）。'
                                           if self._is_topwatch() else ''))
        self.start_button.configure(state='disabled' if self._is_topwatch() else 'normal')

    def _targets(self):
        raw = self.target_entry.get() or ''
        return [part.strip().lstrip('@') for part in raw.replace('、', ',').split(',')
                if part.strip()]

    def start_session(self):
        if self._source is None or self._is_topwatch():
            return
        store = self._store_for_source()
        session = store.start_session(self.mode_menu.get(), self._targets(),
                                      profile=self._source['profile'])
        self._active_session_id = session['session_id']
        if self._sampler is not None:
            self._sampler.stop()
        self._sampler = SessionSampler(store, session['session_id'],
                                       self._source['capture_dir'])
        self._sampler.start()
        self.session_label.configure(text=f"観測中: {session['started_jst']} 開始")
        self.stop_button.configure(state='normal')
        self.refresh()

    def stop_session(self):
        if self._active_session_id is None or self._source is None:
            return
        if self._sampler is not None:
            self._sampler.stop()
            self._sampler = None
        store = self._store_for_source()
        store.stop_session(self._active_session_id, end_kind='normal')
        self.session_label.configure(text='セッション終了。レポートを生成できます。')
        self.stop_button.configure(state='disabled')
        self._active_session_id = None
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

    def generate(self):
        if self._source is None:
            messagebox.showinfo('無人観測レポート', '読み取りできるデータがありません。')
            return
        scope_kind = self.scope_menu.get()
        session = None
        scope = {'kind': 'all'}
        if scope_kind in ('最新セッション', 'セッション指定'):
            session = (self._sessions[0] if self._sessions else None) \
                if scope_kind == '最新セッション' else self._selected_session()
            if session is None:
                messagebox.showinfo('無人観測レポート', '対象セッションがありません。先に観測セッションを開始してください。')
                return
            scope = {'kind': 'session'}
        elif scope_kind == '配信者':
            targets = self._targets()
            if not targets:
                messagebox.showinfo('無人観測レポート', '対象の@IDを入力してください。')
                return
            scope = {'kind': 'streamer', 'streamers': targets}
        elif scope_kind == '期間':
            try:
                start = datetime.strptime(self.period_start.get().strip(), '%Y-%m-%d').replace(tzinfo=JST)
                end = datetime.strptime(self.period_end.get().strip(), '%Y-%m-%d').replace(tzinfo=JST) \
                    + timedelta(days=1) - timedelta(seconds=1)
            except ValueError:
                messagebox.showinfo('無人観測レポート', '期間は YYYY-MM-DD で入力してください。')
                return
            scope = {'kind': 'period', 'start': start.timestamp(), 'end': end.timestamp(),
                     'streamers': self._targets()}
        self.generate_button.configure(state='disabled')
        self.status.configure(text='集計中…（収集は継続しています）')
        source = self._source

        def worker():
            try:
                import time
                began = time.time()
                report = build_report(source['database'], scope, session=session,
                                      profile=source['profile'])
                folder = self._reports_dir()
                folder.mkdir(parents=True, exist_ok=True)
                previous_path = self._previous_report_path(began)
                stamp = datetime.now(JST).strftime('%Y%m%d_%H%M%S')
                export_json(report, folder / f'report_{stamp}.json')
                if session is not None:
                    SessionStore(source['capture_dir']).mark_report(
                        session['session_id'], 'generated')
                self._queue.put(('report', report, previous_path))
            except Exception as exc:
                logging.exception('report build failed')
                self._queue.put(('error', f'レポート生成に失敗しました: {exc}'))

        threading.Thread(target=worker, daemon=True).start()

    def _render_report(self, previous_path):
        self.generate_button.configure(state='normal')
        report = self._report
        summary = report['summary']
        lines = [
            f"観測期間: {summary['window_start_jst']} 〜 {summary['window_end_jst']}",
            f"観測時間: {duration_text(summary['observed_seconds'])}（配信時間ではありません）",
            f"実際に監視できた時間: {duration_text(summary['monitored_seconds'])} / "
            f"接続中断: {duration_text(summary['disconnected_seconds'])}",
            f"観測対象数: {summary['streamer_count']} / 記録バトル数: {summary['record_count']}"
            f"（ユニーク {summary['unique_battle_count']} 件）",
            f"正常終了が確認できたバトル: {summary['finished_confirmed']} / "
            f"中断・終了未確認: {summary['unfinished']}",
            f"スコア取得済み: {summary['score_known_battles']} / 未取得: {summary['score_unknown_battles']}",
            f"スコア中央値: {number(summary['final_score_median'])} / 最大確認スコア: {number(summary['final_score_max'])}",
            f"視聴者数の中央値: {number(summary['viewer_median'])} / 最大確認視聴者数: {number(summary['viewer_peak_max'])}",
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

        battle_lines = ['配信者 / 開始（JST） / 状態 / 最終スコア / 視聴者中央値 / 視聴者最大 / 観測の完全性']
        for battle in report['battles']:
            partial = {'full': '開始から観測', 'partial': '途中から観測',
                       'unknown': '判定不可'}[battle['partial_state']]
            battle_lines.append(
                f"{battle['nickname']} / {battle['first_seen_jst']} / {battle['status_label']} / "
                f"{number(battle['final_score']) if battle['score_known'] else '未取得'} / "
                f"{number(battle['viewer_median'])} / {number(battle['viewer_peak'])} / {partial}")
        if not report['battles']:
            battle_lines.append('データなし')
        self._set_text(self.battles_box, '\n'.join(battle_lines))

        labels = [f"{b['nickname']} / {b['first_seen_jst']}" for b in report['battles']]
        self.battle_menu.configure(values=labels or ['バトル未取得'])
        if labels:
            self.battle_menu.set(labels[0])
            self._selected_battle = report['battles'][0]
        else:
            self._selected_battle = None
        self.draw()
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
        self.status.configure(text='レポートを生成しました。JSONは observation_report/reports に保存済みです。')

    # ------------------------------------------------------------ chart
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
        self.draw()

    def draw(self):
        canvas = self.chart
        canvas.delete('all')
        width = max(canvas.winfo_width(), 400)
        height = max(canvas.winfo_height(), 200)
        dark = ctk.get_appearance_mode() == 'Dark'
        bg = '#111C30' if dark else '#FFFFFF'
        grid = '#334155' if dark else '#E2E8F0'
        fg = '#F8FAFC' if dark else '#0F172A'
        canvas.configure(bg=bg)
        battle = self._selected_battle
        if not battle:
            canvas.create_text(20, 20, anchor='nw', text='データなし', fill=fg)
            return
        mode = self.plot_mode.get()
        points = battle['score_series'] if mode == '本人スコア' else battle['viewer_series']
        self.trend_info.configure(
            text=f"{battle['nickname']} / 状態: {battle['status_label']} / "
                 f"スコア記録 {battle['score_sample_count']} 回 / 視聴者記録 {battle['viewer_sample_count']} 回 / "
                 f"未取得区間 {len(battle['gaps'])} 件（線はつないでいません）")
        known = [p for p in points if p.get('v') is not None]
        if not known:
            canvas.create_text(20, 20, anchor='nw', text='未取得', fill=fg)
            return
        left, top, right, bottom = 70, 16, width - 16, height - 36
        t0, t1 = points[0]['t'], points[-1]['t']
        span = max(1.0, t1 - t0)
        vmax = max(p['v'] for p in known) or 1
        for frac in (0, 0.5, 1.0):
            y = bottom - (bottom - top) * frac
            canvas.create_line(left, y, right, y, fill=grid)
            canvas.create_text(6, y, anchor='w', text=f'{int(vmax * frac):,}', fill=fg)
        color = '#3B82F6' if mode == '本人スコア' else '#10B981'
        previous = None
        for point in points:
            if point.get('v') is None:
                previous = None
                continue
            x = left + (right - left) * (point['t'] - t0) / span
            y = bottom - (bottom - top) * (point['v'] / vmax)
            if previous is not None:
                canvas.create_line(previous[0], previous[1], x, y, fill=color, width=2)
            previous = (x, y)
        canvas.create_text(left, bottom + 8, anchor='w', text=format_jst(t0), fill=fg)
        canvas.create_text(right, bottom + 8, anchor='e', text=format_jst(t1), fill=fg)

    # ------------------------------------------------------------ AI/export
    def run_ai(self):
        if self._report is None:
            messagebox.showinfo('AI改善', '先にレポートを生成してください。')
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
            messagebox.showinfo('出力', '先にレポートを生成してください。')
            return
        stamp = datetime.now(JST).strftime('%Y%m%d_%H%M%S')
        specs = {'json': ('JSONファイル', '*.json', export_json),
                 'csv': ('CSVファイル', '*.csv', export_csv),
                 'pdf': ('PDFファイル', '*.pdf', None)}
        label, pattern, func = specs[kind]
        path = filedialog.asksaveasfilename(
            title=f'無人観測レポートを{kind.upper()}で保存', defaultextension=pattern[1:],
            initialfile=f'unattended_report_{stamp}{pattern[1:]}',
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
            messagebox.showerror('出力', f'保存に失敗しました: {exc}')
