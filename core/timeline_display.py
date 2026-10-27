"""Plain Japanese event descriptions; never infer missing target membership."""
import re


def target_side(target, result):
    target = str(target or '')
    host = str(result.get('host_user_id') or '')
    if not target or not host:
        return '対象未確認'
    if target == host:
        return '自枠'
    if result.get('mode') == 'team':
        groups = []
        for team in result.get('teams') or []:
            members = {str(u.get('user_id') or u.get('anchor_id') or '')
                       for u in team.get('users') or []}
            groups.append(members - {''})
        own = [g for g in groups if host in g]
        if len(own) != 1:
            return '対象未確認'
        if target in own[0]:
            return '味方'
        if any(target in g for g in groups if host not in g):
            return '相手'
    else:
        members = {str(p.get('anchor_id') or p.get('key') or '')
                   for p in result.get('participants') or []}
        if host in members and target in members:
            return '相手'
    return '対象未確認'


def describe_event(event, result, format_time):
    e = event
    label = e.get('label', 'イベント').replace('種類未判定', '種類未確認')
    phase = e.get('phase')
    if e.get('kind') == 'item':
        label = f"{target_side(e.get('target'), result)}の{label}"
    elif phase == 'reward' and e.get('multiple_raw') is not None:
        label = label.replace('倍率アップ', f"{e['multiple_raw']}倍の効果")
    timing = format_time(e['at'])
    if e.get('end'):
        timing += ' ～ ' + format_time(e['end'])
        if phase == 'mission':
            timing += '（ミッション受付期間・終了は予定）'
        else:
            timing += '（効果期間・終了は予定）'
    elif phase == 'settle':
        timing += '（達成判定の通知を受信した時刻）'
    else:
        timing += '（終了時刻未取得）'
    lines = [f'{label}  {timing}']
    if phase == 'mission':
        mission = e.get('mission') or ''
        if 'pm_' in mission:
            target = re.search(r'目標値=([^ /（]+)', mission)
            mission = f'目標：{target.group(1)}（単位未取得）' if target else 'ミッション内容は未取得'
        lines.append(mission or 'ミッション内容は未取得')
    if phase == 'settle':
        lines.append({'BOTH_SUCCEED':'双方がミッション達成', '2':'双方がミッション達成',
                      'SUCCEED':'ミッション達成', '0':'ミッション達成',
                      'FAILED':'ミッション未達成', '1':'ミッション未達成'}.get(
                          str(e.get('outcome')), '判定内容は未確認'))
    return '\n   '.join(lines)
