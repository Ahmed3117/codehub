"""Session history — logs session usage over time.

Stores a record every time a session is stopped, capturing the session
name, start time, stop time, and duration.  Persisted to:
  ~/.config/codehub/session_history.json
"""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import List, Optional

from codehub.utils.constants import CONFIG_DIR
_MAX_HISTORY_ENTRIES = 500  # Cap to prevent the file from growing forever


@dataclass
class HistoryEntry:
    """A single session usage record."""
    session_id: str = ""
    session_name: str = ""
    started_at: str = ""
    stopped_at: str = ""
    duration_seconds: int = 0
    editor: str = ""
    data: dict = field(default_factory=dict)


class SessionHistoryRegistry:
    """Manages the session history log."""

    def __init__(self, config_dir: str = CONFIG_DIR):
        self._entries: List[dict] = []
        self.config_dir = config_dir
        self.history_file = os.path.join(config_dir, "session_history.json")
        self._load()

    def add_entry(self, session_id: str, session_name: str,
                  duration_seconds: int, editor: str = "",
                  started_at: str = "", stopped_at: str = "",
                  data: dict = None):
        """Record a session usage entry."""
        entry = HistoryEntry(
            session_id=session_id,
            session_name=session_name,
            started_at=started_at or "",
            stopped_at=stopped_at or datetime.now().isoformat(),
            duration_seconds=duration_seconds,
            editor=editor,
            data=data or {},
        )
        self._entries.append(asdict(entry))
        # Trim to max size
        if len(self._entries) > _MAX_HISTORY_ENTRIES:
            self._entries = self._entries[-_MAX_HISTORY_ENTRIES:]
        self._save()

    def get_all(self) -> List[dict]:
        """Return all history entries, most recent first."""
        return list(reversed(self._entries))

    def clear(self):
        """Clear all history."""
        self._entries.clear()
        self._save()

    def _load(self):
        if not os.path.exists(self.history_file):
            return
        try:
            with open(self.history_file, "r") as f:
                self._entries = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[SessionHistory] Failed to load: {e}")

    def _save(self):
        os.makedirs(self.config_dir, exist_ok=True)
        try:
            with open(self.history_file, "w") as f:
                json.dump(self._entries, f, indent=2)
        except IOError as e:
            print(f"[SessionHistory] Failed to save: {e}")
