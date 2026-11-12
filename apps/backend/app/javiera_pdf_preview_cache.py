"""Private bounded in-process PDF preview cache.

Fast path: identical approved workbook, same dossier content, same signed
matrix revisions and tenant -> reuse the PDF byte stream. Never share
entries between organizations; never write preview PDF or private data to
a global disk/cache/CDN. Emission PDFs are not cached by this module.

The digest key contains no plaintext identifiers, RUTs or worker names.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

TTL_SECONDS = 240.0
MAX_ITEMS = 12
MAX_BYTES = 32 * 1024 * 1024
MAX_SINGLE_PDF = 12 * 1024 * 1024


class PreviewPdfCache:
    def __init__(self, *, ttl: float = TTL_SECONDS, max_items: int = MAX_ITEMS,
                 max_bytes: int = MAX_BYTES):
        self.ttl, self.max_items, self.max_bytes = ttl, max_items, max_bytes
        self._lock = threading.RLock()
        self._items: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._size = 0

    def read(self, digest: str) -> bytes | None:
        with self._lock:
            now = time.monotonic()
            self._expire(now)
            value = self._items.get(digest)
            if value is None:
                return None
            self._items.move_to_end(digest)
            return value[1]

    def put(self, digest: str, payload: bytes) -> None:
        if not payload or len(payload) > min(self.max_bytes, MAX_SINGLE_PDF):
            return
        with self._lock:
            now = time.monotonic()
            self._expire(now)
            previous = self._items.pop(digest, None)
            if previous:
                self._size -= len(previous[1])
            self._items[digest] = (now + self.ttl, payload)
            self._size += len(payload)
            while len(self._items) > self.max_items or self._size > self.max_bytes:
                _, (_, old) = self._items.popitem(last=False)
                self._size -= len(old)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._size = 0

    def _expire(self, now: float) -> None:
        for key, (until, raw) in list(self._items.items()):
            if until <= now:
                del self._items[key]
                self._size -= len(raw)


pdf_preview_cache = PreviewPdfCache()
