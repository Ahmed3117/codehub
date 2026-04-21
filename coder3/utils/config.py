"""Application configuration management."""

import json
import os

from coder3.utils.constants import CONFIG_DIR, SETTINGS_FILE


def ensure_config_dir():
    """Create the config directory if it doesn't exist."""
    os.makedirs(CONFIG_DIR, exist_ok=True)


def load_settings():
    """Load application settings from disk."""
    ensure_config_dir()
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return get_default_settings()


def save_settings(settings):
    """Save application settings to disk."""
    ensure_config_dir()
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


def get_default_settings():
    """Return default application settings."""
    return {
        "window_width": 1400,
        "window_height": 900,
        "window_x": -1,
        "window_y": -1,
        "window_maximized": False,
        "sidebar_width": 280,
        "vscode_command": "code",
        "auto_embed": True,
        "restore_sessions_on_start": False,
        "last_active_session": None,
    }
