"""Workspace (mode) definitions for Livemetry Pulse.

One app, three audiences:

- ``streamer``   Pulse Pro — personal streamers (the default).
- ``developer``  research/collection tooling that already exists.
- ``agency``     Pulse Agency — NOT implemented. It stays
  unselectable until server-side account authentication, tenant
  separation and streamer consent management exist. A license plan
  label alone never grants Agency access, and this module contains
  no Agency pages, data or navigation targets.

Navigation entries are (key, label, target) triples. ``target`` is
the name of an existing MainWindow method (``show_*``) or the special
``open_collection_health`` window opener. Every target listed here
must exist; tests pin that. Pages that do not exist (Challenge
Investigator UI, PR #7 evidence screens, log viewers, Agency
screens) are deliberately absent instead of being faked.
"""

MODE_STREAMER = 'streamer'
MODE_DEVELOPER = 'developer'
MODE_AGENCY = 'agency'

MODES = (MODE_STREAMER, MODE_DEVELOPER, MODE_AGENCY)

MODE_LABELS = {
    MODE_STREAMER: 'ライバー（Pulse Pro）',
    MODE_DEVELOPER: '開発者',
    MODE_AGENCY: '事務所（Pulse Agency）',
}

# Labels used by the sidebar selector. Agency is never in the
# selector; it is shown separately as an unavailable note.
SELECTOR_LABELS = {
    MODE_STREAMER: 'ライバー',
    MODE_DEVELOPER: '開発者',
}

AGENCY_UNAVAILABLE_NOTE = ('事務所モードは準備中です'
                           '（認証・権限・同意管理の実装後に提供します）')

NAV_ITEMS = {
    MODE_STREAMER: [
        ('dashboard', '⌂    ホーム', 'show_dashboard'),
        ('viewer', '▣    ライブ画面', 'show_viewer'),
        ('unattended_report', '▦    配信レポート', 'show_unattended_report'),
        ('battle', '⚔    バトル分析', 'show_battle'),
        ('analytics', '▥    成長記録', 'show_analytics'),
        ('ai', '✦    AI改善提案', 'show_ai'),
        # 履歴 (analysis history) stays reachable from the Dashboard's
        # latest-result panel (on_show_history), as before.
    ],
    MODE_DEVELOPER: [
        ('dashboard', '⌂    ダッシュボード', 'show_dashboard'),
        ('viewer', '▣    TikTok Viewer', 'show_viewer'),
        ('collection_health', '◉    収集状況', 'open_collection_health'),
        ('collection_history', '▤    収集履歴', 'show_collection_history'),
        ('collection_analysis', '▥    収集分析', 'show_collection_analysis'),
        ('battle', '⚔    バトル分析', 'show_battle'),
        ('unattended_report', '▦    観測レポート', 'show_unattended_report'),
        ('history', '▤    履歴', 'show_history'),
        ('analytics', '▥    Analytics', 'show_analytics'),
        ('ai', '✦    AI分析', 'show_ai'),
    ],
    MODE_AGENCY: [],  # not implemented; never rendered
}

# Settings is available from every mode (sidebar bottom button) and
# is intentionally not part of the per-mode navigation lists.
COMMON_TARGETS = {'settings': 'show_settings'}


def nav_items(mode):
    """Navigation entries for a mode ([] for agency/unknown)."""
    return list(NAV_ITEMS.get(mode, []))


def home_target(mode):
    """Where a mode switch lands: a safe home page for that mode."""
    return 'show_dashboard'
