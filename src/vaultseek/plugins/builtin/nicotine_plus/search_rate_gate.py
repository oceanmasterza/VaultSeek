"""Soulseek search flood protection for Nicotine+ outbound searches.

The Soulseek server does not publish exact search rate limits. Triggering
too many searches in a short span causes an automatic ~30 minute ban
(\"Do not quickly repeat a search\"). Community clients (e.g. Kima/slskd
integrations) serialize searches and space them apart; Nicotine+ wishlist
searches are even slower (server-scheduled, often 90–120 minutes).

VaultSeek defaults are intentionally conservative:
* at least ``min_interval_seconds`` between consecutive searches
* at most ``max_per_minute`` searches in any rolling 60-second window

The gate is **non-blocking** (``try_acquire``) so callers never freeze the
UI thread with ``time.sleep``. Deferred jobs stay queued for the next tick.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class SearchThrottled(Exception):
    """Raised when a Soulseek search must wait to avoid flood bans."""

    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = max(0.0, float(retry_after_seconds))
        super().__init__(
            f"Soulseek search rate-limited; retry in {self.retry_after_seconds:.1f}s"
        )


class SearchRateGate:
    """Process-wide gate that serializes and spaces Soulseek searches."""

    def __init__(
        self,
        *,
        min_interval_seconds: float = 5.0,
        max_per_minute: int = 8,
    ) -> None:
        self._lock = threading.Lock()
        self._min_interval = max(0.0, float(min_interval_seconds))
        self._max_per_minute = max(1, int(max_per_minute))
        self._last_search_at = 0.0
        self._timestamps: deque[float] = deque()

    def configure(
        self,
        *,
        min_interval_seconds: float | None = None,
        max_per_minute: int | None = None,
    ) -> None:
        with self._lock:
            if min_interval_seconds is not None:
                self._min_interval = max(0.0, float(min_interval_seconds))
            if max_per_minute is not None:
                self._max_per_minute = max(1, int(max_per_minute))

    @property
    def min_interval_seconds(self) -> float:
        return self._min_interval

    @property
    def max_per_minute(self) -> int:
        return self._max_per_minute

    def try_acquire(self) -> float | None:
        """Reserve a search slot without sleeping.

        Returns ``None`` on success, or seconds until the next attempt is allowed.
        """
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            delay = self._required_delay(now)
            if delay > 0.0:
                return delay
            self._last_search_at = now
            self._timestamps.append(now)
            return None

    def acquire(self) -> float:
        """Block until a search is allowed. Prefer ``try_acquire`` in app code."""
        waited = 0.0
        while True:
            delay = self.try_acquire()
            if delay is None:
                return waited
            chunk = min(delay, 0.25)
            time.sleep(chunk)
            waited += chunk

    def _prune(self, now: float) -> None:
        while self._timestamps and now - self._timestamps[0] >= 60.0:
            self._timestamps.popleft()

    def _required_delay(self, now: float) -> float:
        interval_wait = 0.0
        if self._last_search_at > 0.0:
            interval_wait = max(0.0, self._min_interval - (now - self._last_search_at))
        minute_wait = 0.0
        if len(self._timestamps) >= self._max_per_minute:
            oldest = self._timestamps[0]
            minute_wait = max(0.0, 60.0 - (now - oldest))
        return max(interval_wait, minute_wait)


# Shared across Nicotine+ provider instances in one process.
DEFAULT_SEARCH_RATE_GATE = SearchRateGate()
