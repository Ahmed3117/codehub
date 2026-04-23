"""App-level general notes — persisted separately from session notes.

This module provides a simple notes store that is not tied to any
specific session.  It uses the same note dict schema as session notes:
  { id, text, status, created_at }

Storage: ~/.config/coder3/general_notes.json
"""

import json
import os
from dataclasses import dataclass, field
from typing import List

from coder3.utils.constants import CONFIG_DIR

_GENERAL_NOTES_FILE = os.path.join(CONFIG_DIR, "general_notes.json")


@dataclass
class AppNotes:
    """Holds app-level (general) notes shared across all sessions."""
    name: str = "General Notes"
    notes: List[dict] = field(default_factory=list)


class AppNotesRegistry:
    """Loads and persists the single app-level AppNotes object.

    Usage::

        registry = AppNotesRegistry()
        owner = registry.notes_obj   # pass to NotesDialog as notes_owner
        save  = registry.save        # pass to NotesDialog as save_fn
    """

    def __init__(self):
        self._data = AppNotes()
        self._load()

    @property
    def notes_obj(self) -> AppNotes:
        return self._data

    def save(self):
        """Persist the current notes list to disk."""
        os.makedirs(CONFIG_DIR, exist_ok=True)
        try:
            with open(_GENERAL_NOTES_FILE, "w") as f:
                json.dump(self._data.notes, f, indent=2)
        except IOError as e:
            print(f"[AppNotesRegistry] Failed to save: {e}")

    def _load(self):
        if not os.path.exists(_GENERAL_NOTES_FILE):
            return
        try:
            with open(_GENERAL_NOTES_FILE, "r") as f:
                self._data.notes = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[AppNotesRegistry] Failed to load: {e}")
