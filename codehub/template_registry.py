import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from codehub.utils.constants import CONFIG_DIR

@dataclass
class SessionTemplate:
    """A saved workspace preset (apps and editor)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    editor: str = "vscode"
    custom_editor_cmd: str = ""
    vscode_args: List[str] = field(default_factory=list)
    apps: List[dict] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


class TemplateRegistry:
    """Manages reusable session templates."""

    def __init__(self, config_dir: str = CONFIG_DIR):
        self._templates: dict[str, SessionTemplate] = {}
        self.config_dir = config_dir
        self.templates_file = os.path.join(config_dir, "templates.json")
        self._load()

    def _load(self):
        os.makedirs(self.config_dir, exist_ok=True)
        if os.path.exists(self.templates_file):
            try:
                with open(self.templates_file, "r") as f:
                    data = json.load(f)
                for item in data:
                    t = SessionTemplate.from_dict(item)
                    self._templates[t.id] = t
            except (json.JSONDecodeError, IOError) as e:
                print(f"[TemplateRegistry] Failed to load templates: {e}")

    def _save(self):
        os.makedirs(self.config_dir, exist_ok=True)
        data = [t.to_dict() for t in self._templates.values()]
        with open(self.templates_file, "w") as f:
            json.dump(data, f, indent=2)

    def add(self, template: SessionTemplate) -> SessionTemplate:
        self._templates[template.id] = template
        self._save()
        return template

    def remove(self, template_id: str) -> Optional[SessionTemplate]:
        t = self._templates.pop(template_id, None)
        if t:
            self._save()
        return t

    def update(self, template: SessionTemplate):
        if template.id in self._templates:
            self._templates[template.id] = template
            self._save()

    def get(self, template_id: str) -> Optional[SessionTemplate]:
        return self._templates.get(template_id)

    def get_all(self) -> List[SessionTemplate]:
        return sorted(self._templates.values(), key=lambda t: t.name.lower())
