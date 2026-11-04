"""Workspace mode state, persisted in settings.json.

Keys:
- ``workspace_mode``: 'streamer' | 'developer' (agency is never a
  valid persisted value; anything else falls back to 'streamer').
- ``developer_mode_enabled``: bool, default False. The developer
  workspace is selectable only while this display setting is on.

This is a UI display preference only. It does not change license
verification, does not grant any permission, and does not unlock
Agency: ``agency_available()`` is hard-wired to False until a future
server-side authorization service exists to decide it.
"""
try:
    from .settings import Settings
    from .workspace_config import MODE_AGENCY, MODE_DEVELOPER, MODE_STREAMER
except ImportError:  # direct-script import style
    from settings import Settings
    from workspace_config import MODE_AGENCY, MODE_DEVELOPER, MODE_STREAMER

MODE_KEY = 'workspace_mode'
DEVELOPER_KEY = 'developer_mode_enabled'


class WorkspaceManager:
    def __init__(self):
        # Settings are read fresh on every call so changes made from
        # the Settings page are visible without an app restart.
        pass

    @staticmethod
    def _load():
        data = Settings.load()
        return data if isinstance(data, dict) else {}

    # NOTE: there is deliberately no _save() helper. All writes go
    # through Settings.update() (strict read + locked merge); a
    # save-the-whole-snapshot helper here was dead code and a
    # lost-update trap for any future caller.

    def developer_enabled(self):
        return self._load().get(DEVELOPER_KEY) is True

    def set_developer_enabled(self, enabled):
        enabled = bool(enabled)
        changes = {DEVELOPER_KEY: enabled}
        if not enabled and self._load().get(MODE_KEY) == MODE_DEVELOPER:
            # Turning the display setting off while in developer mode
            # returns the app to the streamer workspace safely.
            changes[MODE_KEY] = MODE_STREAMER
        # update() re-reads strictly and merges under a lock: an
        # unreadable settings file aborts the save instead of being
        # overwritten, and other writers' keys cannot be lost.
        Settings.update(changes)
        return enabled

    def available_modes(self):
        modes = [MODE_STREAMER]
        if self.developer_enabled():
            modes.append(MODE_DEVELOPER)
        return modes

    @staticmethod
    def agency_available():
        """Agency requires future server-side authorization.

        Always False in this build — a license plan string, a local
        setting, or this display manager must never grant it.
        """
        return False

    def get_mode(self):
        saved = str(self._load().get(MODE_KEY) or '')
        if saved in self.available_modes():
            return saved
        return MODE_STREAMER

    def set_mode(self, mode):
        """Persist a mode switch. Returns False when not selectable."""
        if mode not in self.available_modes():
            return False
        Settings.update({MODE_KEY: mode})
        return True
