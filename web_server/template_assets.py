"""Bounded, stat-invalidated metadata and thumbnail cache for template assets."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import RLock

import cv2

from model_automation.vision import load_image


@dataclass(frozen=True)
class TemplateMetadata:
    width: int
    height: int
    size: int
    revision: str


class TemplateAssets:
    def __init__(self, *, max_entries: int = 128, max_bytes: int = 16 * 1024 * 1024) -> None:
        self.max_entries = max(1, max_entries)
        self.max_bytes = max(1, max_bytes)
        self._lock = RLock()
        self._metadata: OrderedDict[tuple, TemplateMetadata] = OrderedDict()
        self._thumbnails: OrderedDict[tuple, bytes] = OrderedDict()
        self._bytes = 0

    @staticmethod
    def _key(path: Path) -> tuple:
        resolved = path.resolve()
        stat = resolved.stat()
        return str(resolved), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size

    def metadata(self, path: Path) -> TemplateMetadata | None:
        with self._lock:
            try:
                key = self._key(path)
            except OSError:
                return None
            if key in self._metadata:
                self._metadata.move_to_end(key)
                return self._metadata[key]
            try:
                image = load_image(path)
            except (cv2.error, ValueError):
                return None
            if image is None:
                return None
            # Do not cache under the old version if an external editor changed it.
            try:
                if self._key(path) != key:
                    return None
            except OSError:
                return None
            revision = sha256(repr(key).encode('utf-8')).hexdigest()[:24]
            record = TemplateMetadata(int(image.shape[1]), int(image.shape[0]), key[-1], revision)
            self._metadata[key] = record
            while len(self._metadata) > self.max_entries:
                self._metadata.popitem(last=False)
            return record

    def thumbnail(self, path: Path, max_width: int) -> tuple[bytes, str] | None:
        with self._lock:
            try:
                source_key = self._key(path)
            except OSError:
                return None
            key = (*source_key, max_width)
            etag = '"' + sha256(repr(key).encode('utf-8')).hexdigest()[:32] + '"'
            cached = self._thumbnails.get(key)
            if cached is not None:
                self._thumbnails.move_to_end(key)
                return cached, etag
            try:
                image = load_image(path)
            except (cv2.error, ValueError):
                return None
            if image is None:
                return None
            if image.shape[1] > max_width:
                height = max(1, round(image.shape[0] * max_width / image.shape[1]))
                image = cv2.resize(image, (max_width, height), interpolation=cv2.INTER_AREA)
            success, encoded = cv2.imencode('.png', image)
            if not success:
                return None
            content = encoded.tobytes()
            try:
                unchanged = self._key(path) == source_key
            except OSError:
                unchanged = False
            if unchanged and len(content) <= self.max_bytes:
                self._thumbnails[key] = content
                self._bytes += len(content)
                while len(self._thumbnails) > self.max_entries or self._bytes > self.max_bytes:
                    _, removed = self._thumbnails.popitem(last=False)
                    self._bytes -= len(removed)
            return content, etag
