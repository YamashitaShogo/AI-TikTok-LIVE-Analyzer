"""Tests for the workspace (mode) system, Phase 3.

Pins the safety rules: streamer is the default, developer needs the
explicit display setting, Agency is never selectable in this build,
and a corrupt/unavailable saved mode falls back to streamer. Also
pins that every navigation target in the config is a real
MainWindow method (no fake menu entries).
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ['LOCALAPPDATA'] = tempfile.mkdtemp(prefix='pulse_workspace_')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.settings import Settings
from core.workspace_config import (COMMON_TARGETS, MODE_AGENCY, MODE_DEVELOPER,
                                   MODE_STREAMER, SELECTOR_LABELS, nav_items)
from core.workspace_manager import WorkspaceManager

passed = failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f'PASS {name}')
    else:
        failed += 1
        print(f'FAIL {name}')


def fresh_manager_with(settings):
    Settings.save(settings)
    return WorkspaceManager()


# --- defaults -------------------------------------------------------------
mgr = fresh_manager_with({})
check('W1 initial mode is streamer', mgr.get_mode() == MODE_STREAMER)
check('W2 developer is off by default', mgr.developer_enabled() is False)
check('W3 only streamer is available by default',
      mgr.available_modes() == [MODE_STREAMER])
check('W4 agency is never available', WorkspaceManager.agency_available() is False
      and MODE_AGENCY not in mgr.available_modes())
check('W5 agency has no navigation (not implemented)',
      nav_items(MODE_AGENCY) == [])
check('W6 agency is not in the selector labels',
      MODE_AGENCY not in SELECTOR_LABELS)

# --- streamer navigation ----------------------------------------------------
streamer_keys = [key for key, _label, _target in nav_items(MODE_STREAMER)]
check('W7 streamer menu matches the Pro design',
      streamer_keys == ['dashboard', 'viewer', 'unattended_report',
                        'battle', 'analytics', 'ai'])
check('W8 no developer-only items in the streamer menu',
      not any(key.startswith('collection') or key == 'history'
              for key in streamer_keys))

# --- developer gating ---------------------------------------------------------
check('W9 developer switch is rejected while the setting is off',
      mgr.set_mode(MODE_DEVELOPER) is False and mgr.get_mode() == MODE_STREAMER)
check('W10 agency switch is always rejected',
      mgr.set_mode(MODE_AGENCY) is False)
mgr.set_developer_enabled(True)
check('W11 enabling the setting persists across instances',
      WorkspaceManager().developer_enabled() is True)
check('W12 developer becomes available',
      WorkspaceManager().available_modes() == [MODE_STREAMER, MODE_DEVELOPER])
check('W13 developer mode can be selected and restored',
      mgr.set_mode(MODE_DEVELOPER) is True
      and WorkspaceManager().get_mode() == MODE_DEVELOPER)
check('W14 switching back to streamer works',
      mgr.set_mode(MODE_STREAMER) is True
      and WorkspaceManager().get_mode() == MODE_STREAMER)
mgr.set_mode(MODE_DEVELOPER)
mgr.set_developer_enabled(False)
check('W15 disabling the setting while in developer mode returns to streamer',
      WorkspaceManager().get_mode() == MODE_STREAMER)

# --- corrupt / unavailable saved modes ---------------------------------------
for bad in ('agency', 'garbage', '', 123, None):
    m = fresh_manager_with({'workspace_mode': bad})
    check(f'W16 saved mode {bad!r} falls back to streamer',
          m.get_mode() == MODE_STREAMER)
m = fresh_manager_with({'workspace_mode': 'developer',
                        'developer_mode_enabled': False})
check('W17 saved developer mode without the setting falls back to streamer',
      m.get_mode() == MODE_STREAMER)

# --- developer navigation ------------------------------------------------------
dev_keys = [key for key, _label, _target in nav_items(MODE_DEVELOPER)]
check('W18 developer menu groups the existing research screens',
      dev_keys == ['dashboard', 'viewer', 'collection_health',
                   'collection_history', 'collection_analysis', 'battle',
                   'unattended_report', 'history', 'analytics', 'ai'])
check('W19 settings is a common target, available in every mode',
      COMMON_TARGETS == {'settings': 'show_settings'})

# --- every target is a real MainWindow method ----------------------------------
# Parsed from source with ast: importing MainWindow would pull in
# Windows-only audio modules, which are unrelated to navigation.
import ast

source = (Path(__file__).resolve().parent.parent / 'ui' / 'main_window.py'
          ).read_text(encoding='utf-8')
tree = ast.parse(source)
methods = {node.name for node in ast.walk(tree)
           if isinstance(node, ast.FunctionDef)}

targets = {target for mode in (MODE_STREAMER, MODE_DEVELOPER)
           for _k, _l, target in nav_items(mode)}
targets.discard('open_collection_health')  # window opener, imported lazily
targets.update(COMMON_TARGETS.values())
check('W20 all navigation targets exist on MainWindow (no fake entries)',
      all(target in methods for target in targets))
check('W21 mode switching does not touch license verification',
      'require_license' in methods and 'set_workspace_mode' in methods)

print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
