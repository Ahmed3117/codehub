"""Session app — data model for workspace apps within a session.

Each session can host multiple applications (editor + Postman + Chrome + …).
The editor is always the first, pinned app.  Additional apps are tracked here.
"""

import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

from coder3.utils.constants import STATE_IDLE


@dataclass
class SessionApp:
    """A single application window within a session workspace."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    session_id: str = ""            # parent session ID
    app_type: str = ""              # key from APPS dict, or "custom"
    custom_command: str = ""        # custom launch command (when app_type == "custom")
    custom_wm_class: str = ""       # custom WM_CLASS for window discovery
    display_name: str = ""          # user-visible name (e.g. "Postman", "Chrome")
    icon: str = "🔧"               # emoji/symbol for the app bar tab
    # When True, the app window is shared across all active sessions —
    # it stays visible when switching sessions instead of being hidden.
    shared: bool = False

    # Runtime state — NOT persisted across restarts
    pid: Optional[int] = None
    xid: Optional[int] = None
    state: str = STATE_IDLE

    def to_dict(self) -> dict:
        """Serialize for JSON persistence (exclude runtime fields)."""
        d = asdict(self)
        d.pop("pid", None)
        d.pop("xid", None)
        d.pop("state", None)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SessionApp":
        """Deserialize from a dict."""
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    @property
    def slot_key(self) -> str:
        """Compound key used by EmbeddingManager / ProcessManager."""
        return f"{self.session_id}:{self.id}"
