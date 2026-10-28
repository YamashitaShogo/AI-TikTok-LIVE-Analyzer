"""Tests for tools/first_challenge_investigator.py (offline, synthetic).

Run from the project root:
    python tests/first_challenge_investigator_test.py

All fixtures are built in-test with a minimal protobuf encoder and
written as a temporary ChallengeProbe-format JSONL.  Every name/handle
below is fictional test data; the privacy checks assert that none of
it reaches the tool's outputs.
"""

import base64
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location(
    'first_challenge_investigator', ROOT / 'tools' / 'first_challenge_investigator.py')
inv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inv)

FAILURES = []


def check(name, condition, detail=''):
    if condition:
        print(f'  ok: {name}')
    else:
        print(f'  FAIL: {name} {detail}')
        FAILURES.append(name)


# --------------------------------------------------------------------------
# Minimal protobuf encoder for fixtures
# --------------------------------------------------------------------------

def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def f_var(number, value):
    return varint((number << 3) | 0) + varint(value)


def f_bytes(number, payload):
    return varint((number << 3) | 2) + varint(len(payload)) + payload


def f_str(number, text):
    return f_bytes(number, text.encode('utf-8'))


# --------------------------------------------------------------------------
# Fixture timeline
# --------------------------------------------------------------------------

BATTLE = 7701607381448674049
T0 = 1793200000  # arbitrary fixed epoch (valid range for the tool)

# WebcastLinkMicBattle START: field2 battle_id, field4 action=4,
# field3 settings{field2 start_time_ms}
linkmic_start = (
    f_var(2, BATTLE) + f_var(4, 4) +
    f_bytes(3, f_var(2, (T0 - 5) * 1000))
)

# Gameplay-like payloads sharing the structure reported from real logs
# (3=2, 4=1, 5.1=2, 1.5=1, 1.26=1), differing in field 7 (and extras).
def gameplay(extra=b'', seven=111):
    return (
        f_bytes(1, f_var(5, 1) + f_var(26, 1)) +
        f_var(3, 2) + f_var(4, 1) +
        f_bytes(5, f_var(1, 2)) +
        f_var(7, seven) + extra
    )

gameplay_1 = gameplay()
gameplay_2 = gameplay(extra=f_var(2, BATTLE), seven=222)   # field2 == battle id
gameplay_3 = gameplay(extra=f_var(9, 5), seven=111)

# Bonus task (subtype 0) whose preview prompt carries the template the
# existing tracker requires: pm_mt_match_sp_team with arg multi=2.
prompt = f_str(1, 'pm_mt_match_sp_team') + f_bytes(2, f_str(1, 'multi') + f_str(2, '2'))
preview_item = f_bytes(2, prompt)
target_cfg = f_var(2, 60) + f_var(3, T0 + 55) + f_var(24, 2)
reward_cfg = f_var(2, 30) + f_var(3, 2)
bonus_config = f_bytes(2, preview_item) + f_bytes(3, target_cfg) + f_bytes(4, reward_cfg)
task_bonus = f_var(20, BATTLE) + f_var(2, 0) + f_bytes(3, f_bytes(1, bonus_config))

# Unclassified task #1: subtype 1 (TASK_UPDATE) - tracker has no branch.
task_update = f_var(20, BATTLE) + f_var(2, 1) + f_bytes(4, f_var(1, 50))

# Unclassified task #2: subtype 0 without the evidence-bearing prompt.
prompt_other = f_str(1, 'pm_something_else')
config_other = f_bytes(2, f_bytes(2, prompt_other))
task_no_bonus = f_var(20, BATTLE) + f_var(2, 0) + f_bytes(3, f_bytes(1, config_other))

# Gifts: field2 gift_id, field5 repeat_count, field47 a fictional
# nickname string that must never reach the outputs.
gift_in = f_var(2, 5859) + f_var(5, 1) + f_str(47, 'SECRETNICK')
gift_out = f_var(2, 777) + f_var(5, 1)

opponent_gifts = f_var(2, BATTLE) + f_var(8, 10)
item_card = f_var(2, BATTLE) + f_bytes(5, f_var(1, 1))


