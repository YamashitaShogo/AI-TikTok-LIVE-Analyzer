"""Paths shared by all modules in one collector process."""
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
BASE = Path(os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))) / 'AI-TikTok-LIVE-Analyzer'
FIXED = os.environ.get('LIVEMETRY_OBSERVATION_MODE') == 'fixed'
CAPTURE = BASE / ('capture_fixed' if FIXED else 'capture')
PROFILE = BASE / ('webview_profile_fixed' if FIXED else 'webview_profile')

def live_url(value):
    value = str(value).strip()
    if '://' in value:
        p = urlsplit(value)
        if p.scheme != 'https' or p.netloc != 'www.tiktok.com':
            raise ValueError('TikTokの https://www.tiktok.com/@ID/live を入力してください')
        value = p.path.strip('/').split('/')[0]
    value = value.lstrip('@')
    if not re.fullmatch(r'[A-Za-z0-9_.]{1,64}', value):
        raise ValueError('配信者のIDまたはLIVEのURLを入力してください')
    return 'https://www.tiktok.com/@' + value + '/live'
