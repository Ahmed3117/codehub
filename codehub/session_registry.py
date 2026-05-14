"""Session registry — CRUD operations and persistence for coding sessions."""

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from codehub.utils.constants import (
    CONFIG_DIR,
    STATE_IDLE,
)


@dataclass
class Session:
    """Represents a single coding session."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    project_path: str = ""
    vscode_args: List[str] = field(default_factory=list)
    pid: Optional[int] = None
    xid: Optional[int] = None
    state: str = STATE_IDLE
    color: str = "#7aa2f7"  # Accent color for sidebar indicator
    created_at: str = ""
    last_opened: str = ""
    # Group membership (None = ungrouped)
    group_id: Optional[str] = None
    # Display order — used for manual ordering within same level
    order: int = 0
    # Editor: key into EDITORS dict, or "custom"
    editor: str = "vscode"
    # Custom editor command (used when editor == "custom")
    custom_editor_cmd: str = ""
    # Per-session notes and plans.  Each item is a dict with keys:
    #   id (str), text (str), status ("waiting"|"working"|"done"), created_at (str)
    notes: List[dict] = field(default_factory=list)
    # Per-session plans.
    plans: List[dict] = field(default_factory=list)
    # Per-session tasks (supports sub-tasks).
    tasks: List[dict] = field(default_factory=list)
    # Workspace apps — additional applications opened in this session (serialized
    # SessionApp dicts).  The editor itself is NOT stored here; it is implicit.
    apps: List[dict] = field(default_factory=list)
    # Custom environment variables (KEY=VALUE pairs)
    env_vars: dict = field(default_factory=dict)
    # Total time spent in this session (in seconds)
    total_time_seconds: int = 0
    # PIDs launched directly by CodeHub for the editor in this session
    spawned_pids: List[int] = field(default_factory=list)
    # Auto-start this session on CodeHub launch
    auto_start: bool = False
    start_time: float = 0.0
    # Searchable tags for filtering sessions
    tags: List[str] = field(default_factory=list)
    # Hide session from sidebar (soft-delete)
    hidden: bool = False
    # Time since last reset (separate from total_time_seconds)
    time_since_reset: int = 0
    # Goal time in seconds (0 = no goal)
    goal_time_seconds: int = 0
    # Runtime-only: whether this session's timer is paused
    paused: bool = False

    def to_dict(self):
        """Serialize to dict for JSON persistence (exclude runtime fields)."""
        d = asdict(self)
        # Don't persist runtime-only fields
        d.pop("pid", None)
        d.pop("xid", None)
        d.pop("state", None)
        d.pop("start_time", None)
        d.pop("paused", None)
        return d

    @classmethod
    def from_dict(cls, data):
        """Deserialize from a dict."""
        # Remove unknown keys gracefully
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


class SessionRegistry:
    """Manages all coding sessions with persistence."""

    def __init__(self, config_dir: str = CONFIG_DIR):
        self._sessions: dict[str, Session] = {}
        self.config_dir = config_dir
        self.sessions_file = os.path.join(config_dir, "sessions.json")
        self._load()

    def _load(self):
        """Load sessions from disk."""
        os.makedirs(self.config_dir, exist_ok=True)
        if os.path.exists(self.sessions_file):
            try:
                with open(self.sessions_file, "r") as f:
                    data = json.load(f)
                for item in data:
                    session = Session.from_dict(item)
                    session.state = STATE_IDLE
                    session.pid = None
                    session.xid = None
                    self._sessions[session.id] = session
            except (json.JSONDecodeError, IOError) as e:
                print(f"[SessionRegistry] Failed to load sessions: {e}")

    def _save(self):
        """Persist sessions to disk."""
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            data = [s.to_dict() for s in self._sessions.values()]
            import tempfile
            tmp_fd, tmp_path = tempfile.mkstemp(dir=self.config_dir)
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.sessions_file)
        except IOError as e:
            print(f"[SessionRegistry] Failed to save sessions: {e}")

    def add(self, session: Session) -> Session:
        """Add a new session."""
        self._sessions[session.id] = session
        self._save()
        return session

    def remove(self, session_id: str) -> Optional[Session]:
        """Remove a session by ID."""
        session = self._sessions.pop(session_id, None)
        if session:
            self._save()
        return session

    def update(self, session: Session):
        """Update an existing session."""
        if session.id in self._sessions:
            self._sessions[session.id] = session
            self._save()

    def get(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    def get_all(self) -> List[Session]:
        """Get all sessions ordered by (order, name)."""
        return sorted(self._sessions.values(), key=lambda s: (s.order, s.name.lower()))

    def get_by_group(self, group_id: Optional[str]) -> List[Session]:
        """Get all sessions for a given group_id (None = ungrouped)."""
        return sorted(
            [s for s in self._sessions.values() if s.group_id == group_id],
            key=lambda s: (s.order, s.name.lower()),
        )

    def count(self) -> int:
        """Return the number of sessions."""
        return len(self._sessions)

    def save(self):
        """Explicitly save to disk (e.g. after bulk order updates)."""
        self._save()