def notification(method, msg_id, received_at, payload):
    return {
        'kind': 'raw_notification',
        'received_at': received_at,
        'unique_id': 'SECRETWATCHER',
        'method': method,
        'msg_id': msg_id,
        'observed_battle_id': '',
        'association': 'context only; may precede battle detection',
        'is_history': False,
        'payload_bytes': len(payload),
        'payload_base64': base64.b64encode(payload).decode('ascii'),
    }


lines = [
    {'kind': 'probe_version', 'version': 2, 'unique_id': 'SECRETWATCHER',
     'received_at': T0 - 20},
    notification('WebcastLinkMicBattle', 'lm1', T0 - 5, linkmic_start),
    notification('WebcastBattleGameplayMessage', 'g1', T0, gameplay_1),
    notification('WebcastLinkmicBattleTaskMessage', 't1', T0, task_bonus),
    notification('WebcastLinkMicOpponentGifts', 'og1', T0 + 10, opponent_gifts),
    notification('WebcastLinkMicBattleItemCard', 'ic1', T0 + 15, item_card),
    notification('WebcastGiftMessage', 'gift1', T0 + 30, gift_in),
    {'kind': 'raw_notification', 'received_at': T0 + 40,
     'unique_id': 'SECRETWATCHER', 'method': 'WebcastGiftMessage',
     'msg_id': 'omit1', 'observed_battle_id': '', 'is_history': False,
     'payload_bytes': 600000, 'omitted': 'payload exceeds 512 KiB limit'},
    notification('WebcastGiftMessage', 'gift2', T0 + 200, gift_out),
    notification('WebcastBattleGameplayMessage', 'g2', T0 + 600, gameplay_2),
    notification('WebcastLinkmicBattleTaskMessage', 't2', T0 + 601, task_update),
    notification('WebcastBattleGameplayMessage', 'g3', T0 + 1200, gameplay_3),
    notification('WebcastLinkmicBattleTaskMessage', 't3', T0 + 1300, task_no_bonus),
    notification('WebcastBattleGameplayMessage', 'g1', T0, gameplay_1),  # duplicate
    {'kind': 'method_counts', 'received_at': T0 + 1400,
     'unique_id': 'SECRETWATCHER',
     'counts': {'WebcastGiftMessage': 3, 'WebcastBattleGameplayMessage': 4}},
]

tmp = Path(tempfile.mkdtemp(prefix='lm_fc_inv_'))
probe_path = tmp / 'challenge_probe.jsonl'
with open(probe_path, 'w', encoding='utf-8') as fh:
    for row in lines:
        fh.write(json.dumps(row, ensure_ascii=False) + '\n')

out_dir = tmp / 'out'
rc = inv.main([str(probe_path), '--out', str(out_dir)])
check('cli exits 0', rc == 0)

report = json.loads((out_dir / 'report.json').read_text(encoding='utf-8'))

# -- counts / dedupe --------------------------------------------------------
counts = report['method_counts']
check('gameplay counted once per unique payload', counts.get('WebcastBattleGameplayMessage') == 3,
      str(counts))
check('duplicate line skipped', report['inputs']['duplicate_lines_skipped'] == 1)
check('gift count includes the omitted record like the probe counts',
      counts.get('WebcastGiftMessage') == 3)
check('omitted counted separately', report['omitted_payload_counts'].get('WebcastGiftMessage') == 1)
check('task count', counts.get('WebcastLinkmicBattleTaskMessage') == 3)
check('probe_version summarised', len(report['inputs']['probe_version_rows']) == 1
      and report['inputs']['probe_version_rows'][0]['version'] == 2)
check('method_counts snapshot kept',
      report['inputs']['method_counts_final_snapshots'][0]['counts']['WebcastGiftMessage'] == 3)

# -- battles ------------------------------------------------------------------
check('one payload-confirmed battle', len(report['battles']) == 1)
battle = report['battles'][0]
check('battle id matches', battle['battle_id'] == str(BATTLE))
check('battle start source is settings start_time_ms',
      battle['start_source'] == 'linkmic_battle_setting_start_time_ms')
check('battle start rendered in JST', battle['start_server_jst'] == inv.jst(T0 - 5),
      str(battle['start_server_jst']))

