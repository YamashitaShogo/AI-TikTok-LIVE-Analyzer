"""Confirm navigation by URL, rather than trusting a synthetic scroll result."""
from urllib.parse import urlsplit

def url_key(url):
    if not url:
        return None
    parts = urlsplit(str(url))
    return parts.netloc.lower() + parts.path.rstrip('/')

class NavigationGuard:
    def __init__(self, cooldown=7, max_attempts=3):
        self.cooldown = cooldown
        self.max_attempts = max_attempts
        self.source = None
        self.attempts = 0
        self.requested_at = 0

    def begin(self, url, now):
        self.source = url_key(url)
        self.attempts = 1
        self.requested_at = now

    def observe(self, url, now):
        if not self.source:
            return None
        current = url_key(url)
        if current and current != self.source:
            self.source = None
            return 'confirmed'
        if now - self.requested_at < self.cooldown:
            return None
        self.requested_at = now
        if self.attempts < self.max_attempts:
            self.attempts += 1
            return 'retry'
        self.source = None
        return 'fallback'


class NavigationPause:
    """Temporary navigation failure pause; quota blocks always take priority."""
    def __init__(self, seconds=60):
        self.seconds = seconds
        self.resume_at = None

    def pause(self, now):
        self.resume_at = now + self.seconds

    def resume_if_due(self, now, blocked=False):
        if blocked or self.resume_at is None or now < self.resume_at:
            return False
        self.resume_at = None
        return True
