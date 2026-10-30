"""UI helper tests for the streaming report page (Phase 1, Pulse Pro).

Only pure helpers are exercised here (no widgets are created), so the
file runs headless. The honesty rules under test: unknown values are
never rendered as 0, unfinished battles expose no final score, and an
unstructured AI answer is never force-split into fake sections.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.pages.unattended_report import (battle_score_text, duration_clock,
                                        format_mode, kpi_items, number,
                                        short_name, split_ai_sections)

passed = failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f'PASS {name}')
    else:
        failed += 1
        print(f'FAIL {name}')


# --- number / duration formatting -------------------------------------
check('U1 unknown number is 未取得, not 0', number(None) == '未取得')
check('U2 real zero stays 0', number(0) == '0')
check('U3 thousands are grouped', number(1234567) == '1,234,567')
check('U4 clock format', duration_clock(3723) == '1:02:03')
check('U5 unknown duration', duration_clock(None) == '未取得')

# --- battle score cell --------------------------------------------------
check('U6 confirmed final score is shown',
      battle_score_text({'score_known': True, 'final_score': 1200}) == '1,200')
check('U7 unfinished battle shows reference only',
      battle_score_text({'score_known': False, 'final_score': None,
                         'last_known_score': 800}) == '800（参考・終了未確認）')
check('U8 no score at all is 未取得',
      battle_score_text({'score_known': False, 'final_score': None,
                         'last_known_score': None}) == '未取得')
check('U9 a real final score of 0 is shown as 0',
      battle_score_text({'score_known': True, 'final_score': 0}) == '0')

# --- mode / names --------------------------------------------------------
check('U10 team mode label', format_mode('team') == 'チーム戦')
check('U11 individual mode label', format_mode('individual') == '個人戦')
check('U12 unknown mode is not guessed', format_mode('weird') == '形式不明')
check('U13 long names are truncated with ellipsis',
      short_name('あ' * 40, 10).endswith('…') and len(short_name('あ' * 40, 10)) == 10)

# --- KPI items -----------------------------------------------------------
report = {'summary': {
    'observed_seconds': 3600, 'monitored_seconds': 3300, 'disconnected_seconds': 120,
    'record_count': 5, 'unique_battle_count': 4, 'finished_confirmed': 3,
    'unfinished': 2, 'score_known_battles': 3, 'final_score_max': None,
    'final_score_median': None, 'viewer_median': 42.0, 'viewer_peak_max': 100,
    'viewer_sample_total': 88, 'gap_count': 1}}
items = {item['title']: item for item in kpi_items(report)}
check('U14 eight KPI cards', len(items) == 8)
check('U15 unknown max score stays 未取得', items['最大確認スコア']['value'] == '未取得')
check('U16 unknown median stays 未取得', items['スコア中央値']['value'] == '未取得')
check('U17 known viewer median is numeric', items['視聴者数中央値']['value'] == '42')
check('U18 coverage mentions gaps', '未取得区間 1 件' in items['データ取得状況']['sub'])
check('U19 empty report yields no KPIs', kpi_items({}) == [] and kpi_items(None) == [])
report2 = {'summary': dict(report['summary'], monitored_seconds=None)}
items2 = {item['title']: item for item in kpi_items(report2)}
check('U20 unmeasurable coverage is stated, not invented',
      items2['データ取得状況']['value'] == '実測不可')

# --- AI section splitting -------------------------------------------------
answer = ('① 今回の観測結果：記録5件でした。\n'
          '② 良かった傾向：後半にスコアが伸びました。\n'
          '③ 改善を検討したい点：序盤の記録が少ないです。\n'
          '④ 次回の配信で試すこと：仮説を検証します。')
sections, found = split_ai_sections(answer)
check('U21 structured answer is found', found)
check('U22 good section extracted', '後半にスコアが伸びました' in sections['good'])
check('U23 improve section extracted', '序盤の記録が少ない' in sections['improve'])
check('U24 next section extracted', '仮説を検証します' in sections['next'])
sections2, found2 = split_ai_sections('自由形式の回答です。')
check('U25 unstructured answer is not force-split', not found2 and sections2['good'] == '')

print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
