"""App-level general notes — persisted separately from session notes.

This module provides a simple notes store that is not tied to any
specific session.  It uses the same note dict schema as session notes:
  { id, text, status, created_at }

Storage: ~/.config/codehub/general_notes.json
"""

import json
import os
from dataclasses import dataclass, field
from typing import List

from codehub.utils.constants import CONFIG_DIR


@dataclass
class AppNotes:
    """Holds app-level (general) notes shared across all sessions."""
    name: str = "General Notes"
    notes: List[dict] = field(default_factory=list)
    plans: List[dict] = field(default_factory=list)
    ideas: List[dict] = field(default_factory=list)

class AppNotesRegistry:
    """Loads and persists the single app-level AppNotes object.

    Usage::

        registry = AppNotesRegistry()
        owner = registry.notes_obj   # pass to NotesDialog as notes_owner
        save  = registry.save        # pass to NotesDialog as save_fn
    """

    def __init__(self, config_dir: str = CONFIG_DIR):
        self._data = AppNotes()
        self.config_dir = config_dir
        self.notes_file = os.path.join(config_dir, "general_notes.json")
        self._load()

    @property
    def notes_obj(self) -> AppNotes:
        return self._data

    def save(self):
        """Persist the current notes list to disk."""
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            import tempfile
            tmp_fd, tmp_path = tempfile.mkstemp(dir=self.config_dir)
            with os.fdopen(tmp_fd, "w") as f:
                json.dump({"notes": self._data.notes, "plans": self._data.plans, "ideas": self._data.ideas}, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.notes_file)
        except IOError as e:
            print(f"[AppNotesRegistry] Failed to save: {e}")

    def _load(self):
        if not os.path.exists(self.notes_file):
            return
        try:
            with open(self.notes_file, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    self._data.notes = data
                else:
                    self._data.notes = data.get("notes", [])
                    self._data.plans = data.get("plans", [])
                    self._data.ideas = data.get("ideas", [])
        except (json.JSONDecodeError, IOError) as e:
            print(f"[AppNotesRegistry] Failed to load: {e}")