# -- task classification --------------------------------------------------------
tasks = {t['tracker_reason']: t for t in report['task_messages']}
bonus = next(t for t in report['task_messages']
             if t['tracker_classification'] == 'bonus_announced')
check('bonus task classified like the tracker', bonus['battle_id'] == str(BATTLE))
check('bonus multiplier from prompt args', bonus['bonus_multiplier_from_prompt_args'] == 2)
check('bonus target_type surfaced structurally', bonus['target_type'] == 2)
check('bonus reward_multiple surfaced', bonus['reward_multiple'] == 2)
check('task_update unclassified with tracker reason',
      'task_update_subtype_1_not_classified_by_tracker' in tasks)
check('start without evidenced multiplier unclassified',
      'start_without_evidenced_bonus_multiplier' in tasks)

# -- gameplay occurrences -------------------------------------------------------
occs = report['gameplay']['occurrences']
check('three gameplay occurrences', len(occs) == 3)
occ0, occ1, occ2 = occs
check('occ0 associated via same envelope payload battle id',
      occ0['battle_association'] == 'same_envelope_payload_battle_id'
      and occ0['associated_battle_id'] == str(BATTLE))
check('occ0 elapsed from server start', occ0['elapsed_from_battle_start_seconds'] == 5.0,
      str(occ0['elapsed_from_battle_start_seconds']))
check('occ0 start source labelled', occ0['battle_start_source'] == 'linkmic_battle_setting_start_time_ms')
check('occ0 co-received task is the bonus task',
      len(occ0['tasks_within_5s']) == 1
      and occ0['tasks_within_5s'][0]['tracker_classification'] == 'bonus_announced')
check('occ0 gift window counts only the in-window gift',
      occ0['gifts_within_window']['count'] == 1)
check('occ0 has no battle-id value coincidence',
      occ0['top_level_varint_battle_id_value_coincidence_fields'] == [])
check('occ1 coincidence field detected',
      occ1['top_level_varint_battle_id_value_coincidence_fields'] == ['2'])
check('occ1 near task is the unclassified update',
      len(occ1['tasks_within_5s']) == 1
      and occ1['tasks_within_5s'][0]['tracker_classification'] is None)
check('occ0 assessment is CANDIDATE at most', occ0['assessment'] == 'CANDIDATE')
check('occ2 isolated assessment is UNKNOWN', occ2['assessment'] == 'UNKNOWN')
check('occ0 contrast counts item cards in battle',
      occ0['known_event_contrast_in_battle']['item_cards_in_battle'] == 1)

# -- structural comparison ------------------------------------------------------
comparison = report['gameplay']['structural_comparison']
common_paths = {c['path'] for c in comparison['common_fields']}
diff_paths = {d['path'] for d in comparison['differing_fields']}
check('common structure includes reported shared fields',
      {'3', '4', '5.1', '1.5', '1.26'} <= common_paths, str(common_paths))
check('differing structure includes field 7 and extra fields',
      {'7', '2', '9'} <= diff_paths, str(diff_paths))
check('common field 3 has value v:2 everywhere',
      any(c['path'] == '3' and c['values'] == ['v:2'] for c in comparison['common_fields']))

# -- verdict discipline ----------------------------------------------------------
def walk(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from walk(v)
    else:
        yield value

check('no assessment anywhere is CONFIRMED',
      all(v != 'CONFIRMED' for v in walk(report)))
check('first challenge assessment stays UNKNOWN',
      report['first_challenge_assessment']['status'] == 'UNKNOWN')

# -- privacy ---------------------------------------------------------------------
all_output = ''
for name in ('report.json', 'method_counts.csv', 'battles.csv',
             'task_messages.csv', 'gameplay_occurrences.csv'):
    all_output += (out_dir / name).read_text(encoding='utf-8')
check('outputs contain no payload_base64', 'payload_base64' not in all_output)
check('outputs contain no fictional nickname', 'SECRETNICK' not in all_output)
check('outputs contain no watcher handle', 'SECRETWATCHER' not in all_output)

print()
if FAILURES:
    print(f'FAILED: {len(FAILURES)} check(s): {FAILURES}')
    sys.exit(1)
print('ALL FIRST CHALLENGE INVESTIGATOR TESTS PASSED')
