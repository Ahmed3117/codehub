"""Group registry — CRUD operations and persistence for session groups."""

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from codehub.utils.constants import CONFIG_DIR


@dataclass
class Group:
    """Represents a named group that organises sessions in the sidebar."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    color: str = "#7aa2f7"
    # When True the group's session rows are hidden in the sidebar
    collapsed: bool = False
    # Display order among top-level sidebar items
    order: int = 0
    # Soft-delete flag
    hidden: bool = False

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


class GroupRegistry:
    """Manages session groups with persistence."""

    def __init__(self, config_dir: str = CONFIG_DIR):
        self._groups: dict[str, Group] = {}
        self.config_dir = config_dir
        self.groups_file = os.path.join(config_dir, "groups.json")
        self._load()

    def _load(self):
        os.makedirs(self.config_dir, exist_ok=True)
        if os.path.exists(self.groups_file):
            try:
                with open(self.groups_file, "r") as f:
                    data = json.load(f)
                for item in data:
                    group = Group.from_dict(item)
                    self._groups[group.id] = group
            except (json.JSONDecodeError, IOError) as e:
                print(f"[GroupRegistry] Failed to load groups: {e}")

    def _save(self):
        os.makedirs(self.config_dir, exist_ok=True)
        data = [g.to_dict() for g in self._groups.values()]
        with open(self.groups_file, "w") as f:
            json.dump(data, f, indent=2)

    def add(self, group: Group) -> Group:
        self._groups[group.id] = group
        self._save()
        return group

    def remove(self, group_id: str) -> Optional[Group]:
        group = self._groups.pop(group_id, None)
        if group:
            self._save()
        return group

    def update(self, group: Group):
        if group.id in self._groups:
            self._groups[group.id] = group
            self._save()

    def get(self, group_id: str) -> Optional[Group]:
        return self._groups.get(group_id)

    def get_all(self) -> List[Group]:
        return sorted(self._groups.values(), key=lambda g: (g.order, g.name.lower()))

    def count(self) -> int:
        return len(self._groups)

    def save(self):
        """Explicitly save (e.g. after bulk order updates)."""
        self._save()
