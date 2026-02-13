"""In-memory activity log for Gmail sync operations."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime
from zoneinfo import ZoneInfo
import threading
from typing import Any


@dataclass
class GmailLogEntry:
    """Single Gmail activity log entry."""

    timestamp: str
    level: str
    action: str
    message: str
    details: dict[str, Any] | None = None


IST = ZoneInfo("Asia/Kolkata")


class GmailActivityLog:
    """Thread-safe bounded log store for Gmail sync events."""

    _MAX_ENTRIES = 600
    _entries: deque[GmailLogEntry] = deque(maxlen=_MAX_ENTRIES)
    _lock = threading.Lock()

    @classmethod
    def add(
        cls,
        *,
        level: str,
        action: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        entry = GmailLogEntry(
            timestamp=datetime.now(IST).isoformat(timespec="seconds"),
            level=level.lower(),
            action=action,
            message=message,
            details=details,
        )
        with cls._lock:
            cls._entries.append(entry)

    @classmethod
    def list(cls, limit: int = 200) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, cls._MAX_ENTRIES))
        with cls._lock:
            items = list(cls._entries)[-bounded:]
        items.reverse()
        return [asdict(item) for item in items]
