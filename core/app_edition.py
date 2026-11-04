"""Release / beta edition handling (stdlib only — imported first).

The production build is the RELEASE edition and behaves exactly as
before. A BETA build differs only by the presence of a marker file
(``beta_edition.flag``) next to the frozen executable (or inside
the PyInstaller bundle), which the beta installer/spec provide;
source (non-frozen) runs are beta only when the environment
variable ``LIVEMETRY_EDITION=beta`` is set explicitly.

What beta changes — data separation ONLY:

* ``bootstrap()`` (called at the very top of app.py, before any
  other app import) points ``LOCALAPPDATA`` at a beta-only root
  ``<LOCALAPPDATA>/LivemetryPulseBeta``. Every storage location in
  this app — settings.json (incl. the licence key), the capture /
  capture_fixed / top_watch databases, the WebView2 profile, logs,
  reports — is derived from LOCALAPPDATA, so the beta build never
  reads or writes the release build's data. Child processes (the
  viewer collector is re-entered through this same executable)
  inherit the rewritten environment; a guard variable makes the
  rewrite idempotent so it is never applied twice.
* The keyring service name gains a ``-Beta`` suffix (see
  core/secure_storage.py), so the beta build never reads or
  overwrites the release build's stored OpenAI API key.

Version display: the release shows ``v1.6.0``; the beta shows
``v1.6.0-beta.1``. BETA_VERSION_LABEL MUST match MyAppVersion in
installer_beta.iss and ProductVersion in version_info_beta.txt —
build_beta.bat verifies this and fails the build on a mismatch.
"""

import os
import sys
from pathlib import Path

APP_VERSION = "1.6.0"
BETA_VERSION_LABEL = "1.6.0-beta.1"
FLAG_FILE_NAME = "beta_edition.flag"
BETA_DATA_FOLDER = "LivemetryPulseBeta"

_EDITION_ENV = "LIVEMETRY_EDITION"
_APPLIED_ENV = "LIVEMETRY_BETA_DATA_APPLIED"


def _flag_paths():
    paths = []
    if getattr(sys, "frozen", False):
        try:
            paths.append(Path(sys.executable).resolve().parent / FLAG_FILE_NAME)
        except Exception:
            pass
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            paths.append(Path(meipass) / FLAG_FILE_NAME)
    return paths


def is_beta():
    """True for the beta edition (env override, or — frozen only —
    the marker file shipped with the beta build)."""
    if os.environ.get(_EDITION_ENV) == "beta":
        return True
    for path in _flag_paths():
        try:
            if path.exists():
                return True
        except Exception:
            continue
    return False


def edition():
    return "beta" if is_beta() else "release"


def version_label():
    return BETA_VERSION_LABEL if is_beta() else APP_VERSION


def display_version():
    return "v" + version_label()


def keyring_service_name(base):
    """The keyring service for this edition: beta uses a separate
    service so stored secrets are never shared with the release."""
    return base + "-Beta" if is_beta() else base


def bootstrap():
    """Apply the beta data separation. Returns True when beta.

    Rewrites LOCALAPPDATA to the beta-only root exactly once per
    process tree (children inherit both the rewritten value and
    the guard, so a re-entered executable never appends twice).
    Release edition: does nothing at all.
    """
    if not is_beta():
        return False
    os.environ[_EDITION_ENV] = "beta"
    if os.environ.get(_APPLIED_ENV) == "1":
        return True
    base = os.getenv("LOCALAPPDATA")
    if base:
        os.environ["LOCALAPPDATA"] = str(Path(base) / BETA_DATA_FOLDER)
        os.environ[_APPLIED_ENV] = "1"
    return True
