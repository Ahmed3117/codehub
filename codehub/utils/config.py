"""Application configuration management."""

import json
import os

from codehub.utils.constants import CONFIG_DIR


def ensure_config_dir(config_dir: str = CONFIG_DIR):
    """Create the config directory if it doesn't exist."""
    os.makedirs(config_dir, exist_ok=True)


def load_settings(config_dir: str = CONFIG_DIR):
    """Load application settings from disk."""
    ensure_config_dir(config_dir)
    settings_file = os.path.join(config_dir, "settings.json")
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return get_default_settings()


def save_settings(settings, config_dir: str = CONFIG_DIR):
    """Save application settings to disk."""
    ensure_config_dir(config_dir)
    settings_file = os.path.join(config_dir, "settings.json")
    with open(settings_file, "w") as f:
        json.dump(settings, f, indent=2)


def get_default_settings():
    """Return default application settings."""
    return {
        "window_width": 1280,
        "window_height": 820,
        "window_x": -1,
        "window_y": -1,
        "window_maximized": False,
        "sidebar_width": 240,
        "vscode_command": "code",
        "auto_embed": True,
        "restore_sessions_on_start": False,
        "last_active_session": None,
        "pomodoro_work": 25,
        "pomodoro_short_break": 5,
        "pomodoro_long_break": 15,
        "pomodoro_cycles": 4,
        "general_total_time_seconds": 0,
        "general_time_since_reset": 0,
        "general_goal_time_seconds": 0,
    }
