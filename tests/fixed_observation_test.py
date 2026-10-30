"""Tests for Pulse Pro fixed observation (Phase 2).

Covers ID normalization, settings persistence, the fixed-collector
environment, status derivation from collector health, and the child
process lifecycle with a dummy script (never the real collector).
The registered ID is an observation target only: these tests also
pin that nothing in the module claims ownership verification.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_fixed_obs_')
os.environ['LOCALAPPDATA'] = _TMP  # must precede core imports (BASE / Settings)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import fixed_observation as fx

passed = failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f'PASS {name}')
    else:
        failed += 1
        print(f'FAIL {name}')


def raises_value_error(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


# --- ID normalization ---------------------------------------------------
check('F1 plain ID passes through', fx.normalize_tiktok_id('my.id_1') == 'my.id_1')
check('F2 leading @ is stripped', fx.normalize_tiktok_id('@my.id') == 'my.id')
check('F3 LIVE URL is parsed to the ID',
      fx.normalize_tiktok_id('https://www.tiktok.com/@my.id/live') == 'my.id')
check('F4 empty ID is rejected', raises_value_error(lambda: fx.normalize_tiktok_id('')))
check('F5 invalid characters are rejected',
      raises_value_error(lambda: fx.normalize_tiktok_id('bad id!')))
check('F6 non-TikTok URL is rejected',
      raises_value_error(lambda: fx.normalize_tiktok_id('https://example.com/@x/live')))

# --- settings persistence -------------------------------------------------
check('F7 no ID registered initially', fx.get_pro_tiktok_id() == '')
check('F8 set returns the bare ID', fx.set_pro_tiktok_id('@Streamer_9') == 'Streamer_9')
check('F9 ID is restored from settings', fx.get_pro_tiktok_id() == 'Streamer_9')
check('F10 ID can be changed', fx.set_pro_tiktok_id('other_id') == 'other_id'
      and fx.get_pro_tiktok_id() == 'other_id')
settings_file = Path(_TMP) / 'AI-TikTok-LIVE-Analyzer' / 'settings.json'
saved = json.loads(settings_file.read_text(encoding='utf-8'))
check('F11 settings.json holds only the target ID (no verified/owner flags)',
      saved.get('pro_tiktok_id') == 'other_id'
      and not any('verif' in k or 'owner' in k for k in saved))

# --- fixed environment ------------------------------------------------------
env = fx.build_fixed_env('my.id', base_env={'PATH': 'x'})
check('F12 env selects fixed mode', env['LIVEMETRY_OBSERVATION_MODE'] == 'fixed')
check('F13 env points at the account LIVE page',
      env['LIVEMETRY_FIXED_URL'] == 'https://www.tiktok.com/@my.id/live')
check('F14 base env is preserved and not mutated',
      env['PATH'] == 'x' and 'LIVEMETRY_OBSERVATION_MODE' not in os.environ)

# --- fixed_target.json compatibility ---------------------------------------
path = fx.save_fixed_target('my.id', base=Path(_TMP) / 'base')
check('F15 fixed_target.json matches the top_viewer format',
      json.loads(path.read_text(encoding='utf-8')) ==
      {'url': 'https://www.tiktok.com/@my.id/live'})

# --- status derivation -------------------------------------------------------
check('F16 stopped process is 停止中',
      fx.status_from_health(False, {'status': '接続中'})['state'] == 'stopped')
check('F17 connected health is observing',
      fx.status_from_health(True, {'status': '接続中'})['state'] == 'observing')
check('F18 not-connected health is waiting (offline is not an error)',
      fx.status_from_health(True, {'status': '未接続・待機中'})['state'] == 'waiting')
check('F19 missing health while running is waiting, never observing',
      fx.status_from_health(True, {'status': '稼働情報なし'})['state'] == 'waiting')
check('F20 stale heartbeat is flagged as possibly disconnected',
      fx.status_from_health(True, {'status': '更新停止・停止の可能性'})['state'] == 'stalled')
check('F21 blocked health is shown as blocked',
      fx.status_from_health(True, {'status': '接続制限で停止'})['state'] == 'blocked')

# --- child process lifecycle (dummy script) ----------------------------------
dummy = Path(_TMP) / 'dummy_collector.py'
dummy.write_text('import time\ntime.sleep(60)\n', encoding='utf-8')
controller = fx.FixedObservationController(
    capture_dir=Path(_TMP) / 'capture_fixed', script_path=dummy)
check('F22 controller starts the child', controller.start('my.id') is True)
check('F23 child is running', controller.is_running())
check('F24 second start is a no-op', controller.start('my.id') is False)
check('F25 target is recorded on the controller', controller.target_id == 'my.id')
controller.stop()
time.sleep(0.2)
check('F26 stop terminates the child', not controller.is_running())
check('F27 status after stop is stopped', controller.status()['state'] == 'stopped')
singleton = fx.get_fixed_controller(Path(_TMP) / 'capture_fixed')
check('F28 controller is a per-capture-dir singleton',
      singleton is fx.get_fixed_controller(Path(_TMP) / 'capture_fixed'))

print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
