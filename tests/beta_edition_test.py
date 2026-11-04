#!/usr/bin/env python3
"""Beta edition separation checks (no network, no real profile).

Run: python tests/beta_edition_test.py

B1-B3: edition detection, the one-time LOCALAPPDATA rewrite and
the keyring service separation in core/app_edition.py.
B4:    the release installer identity is untouched and the beta
       installer identity is fully separate.
B5:    the version label agrees in all three places.
B6:    requirements-build.txt carries the previously missing deps.
B7:    no secrets are bundled by the beta spec / installer.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_passed = 0
_failed = 0


def check(name, condition, detail=''):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f'  ok - {name}')
    else:
        _failed += 1
        print(f'FAIL - {name} {detail}')


from core import app_edition  # noqa: E402

_ENV_KEYS = ('LIVEMETRY_EDITION', 'LIVEMETRY_BETA_DATA_APPLIED', 'LOCALAPPDATA')
_saved_env = {k: os.environ.get(k) for k in _ENV_KEYS}


def set_env(**kwargs):
    for key in _ENV_KEYS:
        if key in kwargs:
            if kwargs[key] is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = kwargs[key]


try:
    # --- B1: release is the default and bootstrap is a no-op ----
    with tempfile.TemporaryDirectory() as tmp:
        set_env(LIVEMETRY_EDITION=None, LIVEMETRY_BETA_DATA_APPLIED=None,
                LOCALAPPDATA=tmp)
        check('B1 release by default: not beta, v1.6.0, bootstrap no-op',
              app_edition.is_beta() is False
              and app_edition.display_version() == 'v1.6.0'
              and app_edition.bootstrap() is False
              and os.environ['LOCALAPPDATA'] == tmp
              and app_edition.keyring_service_name('AI-TikTok-LIVE-Analyzer')
              == 'AI-TikTok-LIVE-Analyzer')

    # --- B2: beta rewrites the data root exactly once -----------
    with tempfile.TemporaryDirectory() as tmp:
        set_env(LIVEMETRY_EDITION='beta', LIVEMETRY_BETA_DATA_APPLIED=None,
                LOCALAPPDATA=tmp)
        expected = str(Path(tmp) / 'LivemetryPulseBeta')
        first = app_edition.bootstrap()
        after_first = os.environ['LOCALAPPDATA']
        second = app_edition.bootstrap()
        check('B2 beta bootstrap points LOCALAPPDATA at the beta root, once',
              first is True and second is True
              and after_first == expected
              and os.environ['LOCALAPPDATA'] == expected
              and app_edition.display_version() == 'v1.6.0-beta.1'
              and app_edition.keyring_service_name('AI-TikTok-LIVE-Analyzer')
              == 'AI-TikTok-LIVE-Analyzer-Beta')

    # --- B3: keyring service follows the edition ----------------
    try:
        import importlib
        import core.secure_storage as secure_storage
        set_env(LIVEMETRY_EDITION=None)
        importlib.reload(secure_storage)
        release_service = secure_storage.SecureStorage.SERVICE_NAME
        set_env(LIVEMETRY_EDITION='beta')
        importlib.reload(secure_storage)
        beta_service = secure_storage.SecureStorage.SERVICE_NAME
        importlib.reload(secure_storage)
        check('B3 SecureStorage service name is edition-separated',
              release_service == 'AI-TikTok-LIVE-Analyzer'
              and beta_service == 'AI-TikTok-LIVE-Analyzer-Beta')
    except ImportError:
        source = (ROOT / 'core' / 'secure_storage.py').read_text(encoding='utf-8')
        check('B3 SecureStorage service name is edition-separated (source)',
              'keyring_service_name("AI-TikTok-LIVE-Analyzer")' in source)

    # --- B4: installer identities --------------------------------
    release_iss = (ROOT / 'installer_release.iss').read_text(encoding='utf-8')
    beta_iss = (ROOT / 'installer_beta.iss').read_text(encoding='utf-8')
    check('B4 release installer untouched (AppId / folder / exe)',
          'A58F6A53-1EFA-4AA8-9D58-513EC513AC21' in release_iss
          and 'Programs\\Livemetry Pulse' in release_iss
          and 'LivemetryPulse.exe' in release_iss)
    check('B4 beta installer has its own AppId, folder, exe and name',
          '5F1D4EC2-4F38-453F-BAB1-D1160BF2444C' in beta_iss
          and 'A58F6A53' not in beta_iss
          and 'Programs\\Livemetry Pulse Beta' in beta_iss
          and 'LivemetryPulseBeta.exe' in beta_iss
          and 'Livemetry Pulse Beta' in beta_iss)

    # --- B5: one version label in all three places ---------------
    label = app_edition.BETA_VERSION_LABEL
    iss_version = re.search(r'#define MyAppVersion "([^"]+)"', beta_iss)
    info = (ROOT / 'version_info_beta.txt').read_text(encoding='utf-8')
    flag = (ROOT / 'beta_edition.flag').read_text(encoding='utf-8')
    check('B5 beta version label agrees (code / installer / version info / flag)',
          iss_version is not None and iss_version.group(1) == label
          and f"StringStruct('ProductVersion', '{label}')" in info
          and f"StringStruct('FileVersion', '{label}')" in info
          and f'version={label}' in flag)

    # --- B6: build requirements ----------------------------------
    req = (ROOT / 'requirements-build.txt').read_text(encoding='utf-8')
    req_names = {line.strip().lower() for line in req.splitlines()
                 if line.strip() and not line.startswith('#')}
    check('B6 requirements-build.txt includes opencv-python, numpy, keyring',
          {'opencv-python', 'numpy', 'keyring'} <= req_names)

    # --- B7: nothing secret is bundled ----------------------------
    beta_spec = (ROOT / 'LivemetryPulseBeta.spec').read_text(encoding='utf-8')
    check('B7 beta spec/installer bundle no settings, licence or .env',
          'settings.json' not in beta_spec and 'settings.json' not in beta_iss
          and 'licenses' not in beta_spec
          and ('".env"' not in beta_spec and "'.env'" not in beta_spec)
          and '.env.example' in beta_spec)
    # --- B8: smoke / verify scripts carry the safety design -----
    smoke = (ROOT / 'tools' / 'smoke_test_beta.ps1').read_text(encoding='utf-8-sig')
    verify = (ROOT / 'tools' / 'verify_beta_isolation.ps1').read_text(encoding='utf-8-sig')
    check('B8 smoke waits for the window before closing, with diagnostics',
          'MainWindowHandle' in smoke and 'CloseMainWindow' in smoke
          and 'smoke_diagnostics.log' in smoke
          and 'START_FAILED_EARLY_EXIT' in smoke
          and 'WINDOW_NOT_SHOWN' in smoke and 'CLOSE_TIMEOUT' in smoke
          and 'Get-FullSnapshot' in smoke)
    check('B8 verify guards existing beta / running apps, full-hash compare',
          '既存のベータ版がインストール済みです' in verify
          and "Get-Process -Name 'LivemetryPulse'" in verify
          and 'Get-FullSnapshot' in verify and 'Get-FileHash' in verify)
finally:
    set_env(**{k: _saved_env[k] for k in _ENV_KEYS})

print()
print(f'{_passed} passed, {_failed} failed')
sys.exit(1 if _failed else 0)
