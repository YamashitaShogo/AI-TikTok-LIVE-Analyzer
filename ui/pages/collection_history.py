"""Collected battle history, with a native Tk audience chart."""
import logging
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from core.collection_store import CollectionStore, STATUS_LABELS, format_time
from ui import theme
from core.score_history import scores
from core.battle_timeline import hatch_segments
from core.timeline_display import describe_event
from ui.score_zoom import ScoreZoom
from core.battle_clock import BattleClock
from ui.deferred_render import DeferredRender
from core.battle_notes import BattleNotes

TEXT = ('#0F172A', '#F8FAFC')
MUTED = ('#64748B', '#94A3B8')
CARD = ('#FFFFFF', '#111C30')


class CollectionHistoryPage(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color='transparent', corner_radius=0)
        self._render = DeferredRender(self)
        self._detail_width = None
        self._timeline_text = None
        self.store = CollectionStore()
        self.notes = BattleNotes(self.store.database)
        self._note_key = None
        self._note_saved = ""
        self._queue = queue.Queue()
        self._alive = True
        self._busy = False
        self._pending = False
        self._selected = None
        self._detail = None
        self._rows = []
        self._offset = 0
        self._matched = 0
        self._search = ''
        self._jobs = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        head = ctk.CTkFrame(self, fg_color='transparent')
        head.grid(row=0, column=0, sticky='ew', padx=24, pady=(22, 8))
        ctk.CTkLabel(head, text='収集履歴', font=(theme.FONT_FAMILY, 24, 'bold'), text_color=TEXT).pack(side='left')
        self.auto = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(head, text='10秒ごとに更新', variable=self.auto, font=(theme.FONT_FAMILY, 12)).pack(side='right', padx=12)
        ctk.CTkButton(head, text='更新', width=76, command=self.refresh).pack(side='right')
        self.stats_label = ctk.CTkLabel(self, text='保存データを読み込み中…', anchor='w', text_color=MUTED, font=(theme.FONT_FAMILY, 13))
        self.stats_label.grid(row=1, column=0, sticky='ew', padx=26, pady=(0, 10))
        filters = ctk.CTkFrame(self, fg_color='transparent')
        filters.grid(row=2, column=0, sticky='ew', padx=24, pady=(0, 12))
        self.search_entry = ctk.CTkEntry(filters, placeholder_text='配信者名・IDで検索', width=280)
        self.search_entry.pack(side='left')
        self.search_entry.bind('<Return>', lambda _: self.search())
        ctk.CTkButton(filters, text='検索', width=65, command=self.search).pack(side='left', padx=8)
        ctk.CTkLabel(filters, text='保存時刻は日本時間', text_color=MUTED).pack(side='right')
        body = ctk.CTkFrame(self, fg_color='transparent')
        body.grid(row=3, column=0, sticky='nsew', padx=24, pady=(0, 8))
        body.grid_columnconfigure(0, weight=0, minsize=310)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self.list_panel = ctk.CTkScrollableFrame(body, width=300, fg_color=CARD, corner_radius=14)
        self.list_panel.grid(row=0, column=0, sticky='nsew', padx=(0, 14))
        right = ctk.CTkFrame(body, fg_color=CARD, corner_radius=14)
        right.grid(row=0, column=1, sticky='nsew')
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(3, weight=1)
        title_row = ctk.CTkFrame(right, fg_color='transparent')
        title_row.grid(row=0, column=0, sticky='ew', padx=18, pady=(16, 8))
        self.note_save_button = ctk.CTkButton(title_row, text='✎', width=36, height=32,
            font=(theme.FONT_FAMILY, 22), command=self._edit_note, state='disabled')
        self.note_save_button.pack(side='right', padx=(8, 0))
        self.detail_title = ctk.CTkLabel(title_row, text='バトルを選択', anchor='w', font=(theme.FONT_FAMILY, 19, 'bold'), text_color=TEXT)
        self.detail_title.pack(side='left')
        self.summary = ctk.CTkLabel(right, text='左の一覧からバトルを選んでください。', justify='left', anchor='w', text_color=MUTED, wraplength=500)
        self.summary.grid(row=1, column=0, sticky='ew', padx=18, pady=(0, 8))
        self.note_status = ctk.CTkLabel(title_row, text='', text_color=MUTED)
        self.note_box = ctk.CTkTextbox(title_row, height=40, width=220, wrap='word',
            fg_color=CARD, text_color=MUTED, border_width=0,
            font=(theme.FONT_FAMILY, 13))
        self.note_box.pack(side='left', fill='x', expand=True, padx=(18, 8))
        self.note_box.configure(state='disabled')
        self.tabs = ctk.CTkTabview(right, fg_color=CARD)
        self.tabs.grid(row=3, column=0, sticky='nsew', padx=10, pady=(0, 8))
        score_tab = self.tabs.add('スコア推移')
        score_tab.grid_columnconfigure(0, weight=1)
        score_tab.grid_rowconfigure(1, weight=1)
        self.score_note = ctk.CTkLabel(score_tab, text='時刻（日本時間）／スコア', text_color=MUTED, wraplength=500)
        self.score_note.grid(row=0, column=0, sticky='w', padx=8, pady=8)
        ctk.CTkButton(score_tab, text='大きく開く', width=100, command=self._open_score_zoom).grid(row=0, column=0, sticky='e', padx=8, pady=8)
        self.score_chart = tk.Canvas(score_tab, height=240, highlightthickness=0)
        self.score_chart.grid(row=1, column=0, sticky='nsew', padx=8, pady=8)
        self.score_chart.bind('<Configure>', lambda e: self._render.resize(
            'score', (e.width, e.height), self._render_score_chart))
        self.timeline_info = ctk.CTkLabel(score_tab, text='イベントの印にマウスを合わせると詳細を表示', text_color=MUTED, wraplength=600)
        self.timeline_info.grid(row=3, column=0, sticky='ew', padx=8)
        self.timeline_list = ctk.CTkTextbox(score_tab, height=100, wrap='word')
        self.timeline_list.grid(row=4, column=0, sticky='ew', padx=8, pady=6)
        ctk.CTkLabel(score_tab, text='チーム戦は合計と自枠個人を表示。未取得・30秒超の記録間隔は線を接続しません。', text_color=MUTED, wraplength=480).grid(row=2, column=0, sticky='ew', padx=8, pady=8)
        viewers = self.tabs.add('視聴者数')
        comments = self.tabs.add('コメント')
        viewers.grid_columnconfigure(0, weight=1)
        viewers.grid_rowconfigure(1, weight=1)
        self.viewer_summary = ctk.CTkLabel(viewers, text='視聴者数の記録がここに表示されます', text_color=MUTED, wraplength=500)
        self.viewer_summary.grid(row=0, column=0, sticky='ew', padx=8, pady=8)
        self.chart = tk.Canvas(viewers, height=220, highlightthickness=0)
        self.chart.grid(row=1, column=0, sticky='nsew', padx=8, pady=8)
        self.chart.bind('<Configure>', lambda e: self._render.resize(
            'viewers', (e.width, e.height), self._render_chart))
        self.export_button = ctk.CTkButton(viewers, text='このバトルの視聴者数をCSV保存', command=self.export, state='disabled')
        self.export_button.grid(row=2, column=0, sticky='ew', padx=8, pady=(4, 8))
        ctk.CTkLabel(viewers, text='観戦中の配信者の人数。通知が届いた時点の記録です。', text_color=MUTED, wraplength=500).grid(row=3, column=0, sticky='ew', padx=8, pady=4)
        self.comment_box = ctk.CTkTextbox(comments, wrap='word', font=(theme.FONT_FAMILY, 13))
        self.comment_box.pack(fill='both', expand=True, padx=6, pady=6)
        self.comment_box.configure(state='disabled')
        right.bind('<Configure>', lambda event: self._resize_detail(event.width))
        footer = ctk.CTkFrame(self, fg_color='transparent')
        footer.grid(row=4, column=0, sticky='ew', padx=24, pady=(0, 12))
        self.previous = ctk.CTkButton(footer, text='前へ', width=65, command=lambda: self.paginate(-50))
        self.previous.pack(side='left')
        self.page_label = ctk.CTkLabel(footer, text='', text_color=MUTED)
        self.page_label.pack(side='left', padx=12)
        self.next = ctk.CTkButton(footer, text='次へ', width=65, command=lambda: self.paginate(50))
        self.next.pack(side='left')
        self.status = ctk.CTkLabel(footer, text='', text_color=MUTED)
        self.status.pack(side='right')
        self._update_timeline_text()
        self._draw_chart()
        self._draw_score_chart()
        self._schedule(100, self._pump)
        self._schedule(10000, self._auto_refresh)
        self.refresh()

    def _resize_detail(self, width):
        if width == self._detail_width:
            return
        self._detail_width = width
        self._render.request('layout', self._apply_detail_width)

    def _apply_detail_width(self):
        width = self._detail_width
        wrap = max(180, width - 42)
        self.summary.configure(wraplength=wrap)
        self.detail_title.configure(wraplength=max(120, int((width - 90) * 0.42)))
        self.viewer_summary.configure(wraplength=wrap)

    def _schedule(self, delay, fn):
        def call():
            if job in self._jobs:
                self._jobs.remove(job)
            if self._alive:
                fn()
        job = self.after(delay, call)
        self._jobs.append(job)

    def search(self):
        if not self._save_note(): return
        self._search = self.search_entry.get().strip()
        self._offset = 0
        self._selected = None
        self.refresh()

    def paginate(self, step):
        if not self._save_note(): return
        self._offset = max(0, self._offset + step)
        self._selected = None
        self.refresh()

    def refresh(self):
        if self._busy:
            self._pending = True
            return
        self._busy = True
        self.status.configure(text='読み込み中…')
        request = (self._search, self._offset, self._selected)
        def worker():
            try:
                overview = self.store.overview(request[0], request[1])
                selected = request[2]
                if selected is None and overview['rows']:
                    selected = (overview['rows'][0]['unique_id'], overview['rows'][0]['battle_id'])
                detail = self.store.detail(*selected) if selected else None
                self._queue.put((request, overview, selected, detail, None))
            except Exception as exc:
                logging.exception('収集履歴の読み込みに失敗しました')
                self._queue.put((request, None, None, None, str(exc)))
        threading.Thread(target=worker, daemon=True, name='CollectionHistoryRead').start()

    def _pump(self):
        try:
            request, overview, selected, detail, error = self._queue.get_nowait()
            self._busy = False
            current = (self._search, self._offset, self._selected)
            if request == current:
                if error:
                    self.status.configure(text='読み込みに失敗。更新を押してください。')
                    self.summary.configure(text=f'保存データを読み込めませんでした。\n{error}')
                else:
                    self._selected = selected if detail else None
                    self._rows = overview['rows']
                    self._matched = overview['matched']
                    self._apply_overview(overview)
                    self._apply_detail(detail)
                    self.status.configure(text='更新済み')
            else:
                self._pending = True
            if self._pending:
                self._pending = False
                self.refresh()
        except queue.Empty:
            pass
        self._schedule(100, self._pump)

    def _auto_refresh(self):
        if self.auto.get():
            self.refresh()
        self._schedule(10000, self._auto_refresh)

    def _apply_overview(self, overview):
        stats = overview['stats']
        self.stats_label.configure(text=f"バトル {stats['battles']:,}件    更新履歴 {stats['snapshots']:,}件    保存コメント {stats['comments']:,}件    視聴者数 {stats['viewer_samples']:,}件    低スコア除外 {stats['excluded_battles']:,}件")
        for widget in self.list_panel.winfo_children():
            widget.destroy()
        if not self._rows:
            ctk.CTkLabel(self.list_panel, text='該当する履歴がありません。' if overview['exists'] else '収集データはまだありません。', text_color=MUTED).pack(padx=14, pady=30)
        for row in self._rows:
            key = (row['unique_id'], row['battle_id'])
            label = f"{row['nickname'][:24]}\n@{row['unique_id']}\n{format_time(row['first_seen'])} · {STATUS_LABELS.get(row['status'], row['status'])}\n{row['score_text']}"
            ctk.CTkButton(self.list_panel, text=label, anchor='w', height=98,
                fg_color=('#DBEAFE', '#1E3A5F') if key == self._selected else ('#F1F5F9', '#17243B'),
                hover_color=('#E2E8F0', '#24354F'), text_color=TEXT, font=(theme.FONT_FAMILY, 12),
                command=lambda k=key: self.select(k)).pack(fill='x', padx=4, pady=4)
        self.previous.configure(state='normal' if self._offset else 'disabled')
        self.next.configure(state='normal' if self._offset + 50 < self._matched else 'disabled')
        self.page_label.configure(text=f"{min(self._offset + 1, self._matched)}–{min(self._offset + 50, self._matched)} / {self._matched}件")

    def select(self, key):
        if not self._save_note(): return
        self._selected = key
        self.refresh()

    def _apply_detail(self, detail):
        key = (detail['unique_id'], detail['battle_id']) if detail else None
        if key != self._note_key:
            if not self._save_note(): return
            try:
                note = self.notes.load(*key) if key else ''
            except Exception as exc:
                self.note_status.configure(text='メモ読込失敗')
                messagebox.showerror('メモ読込失敗', str(exc), parent=self)
                return
            self._note_key = key
            self._note_saved = note
            self.note_box.configure(state='normal')
            self.note_box.delete('1.0','end')
            self.note_box.insert('1.0', note)
            self.note_box.configure(state='disabled')
            self.note_save_button.configure(state='normal' if key else 'disabled')
            self.note_status.configure(text='観測メモ（自分用）')
        self._detail = detail
        if detail is None:
            self.detail_title.configure(text='バトルを選択')
            self.summary.configure(text='左の一覧からバトルを選んでください。')
            self.viewer_summary.configure(text='視聴者数の記録はありません')
            self.export_button.configure(state='disabled')
            comment_text = ''
        else:
            result = detail['result']
            self.detail_title.configure(text=str(result.get('host_nickname') or detail['unique_id']))
            host_note = '左が本人・本人チーム' if detail['host_identified'] else '本人の位置は未特定'
            self.summary.configure(text=f"@{detail['unique_id']}  ·  {STATUS_LABELS.get(detail['status'], detail['status'])}\n"
                f"{detail['score_text']}  （{host_note}）\n"
                f"記録開始 {format_time(detail['first_seen'])}  /  最終更新 {format_time(detail['last_seen'])}\n"
                f"バトルID {detail['battle_id']}\n"
                f"更新 {detail['snapshot_count']:,}件  ·  バトル中コメント {detail['comment_count']:,}件")
            points = detail['viewers']
            counts = [p['viewer_count'] for p in points]
            self.viewer_summary.configure(text=(f'最初 {counts[0]:,}人 → 最後 {counts[-1]:,}人  ·  最大 {max(counts):,}人  ·  記録 {len(counts):,}回' if counts else 'このバトルの視聴者数は未取得です'))
            self.export_button.configure(state='normal' if points else 'disabled')
            comment_text = '\n\n'.join(f"{format_time(c['received_at'])}  {c['username']}\n{c['comment']}" for c in detail['comments'])
            if detail['comment_count'] > 300:
                comment_text = '直近300件を表示しています。\n\n' + comment_text
            if not comment_text:
                comment_text = 'バトル中のコメント記録はありません。'
        self.comment_box.configure(state='normal')
        self.comment_box.delete('1.0', 'end')
        self.comment_box.insert('1.0', comment_text)
        self.comment_box.configure(state='disabled')
        self._update_timeline_text()
        self._draw_chart()
        self._draw_score_chart()

    def _draw_chart(self):
        self._render.request('viewers', self._render_chart)

    def _render_chart(self):
        dark = ctk.get_appearance_mode() == 'Dark'
        bg, fg, grid = ('#111C30', '#94A3B8', '#25334A') if dark else ('#FFFFFF', '#64748B', '#E2E8F0')
        canvas = self.chart
        canvas.configure(background=bg)
        canvas.delete('all')
        width, height = max(300, canvas.winfo_width()), max(180, canvas.winfo_height())
        points = (self._detail or {}).get('viewers') or []
        if not points:
            canvas.create_text(width/2, height/2, text='視聴者数の記録がありません', fill=fg, font=(theme.FONT_FAMILY, 12))
            return
        left, right, top, bottom = 50, width-18, 20, height-42
        lo_time, hi_time = points[0]['received_at'], points[-1]['received_at']
        span = max(1, hi_time-lo_time)
        maximum = max(1, max(p['viewer_count'] for p in points))
        for fraction in (0, .5, 1):
            y = bottom-(bottom-top)*fraction
            canvas.create_line(left, y, right, y, fill=grid)
            canvas.create_text(left-7, y, text=f'{maximum*fraction:,.0f}', anchor='e', fill=fg)
        previous = None
        for point in points:
            x = left+(right-left)*(point['received_at']-lo_time)/span
            y = bottom-(bottom-top)*point['viewer_count']/maximum
            if previous and point['received_at']-previous[2] <= 15:
                canvas.create_line(previous[0], previous[1], x, y, fill='#3B82F6', width=2)
            canvas.create_oval(x-2, y-2, x+2, y+2, fill='#3B82F6', outline='')
            previous = (x,y,point['received_at'])
        canvas.create_text(left, bottom+16, text=format_time(lo_time).split(' ')[-1], anchor='w', fill=fg)
        canvas.create_text(right, bottom+16, text=format_time(hi_time).split(' ')[-1], anchor='e', fill=fg)
        canvas.create_text((left+right)/2, bottom+34, text='受信時刻（日本時間）', fill=fg)

    def _edit_note(self):
        if not self._note_key:
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title('観測メモを編集')
        dialog.geometry('560x320')
        dialog.minsize(400, 260)
        dialog.transient(self.winfo_toplevel())
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(dialog, text='観測メモ', font=(theme.FONT_FAMILY, 19, 'bold')).grid(
            row=0, column=0, sticky='w', padx=20, pady=(18, 8))
        editor = ctk.CTkTextbox(dialog, wrap='word', font=(theme.FONT_FAMILY, 14),
            corner_radius=12, border_width=1, border_color=('#DCE1F0', '#33445F'))
        editor.grid(row=1, column=0, sticky='nsew', padx=20, pady=8)
        editor.insert('1.0', self.note_box.get('1.0', 'end-1c'))
        buttons = ctk.CTkFrame(dialog, fg_color='transparent')
        buttons.grid(row=2, column=0, sticky='ew', padx=20, pady=(8, 18))
        def save():
            previous = self.note_box.get('1.0', 'end-1c')
            self.note_box.configure(state='normal')
            self.note_box.delete('1.0', 'end')
            self.note_box.insert('1.0', editor.get('1.0', 'end-1c'))
            self.note_box.configure(state='disabled')
            if self._save_note():
                dialog.destroy()
            else:
                self.note_box.configure(state='normal')
                self.note_box.delete('1.0', 'end')
                self.note_box.insert('1.0', previous)
                self.note_box.configure(state='disabled')
        ctk.CTkButton(buttons, text='保存', width=100, fg_color='#5B5CE2',
            hover_color='#4C4DD0', command=save).pack(side='right')
        ctk.CTkButton(buttons, text='キャンセル', width=100, fg_color=('#E8ECF5', '#28364B'),
            text_color=TEXT, command=dialog.destroy).pack(side='right', padx=8)
        dialog.after(100, lambda: (dialog.grab_set(), editor.focus_set()) if dialog.winfo_exists() else None)

    def _save_note(self):
        if not self._note_key: return True
        text = self.note_box.get('1.0','end-1c')
        if text == self._note_saved: return True
        try:
            self.notes.save(*self._note_key, text)
            self._note_saved = text
            self.note_status.configure(text='観測メモ：保存済み')
            return True
        except Exception as exc:
            logging.exception('観測メモ保存失敗')
            messagebox.showerror('メモを保存できませんでした', str(exc), parent=self)
            return False

    def _open_score_zoom(self):
        if not self._detail:
            messagebox.showinfo('スコア推移', '先にバトルを選択してください。', parent=self)
            return
        window = ScoreZoom(self, self._detail)
        window.after(100, window.lift)

    def _update_timeline_text(self):
        detail = self._detail or {}
        self._timeline_descriptions = [
            f"{i+1}. {describe_event(e, detail.get('result') or {}, format_time)}"
            for i, e in enumerate(detail.get('timeline') or [])]
        text = '\n'.join(self._timeline_descriptions) or 'イベント記録なし（未取得と未使用は区別できません）'
        if text == self._timeline_text:
            return
        self._timeline_text = text
        self.timeline_list.configure(state='normal')
        self.timeline_list.delete('1.0', 'end')
        self.timeline_list.insert('1.0', text)
        self.timeline_list.configure(state='disabled')
        self.timeline_info.configure(text='灰点線：ミッション期間／緑：達成・判定通知／斜線：アイテム・倍率アップ効果期間')

    def _draw_score_chart(self):
        self._render.request('score', self._render_score_chart)

    def _render_score_chart(self):
        canvas = self.score_chart
        dark = ctk.get_appearance_mode() == 'Dark'
        bg, fg, grid = ('#111C30', '#94A3B8', '#25334A') if dark else ('#FFFFFF', '#64748B', '#E2E8F0')
        canvas.configure(background=bg); canvas.delete('all')
        width, height = max(300, canvas.winfo_width()), max(240, canvas.winfo_height())
        raw = (self._detail or {}).get('score_snapshots') or []
        points = [(p['received_at'], scores(p['result'])) for p in raw]
        events = (self._detail or {}).get('timeline') or []
        descriptions = self._timeline_descriptions
        values = [v for _, series in points for v in series.values() if v is not None]
        if not values and not events:
            canvas.create_text(width/2, height/2, text='スコア推移の記録がありません', fill=fg)
            return
        keys = list(dict.fromkeys(k for _, series in points for k in series))
        left, right, top = 76, width-18, 60
        legend_rows = (len(keys)+1)//2
        bottom = max(top+60, height-65-legend_rows*20)
        times = [t for t,_ in points] + [e['at'] for e in events] + [e['end'] for e in events if e.get('end')]
        clock = BattleClock(self._detail or {})
        start, end = clock.bounds(times)
        span = max(1, end-start); maximum = max(1, max(values, default=0))*1.05
        for i,e in enumerate(events):
            x = left+(right-left)*(e['at']-start)/span
            color = '#F59E0B' if e['kind']=='item' else '#94A3B8' if e.get('phase')=='mission' else '#22C55E' if e.get('phase')=='settle' else '#14B8A6' if 'スピード' in e['label'] else '#A855F7'
            tag = f'timeline_{i}'
            y = 14 + (i % 3)*14
            finish = e.get('end')
            if finish and finish > e['at']:
                x_end = left+(right-left)*(finish-start)/span
                for segment in ([] if e.get('phase')=='mission' else hatch_segments(x, top, x_end, bottom)):
                    canvas.create_line(*segment, fill=color, width=1, tags=(tag,))
                canvas.create_line(x_end, top, x_end, bottom, fill=color, width=2, dash=(3,3) if e.get('phase')=='mission' else (), tags=(tag,))
                canvas.create_text(x_end, bottom-8, text=f'{i+1}終', anchor='e', fill=color, tags=(tag,))
            canvas.create_line(x, top, x, bottom, fill=color, width=2, dash=(3,3) if e.get('phase')=='mission' else (), tags=(tag,))
            canvas.create_text(x,y,text=f'{i+1}達' if e.get('phase')=='settle' and e.get('succeeded') else f'{i+1}判' if e.get('phase')=='settle' else f'{i+1}始',fill=color,tags=(tag,))
            canvas.tag_bind(tag, '<Enter>', lambda _, text=descriptions[i]: self.timeline_info.configure(text=text))
        for fraction in (0, .25, .5, .75, 1):
            y = bottom-(bottom-top)*fraction
            canvas.create_line(left,y,right,y,fill=grid)
            canvas.create_text(left-8,y,text=f'{maximum*fraction:,.0f}',anchor='e',fill=fg)
        colors = ['#3B82F6','#EF4444','#22C55E','#A855F7','#F59E0B']
        for i,key in enumerate(keys):
            color = colors[i % len(colors)]; previous = None
            for timestamp,series in points:
                value = series.get(key)
                if value is None:
                    previous = None
                    continue
                x = left+(right-left)*(timestamp-start)/span
                y = bottom-(bottom-top)*value/maximum
                if previous and timestamp-previous[2] <= 30:
                    canvas.create_line(previous[0],previous[1],x,y,fill=color,width=2)
                canvas.create_oval(x-2,y-2,x+2,y+2,fill=color,outline='')
                previous = (x,y,timestamp)
            canvas.create_text(left+(i%2)*(right-left)/2,bottom+48+(i//2)*20,text=key,anchor='w',fill=color,font=(theme.FONT_FAMILY,10))
        for ts in clock.ticks(start, end):
            x = left+(right-left)*(ts-start)/span
            canvas.create_text(x,bottom+16,text=clock.label(ts, lambda t: format_time(t).split(' ')[-1]),fill=fg)
        canvas.create_text((left+right)/2,bottom+32,text=clock.caption,fill=fg)


    def export(self):
        if not self._selected or not self._detail:
            return
        path = filedialog.asksaveasfilename(parent=self, title='視聴者数をCSV保存', defaultextension='.csv',
                                          initialfile=f"battle_{self._selected[1]}_viewers.csv", filetypes=[('CSV', '*.csv')])
        if not path:
            return
        try:
            count = self.store.export_viewers(*self._selected, path)
            messagebox.showinfo('保存完了', f'視聴者数 {count}件を保存しました。', parent=self)
        except Exception as exc:
            logging.exception('視聴者数CSVの保存に失敗しました')
            messagebox.showerror('保存できませんでした', str(exc), parent=self)

    def destroy(self):
        self._render.close()
        self._save_note()
        self._alive = False
        for job in list(self._jobs):
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        self._jobs.clear()
        super().destroy()
