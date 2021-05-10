# -*- coding: utf-8 -*-
import threading
import time
from collections import defaultdict


class RateLimit:
    def __init__(self, limit: float = 2, per: float = 1, cleanup_delay: float = 60):
        self.limit = limit
        self.per = per
        self.cleanup_delay = cleanup_delay
        self._entries = defaultdict(list)

        # Start cleanup
        self._start_cleanup()

    def get_count(self, key):
        return len(
            [entry for entry in self._entries[key] if entry > time.time() - self.per]
        )

    def enter(self, key) -> int:
        # Add the entry
        self._entries[key].append(time.time())
        # Get entries within the limit
        recent_entries = [
            entry for entry in self._entries[key] if entry > time.time() - self.per
        ]

        if len(recent_entries) > self.limit:
            return len(recent_entries) - self.limit
        return 0

    async def aenter(self, key) -> int:
        # Add the entry
        self._entries[key].append(time.time())
        # Get entries within the limit
        recent_entries = [
            entry for entry in self._entries[key] if entry > time.time() - self.per
        ]

        if len(recent_entries) > self.limit:
            return len(recent_entries) - self.limit
        return 0

    def _start_cleanup(self):
        # Start up next iteration
        t = threading.Timer(self.cleanup_delay, self._cleanup)
        t.setDaemon(True)
        t.start()

    def _cleanup(self):
        self._start_cleanup()

        for key in [*self._entries.keys()]:
            # Similarly empty all irrelevant entries
            self._entries[key] = [
                entry for entry in self._entries[key] if entry > time.time() - self.per
            ]
