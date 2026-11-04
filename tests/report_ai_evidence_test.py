"""Accuracy pins for the AI evidence + prompt (PR #12).

Three failure modes are pinned shut:
1. largest_score_increases_top5 used to send the battle's
   first_seen_jst as if it were the moment of the increase. The
   increase is an interval between two samples (from_t/to_t) and
   is now sent as increase_from_jst / increase_to_jst.
2. Unfinished battles hold reference scores only; their partial
   increases are excluded from the confirmed-results comparison.
3. gap_count=0 / partial_battles=0 describe recorded samples
   only. When disconnected_seconds > 0 an explicit coverage
   constraint note is added, and the prompt forbids claiming
   continuous observation (or viewer/score timing correlation)
   without a basis, and keeps streamer actions separate from
   observation-system improvements.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_ai_evidence_')
os.environ['LOCALAPPDATA'] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import report_ai
from core.observation_sessions import format_jst

passed = failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f'PASS {name}')
    else:
        failed += 1
        print(f'FAIL {name}')


T0 = 1_762_000_000.0  # arbitrary fixed epoch


def battle(bid, finished, increase, from_t, to_t, first_seen):
    return {'unique_id': 'alice', 'battle_id': bid, 'nickname': 'Alice',
            'finished_confirmed': finished,
            'first_seen_jst': format_jst(first_seen),
            'largest_increase': ({'increase': increase,
                                  'from_t': from_t, 'to_t': to_t}
                                 if increase is not None else None)}


def make_report(disconnected=0):
    return {
        'profile': 'capture_fixed',
        'summary': {'window_start_jst': format_jst(T0),
                    'window_end_jst': format_jst(T0 + 3600),
                    'observed_seconds': 3600, 'monitored_seconds': 3600 - disconnected,
                    'disconnected_seconds': disconnected,
                    'record_count': 2, 'unique_battle_count': 2,
                    'finished_confirmed': 1, 'unfinished': 1,
                    'score_known_battles': 1, 'score_unknown_battles': 0,
                    'final_score_median': 5000, 'final_score_max': 9000,
                    'viewer_median': 40, 'viewer_peak_max': 120,
                    'score_sample_total': 30, 'viewer_sample_total': 30,
                    'partial_battles': 0, 'gap_count': 0, 'error_count': 0},
        'per_streamer': [{'unique_id': 'alice', 'nickname': 'Alice',
                          'records': 2, 'finished': 1, 'score_known': 1,
                          'score_median': 5000, 'score_max': 9000,
                          'viewer_median': 40, 'viewer_peak': 120,
                          'partial_records': 0}],
        'battles': [
            # Finished: increase of 800 between T0+600 and T0+660.
            battle(101, True, 800, T0 + 600, T0 + 660, T0 + 10),
            # Unfinished with a LARGER partial increase: excluded.
            battle(102, False, 5000, T0 + 100, T0 + 160, T0 + 50),
            # Finished without any increase: absent.
            battle(103, True, None, 0, 0, T0 + 20),
        ],
        'comparison': None,
        'data_notes': ['元の注記'],
    }


# --- 1+2: increase interval + unfinished exclusion -------------------------
evidence, mapping = report_ai.build_evidence(make_report())
top = evidence['largest_score_increases_top5']
check('E1 only the finished battle contributes an increase', len(top) == 1)
entry = top[0] if top else {}
check('E2 the unfinished battle\'s larger partial increase is excluded',
      all(item['increase'] != 5000 for item in top))
check('E3 interval start is the from_t sample time (JST)',
      entry.get('increase_from_jst') == format_jst(T0 + 600))
check('E4 interval end is the to_t sample time (JST)',
      entry.get('increase_to_jst') == format_jst(T0 + 660))
check('E5 no at_jst field remains', 'at_jst' not in entry)
check('E6 the battle first_seen time is NOT sent as the increase time',
      format_jst(T0 + 10) not in (entry.get('increase_from_jst'),
                                  entry.get('increase_to_jst')))
preview = json.loads(report_ai.evidence_preview(make_report()))
check('E7 the UI preview carries the same corrected interval',
      preview['largest_score_increases_top5'][0]['increase_from_jst']
      == format_jst(T0 + 600))

# --- 3: coverage discipline --------------------------------------------------
ev_disc, _ = report_ai.build_evidence(make_report(disconnected=1800))
notes = '\n'.join(ev_disc['notes'])
check('C1 disconnected time adds an explicit coverage constraint note',
      '観測制約' in notes and '1800' in notes)
check('C2 the note says continuity cannot be claimed',
      '連続していたとは言えません' in notes)
check('C3 the original report notes are preserved', '元の注記' in ev_disc['notes'])
ev_full, _ = report_ai.build_evidence(make_report(disconnected=0))
check('C4 fully monitored sessions gain NO extra note (payload not bloated)',
      ev_full['notes'] == ['元の注記'])
check('C5 the three coverage seconds stay distinct in the evidence',
      ev_disc['summary']['observed_seconds'] == 3600
      and ev_disc['summary']['monitored_seconds'] == 1800
      and ev_disc['summary']['disconnected_seconds'] == 1800)

# --- prompt pins ---------------------------------------------------------------
P = report_ai.PROMPT
check('P1 prompt version bumped for the changed contract',
      report_ai.PROMPT_VERSION == 'unattended-report-v2')
check('P2 prompt explains observed/monitored/disconnected distinctly',
      'monitored_seconds' in P and 'disconnected_seconds' in P
      and '記録自体が存在しない時間' in P)
check('P3 prompt forbids continuity claims from gap/partial zero alone',
      'gap_count=0' in P and '連続して観測できた' in P and '書かない' in P)
check('P4 prompt requires the increase interval fields',
      'increase_from_jst' in P and 'increase_to_jst' in P)
check('P5 prompt forbids claiming an uncomputed viewer/score correlation',
      '時刻的な関連は入力では計算されていません' in P)
check('P6 prompt separates streamer actions from observation-system work',
      '観測方法やデータ取得の改善は④に書かない' in P
      and '根拠が不足していること' in P)
check('P7 prompt keeps unfinished scores out of confirmed comparisons',
      '未完了バトルのスコアは参考値' in P and '順位付けに使わない' in P)

# --- anonymisation unchanged ---------------------------------------------------
blob = json.dumps(evidence, ensure_ascii=False)
check('A1 no real unique_id or nickname in the evidence',
      'alice' not in blob and 'Alice' not in blob)
check('A2 the streamer is present only as a code',
      evidence['streamers'][0]['id'] == 'R0001'
      and mapping['R0001']['unique_id'] == 'alice')

print(f'\n{passed} passed, {failed} failed')
raise SystemExit(1 if failed else 0)
