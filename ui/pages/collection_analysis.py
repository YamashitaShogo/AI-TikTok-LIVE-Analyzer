"""Local collection analytics, showing sample sizes and acquisition limits."""
import logging
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from core.collection_analysis import summary, timeline, export_summary
from core.streamer_tiers import tier_summary, export_tiers
from core.collection_ai import analyze, latest_report, report_text
from core.collection_store import STATUS_LABELS, format_time
from ui import theme

TEXT = ('#0F172A', '#F8FAFC')
MUTED = ('#64748B', '#94A3B8')
CARD = ('#FFFFFF', '#111C30')


def number(value):
    return '未取得' if value is None else f'{value:,.0f}'


class CollectionAnalysisPage(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color='transparent', corner_radius=0)
        self._alive = True
        self._ai_queue = queue.Queue()
        self._ai_running = False
        self._ai_report = None
        self._queue = queue.Queue()
        self._busy = False
        self._pending = False
        self._selected = None
        self._data = None
        self._trend = None
        self._choices = {}
        self._poll = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        head = ctk.CTkFrame(self, fg_color='transparent')
        head.grid(row=0, column=0, sticky='ew', padx=24, pady=(22, 8))
        ctk.CTkLabel(head, text='収集分析', text_color=TEXT, font=(theme.FONT_FAMILY, 24, 'bold')).pack(side='left')
        ctk.CTkButton(head, text='更新', width=75, command=self.refresh).pack(side='right', padx=6)
        self.export_button = ctk.CTkButton(head, text='集計CSV', width=95, command=self.export, state='disabled')
        self.export_button.pack(side='right')
        self.metrics = ctk.CTkLabel(self, text='保存データを集計中…', anchor='w', text_color=TEXT, font=(theme.FONT_FAMILY, 14, 'bold'))
        self.metrics.grid(row=1, column=0, sticky='ew', padx=26, pady=8)
        ctk.CTkLabel(self, text='保存された観戦区間の分析です。低スコア除外があるため配信全体の平均・人気順位を示すものではありません。',
                     anchor='w', text_color=MUTED, wraplength=850).grid(row=2, column=0, sticky='ew', padx=26, pady=(0, 10))
        self.tabs = ctk.CTkTabview(self, fg_color=CARD)
        self.tabs.grid(row=3, column=0, sticky='nsew', padx=24, pady=(0, 12))
        tiers = self.tabs.add('層別分類')
        tools = ctk.CTkFrame(tiers, fg_color='transparent')
        tools.pack(fill='x', padx=8, pady=8)
        self.tier_filter = ctk.CTkOptionMenu(tools, values=['すべて', 'Top層', '中堅層', '高スコア型', '集客型', 'その他', '判定待ち'], command=lambda _: self.render_tiers())
        self.tier_filter.pack(side='left')
        ctk.CTkButton(tools, text='分類CSV', width=95, command=self.export_classification).pack(side='right')
        self.tier_panel = ctk.CTkScrollableFrame(tiers, fg_color=CARD)
        self.tier_panel.pack(fill='both', expand=True)
        compare = self.tabs.add('配信者別')
        self.groups_panel = ctk.CTkScrollableFrame(compare, fg_color=CARD)
        self.groups_panel.pack(fill='both', expand=True)
        trend = self.tabs.add('バトルの推移')
        trend.grid_columnconfigure(0, weight=1)
        trend.grid_rowconfigure(3, weight=1)
        self.battle_menu = ctk.CTkOptionMenu(trend, values=['バトル未取得'], command=self.select)
        self.battle_menu.grid(row=0, column=0, sticky='ew', padx=10, pady=10)
        self.trend_info = ctk.CTkLabel(trend, text='', text_color=MUTED, anchor='w', justify='left', wraplength=800)
        self.trend_info.grid(row=1, column=0, sticky='ew', padx=12, pady=4)
        self.plot_mode = ctk.CTkSegmentedButton(trend, values=['本人スコア', '視聴者数'], command=lambda _: self.draw())
        self.plot_mode.set('本人スコア')
        self.plot_mode.grid(row=2, column=0, sticky='w', padx=12, pady=8)
        self.chart = tk.Canvas(trend, highlightthickness=0, height=250)
        self.chart.grid(row=3, column=0, sticky='nsew', padx=12, pady=8)
        self.chart.bind('<Configure>', lambda _: self.draw())
        self.increase_info = ctk.CTkLabel(trend, text='', text_color=MUTED, justify='left', anchor='w', wraplength=800)
        self.increase_info.grid(row=4, column=0, sticky='ew', padx=12, pady=8)
        ai_tab = self.tabs.add('AI分析')
        ctk.CTkLabel(ai_tab, text='直近30日の全分類を比較します。ボタンを押したときだけ、匿名ID付きの集計とグラフを既存AIサーバーへ送信します。\n既存AIサービスの利用枠・料金が適用されます。コメント本文やLIVE映像は送りません。', text_color=MUTED, wraplength=800, justify='left').pack(fill='x', padx=12, pady=8)
        ai_controls = ctk.CTkFrame(ai_tab, fg_color='transparent')
        ai_controls.pack(fill='x', padx=12, pady=6)
        self.ai_button = ctk.CTkButton(ai_controls, text='AI分析を実行', command=self.start_collection_ai)
        self.ai_button.pack(side='left', padx=4)
        ctk.CTkButton(ai_controls, text='前回の結果', command=self.load_collection_ai).pack(side='left', padx=4)
        ctk.CTkButton(ai_controls, text='結果を保存', command=self.export_collection_ai).pack(side='left', padx=4)
        self.ai_status = ctk.CTkLabel(ai_tab, text='未実行', text_color=MUTED, anchor='w', wraplength=800)
        self.ai_status.pack(fill='x', padx=12, pady=4)
        self.ai_output = ctk.CTkTextbox(ai_tab, wrap='word', font=(theme.FONT_FAMILY,14))
        self.ai_output.pack(fill='both', expand=True, padx=12, pady=8)
        self.ai_output.configure(state='disabled')
        self.load_collection_ai()
        quality = self.tabs.add('取得状況')
        self.quality_box = ctk.CTkTextbox(quality, wrap='word', font=(theme.FONT_FAMILY, 14))
        self.quality_box.pack(fill='both', expand=True, padx=10, pady=10)
        self.quality_box.configure(state='disabled')
        self.status = ctk.CTkLabel(self, text='', text_color=MUTED, anchor='w')
        self.status.grid(row=4, column=0, sticky='ew', padx=26, pady=(0, 12))
        self._schedule()
        self.draw()
        self.refresh()

    def _schedule(self):
        self._poll = self.after(100, self._pump)

    def refresh(self):
        if self._busy:
            self._pending = True
            return
        self._busy = True
        self.status.configure(text='集計中…')
        selected = self._selected
        def worker():
            try:
                data = summary()
                data['tiers'] = tier_summary()
                key = selected
                available = {(r['unique_id'], r['battle_id']) for r in data['recent']}
                if key not in available:
                    key = ((data['recent'][0]['unique_id'], data['recent'][0]['battle_id']) if data['recent'] else None)
                self._queue.put((selected, data, key, timeline(*key) if key else None, None))
            except Exception as exc:
                logging.exception('収集分析に失敗しました')
                self._queue.put((selected, None, None, None, str(exc)))
        threading.Thread(target=worker, daemon=True, name='CollectionAnalysisRead').start()

    def _pump(self):
        if not self._alive:
            return
        self.pump_collection_ai()
        try:
            request, data, key, trend, error = self._queue.get_nowait()
            self._busy = False
            if request != self._selected:
                self._pending = True
            elif error:
                self.status.configure(text=f'集計できませんでした: {error}')
            else:
                self._data, self._selected, self._trend = data, key, trend
                self.apply(data)
                self.status.configure(text='更新済み · 集計を更新するには「更新」を押してください')
            if self._pending:
                self._pending = False
                self.refresh()
        except queue.Empty:
            pass
        self._schedule()

    def select(self, label):
        self._selected = self._choices.get(label)
        self.refresh()

    def apply(self, data):
        self.render_tiers()
        finished = data['statuses'].get('finished', 0)
        self.metrics.configure(text=f"保存 {data['total']:,}バトル  ·  終了通知取得率 {data['finished_rate']:.1f}%（{finished}/{data['total']}）  ·  視聴者数 {data['viewer_samples']:,}回  ·  低スコア除外 {data['excluded']:,}件")
        self.export_button.configure(state='normal' if data['groups'] else 'disabled')
        for child in self.groups_panel.winfo_children():
            child.destroy()
        ctk.CTkLabel(self.groups_panel, text='スコアは終了通知ありのバトルのみ集計。個人戦とチーム戦を分けています。',
                     text_color=MUTED, wraplength=780, anchor='w').pack(fill='x', padx=10, pady=8)
        if not data['groups']:
            ctk.CTkLabel(self.groups_panel, text='収集データがまだありません。', text_color=MUTED).pack(pady=30)
        for group in data['groups']:
            box = ctk.CTkFrame(self.groups_panel, fg_color=('#F1F5F9', '#17243B'), corner_radius=12)
            box.pack(fill='x', padx=8, pady=5)
            mode = {'team': 'チーム合計', 'individual': '本人スコア'}.get(group['mode'], '形式不明')
            ctk.CTkLabel(box, text=f"{group['nickname']}  @{group['unique_id']}  ·  {mode}", text_color=TEXT,
                         anchor='w', font=(theme.FONT_FAMILY, 14, 'bold')).pack(fill='x', padx=14, pady=(10, 4))
            ctk.CTkLabel(box, text=f"スコア中央値 {number(group['median_score'])}  /  最大 {number(group['max_score'])}  （{group['score_samples']}件）\n"
                         f"視聴者ピーク中央値 {number(group['median_peak'])}人  （{group['peak_samples']}件）  ·  保存 {group['total']}件 / 終了通知 {group['finished']}件",
                         text_color=MUTED, anchor='w', justify='left').pack(fill='x', padx=14, pady=(0, 10))
        self._choices = {}
        for index, row in enumerate(data['recent']):
            label = f"{format_time(row['first_seen'])}  {row['nickname']}  #{index + 1}"
            self._choices[label] = (row['unique_id'], row['battle_id'])
        labels = list(self._choices) or ['バトル未取得']
        self.battle_menu.configure(values=labels)
        selected_label = next((label for label,key in self._choices.items() if key == self._selected), labels[0])
        self.battle_menu.set(selected_label)
        self.battle_menu.configure(state='normal' if self._choices else 'disabled')
        trend = self._trend
        if trend:
            detail = trend['detail']
            self.trend_info.configure(text=f"{detail['score_text']}  ·  {STATUS_LABELS.get(detail['status'], detail['status'])}\n"
                f"{trend['score_label']}  /  スコア記録 {len(trend['scores'])}回  /  視聴者数 {len(trend['viewers'])}回\n"
                f"バトルID {detail['battle_id']}  ·  途中観戦の場合、観戦前のデータはありません。")
            intervals = [f"{p['from_seconds']:.0f}〜{p['to_seconds']:.0f}秒：+{p['increase']:,}点" for p in trend['largest_increases']]
            self.increase_info.configure(text='記録間の得点増加が大きかった区間\n' + ('  /  '.join(intervals) if intervals else '得点増加の記録なし') + '\nギフトの種類や増加の原因は、この集計では特定できません。')
        else:
            self.trend_info.configure(text='バトルを取得すると推移を表示できます。')
            self.increase_info.configure(text='')
        quality = ['保存バトルの終了状態', '']
        for status,count in data['statuses'].items():
            quality.append(f'{STATUS_LABELS.get(status,status)}: {count:,}件')
        quality += ['', f"終了通知取得率: {data['finished_rate']:.1f}%（終了通知あり ÷ 保存バトル）",
                    f"低スコア除外: {data['excluded']:,}件（上記の分母に含みません）", '',
                    '集計上の注意',
                    '・保存されたバトルだけを対象としています。未検知の枠や指定ギフトスキップの総数は分かりません。',
                    '・したがって、この割合は全配信に対する最終取得率ではありません。',
                    '・時間で終了判定したスコアは確定結果とは区別し、配信者別スコア集計から外しています。',
                    '・本人IDとスコアが特定できないバトルはスコア集計から外しています。',
                    '・個人戦の本人スコアとチーム戦のチーム合計を分けています。',
                    '・視聴者ピークは観戦中に受けた通知の最大値です。配信全体の最大人数とは限りません。',
                    '・記録が少ない配信者の数値は、観戦したバトルの偏りの影響を受けます。']
        if data['invalid_payloads']:
            quality.append(f"・読み取れない保存内容: {data['invalid_payloads']}件")
        self.quality_box.configure(state='normal')
        self.quality_box.delete('1.0','end')
        self.quality_box.insert('1.0','\n'.join(quality))
        self.quality_box.configure(state='disabled')
        self.draw()

    def start_collection_ai(self):
        if self._ai_running:
            return
        self._ai_running = True
        self.ai_button.configure(state='disabled', text='分析中…')
        self.ai_status.configure(text='最新の集計を読み取り、AIで分析中…')
        def worker():
            try:
                result = analyze(tier_summary())
                self._ai_queue.put((result, None))
            except Exception as exc:
                # Do not show raw server response or credentials in the UI.
                text = str(exc) if isinstance(exc, ValueError) else f'AI分析に失敗しました（{type(exc).__name__}）。接続・ライセンス・利用枠を確認してください。'
                self._ai_queue.put((None, text))
        threading.Thread(target=worker, daemon=True, name='CollectionAI').start()

    def pump_collection_ai(self):
        try:
            result, error = self._ai_queue.get_nowait()
        except queue.Empty:
            return
        self._ai_running = False
        self.ai_button.configure(state='normal', text='AI分析を実行')
        if error:
            self.ai_status.configure(text=error)
        else:
            report, path, warning = result
            self.show_collection_ai(report)
            self.ai_status.configure(text=warning or f'分析完了・保存済み: {path}')

    def show_collection_ai(self, report):
        self._ai_report = report
        self.ai_output.configure(state='normal')
        self.ai_output.delete('1.0','end')
        self.ai_output.insert('1.0', report_text(report))
        self.ai_output.configure(state='disabled')

    def load_collection_ai(self):
        try:
            report, path = latest_report()
            if report:
                self.show_collection_ai(report)
                self.ai_status.configure(text=f'保存結果を表示中: {path}')
            else:
                self.ai_status.configure(text='保存された分析はありません。')
        except Exception:
            self.ai_status.configure(text='保存結果を読み込めませんでした。')

    def export_collection_ai(self):
        if not self._ai_report:
            return
        path = filedialog.asksaveasfilename(parent=self, initialfile='collection_ai_report.txt', defaultextension='.txt', filetypes=[('Text','*.txt')])
        if path:
            try:
                with open(path,'w',encoding='utf-8-sig') as f:
                    f.write(report_text(self._ai_report))
                self.ai_status.configure(text=f'結果を保存しました: {path}')
            except OSError:
                self.ai_status.configure(text='結果を保存できませんでした。保存先を確認してください。')

    def render_tiers(self):
        for child in self.tier_panel.winfo_children():
            child.destroy()
        data = (self._data or {}).get('tiers', {})
        rows = data.get('rows', [])
        explanation = (f"直近30日 · 比較対象 {data.get('cohort', 0)}人 · 保存データ内での相対分類\n"
            "自枠の個人スコアと、バトル中の同時視聴者数中央値を使用。両方取れた終了済みバトルで集計。\n"
            "両軸上位20%＝Top／両軸上位20〜60%＝中堅／片軸のみ上位20%＝高スコア型・集客型。\n"
            "同点は同順位。10件未満は暫定、比較対象5人未満は判定待ち。分類は収集のたび変わります。\n"
            "イベント回は未区別。途中参加・低スコア除外の影響があります。")
        ctk.CTkLabel(self.tier_panel, text=explanation, text_color=MUTED, justify='left', anchor='w', wraplength=780).pack(fill='x', padx=12, pady=10)
        selection = self.tier_filter.get()
        filtered = [r for r in rows if selection == 'すべて' or r['tier'] == selection]
        if not filtered:
            ctk.CTkLabel(self.tier_panel, text='対象の配信者はまだいません。', text_color=MUTED).pack(pady=20)
        for r in filtered:
            box = ctk.CTkFrame(self.tier_panel, fg_color=('#F1F5F9', '#17243B'), corner_radius=12)
            box.pack(fill='x', padx=8, pady=5)
            ctk.CTkLabel(box, text=f"{r['tier']} · {r['confidence']}   |   {r['nickname']}  @{r['unique_id']}",
                text_color=TEXT, anchor='w', font=(theme.FONT_FAMILY,14,'bold'), wraplength=780).pack(fill='x', padx=14, pady=(10,4))
            detail = (f"自枠スコア中央値 {number(r['median_score'])}点  ·  視聴者数中央値 {number(r['median_viewers'])}人  ·  有効 {r['valid_battles']}件\n"
                f"観戦序盤→終盤の人数差中央値 {number(r['median_viewer_change'])}人（{r['change_battles']}件）\n"
                f"終了未確認 {r['unfinished']}件 / スコア不明 {r['missing_score']}件 / 人数未取得 {r['missing_viewers']}件 / 指定ギフト {r['restricted']}件 / 除外記録 {r['excluded']}件")
            if r['score_top'] is not None:
                detail += f"\nスコア上位 {r['score_top']:.1f}% · 視聴者数上位 {r['viewers_top']:.1f}%（同点調整）"
            if not r['valid_battles']:
                detail += '\n両指標が揃っていません。表示値はそれぞれ取得できたバトルの参考値です。'
            ctk.CTkLabel(box, text=detail, text_color=MUTED, justify='left', anchor='w', wraplength=780).pack(fill='x', padx=14, pady=(0,10))

    def export_classification(self):
        rows = (self._data or {}).get('tiers', {}).get('rows', [])
        selection = self.tier_filter.get()
        rows = [r for r in rows if selection == 'すべて' or r['tier'] == selection]
        if not rows:
            messagebox.showinfo('分類CSV', '対象データがありません。', parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, title='分類を保存', initialfile='streamer_tiers.csv', defaultextension='.csv', filetypes=[('CSV','*.csv')])
        if path:
            try:
                count = export_tiers(rows, path)
                messagebox.showinfo('保存完了', f'{count}人の分類を保存しました。', parent=self)
            except Exception as exc:
                messagebox.showerror('保存できませんでした', str(exc), parent=self)

    def draw(self):
        canvas = self.chart
        dark = ctk.get_appearance_mode() == 'Dark'
        bg, fg, grid = ('#111C30','#94A3B8','#25334A') if dark else ('#FFFFFF','#64748B','#E2E8F0')
        canvas.configure(background=bg); canvas.delete('all')
        width,height = max(400,canvas.winfo_width()),max(200,canvas.winfo_height())
        viewers = self.plot_mode.get() == '視聴者数'
        points = (self._trend or {}).get('viewers' if viewers else 'scores') or []
        if not points:
            canvas.create_text(width/2,height/2,text='この指標の記録はありません',fill=fg,font=(theme.FONT_FAMILY,13))
            return
        left,right,top,bottom = 65,width-22,20,height-45
        end = max(1,max(p['seconds'] for p in points))
        maximum = max(1,max(p['value'] for p in points))
        for f in (0,.5,1):
            y=bottom-(bottom-top)*f
            canvas.create_line(left,y,right,y,fill=grid)
            canvas.create_text(left-8,y,text=f'{maximum*f:,.0f}',anchor='e',fill=fg)
        previous=None
        for point in points:
            x=left+(right-left)*point['seconds']/end
            y=bottom-(bottom-top)*point['value']/maximum
            if previous and point['timestamp']-previous[2] <= 15:
                canvas.create_line(previous[0],previous[1],x,y,fill='#3B82F6',width=2)
            canvas.create_oval(x-2,y-2,x+2,y+2,fill='#3B82F6',outline='')
            previous=(x,y,point['timestamp'])
        for f in (0,.5,1):
            canvas.create_text(left+(right-left)*f,bottom+16,text=f'{end*f:.0f}秒',fill=fg)
        canvas.create_text((left+right)/2,bottom+34,text=(self._trend or {}).get('axis_label','経過秒'),fill=fg)

    def export(self):
        if not self._data:
            return
        path=filedialog.asksaveasfilename(parent=self,title='配信者別集計を保存',initialfile='collection_analysis.csv',defaultextension='.csv',filetypes=[('CSV','*.csv')])
        if not path:
            return
        try:
            count=export_summary(self._data['groups'],path)
            messagebox.showinfo('保存完了',f'{count}組の集計を保存しました。',parent=self)
        except Exception as exc:
            logging.exception('収集分析CSVの保存に失敗しました')
            messagebox.showerror('保存できませんでした',str(exc),parent=self)

    def destroy(self):
        self._alive=False
        if self._poll:
            try:self.after_cancel(self._poll)
            except tk.TclError:pass
        super().destroy()
