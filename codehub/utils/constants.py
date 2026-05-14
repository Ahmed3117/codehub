"""Application-wide constants and defaults."""

import os

# App identity
APP_ID = "com.codehub.app"
APP_NAME = "CodeHub"
APP_VERSION = "0.1.1"

# Paths
CONFIG_DIR = os.path.expanduser("~/.config/codehub")

def _migrate_config():
    """Migrate config from old coder3 directory if needed."""
    old_dir = os.path.expanduser("~/.config/coder3")
    if os.path.exists(old_dir) and not os.path.exists(os.path.join(CONFIG_DIR, "sessions.json")):
        import shutil
        os.makedirs(CONFIG_DIR, exist_ok=True)
        print(f"Migrating configuration from {old_dir} to {CONFIG_DIR}...")
        for item in os.listdir(old_dir):
            s = os.path.join(old_dir, item)
            d = os.path.join(CONFIG_DIR, item)
            if not os.path.exists(d):
                try:
                    if os.path.isdir(s):
                        shutil.copytree(s, d)
                    else:
                        shutil.copy2(s, d)
                except Exception as e:
                    print(f"Failed to copy {item}: {e}")

_migrate_config()

SESSIONS_FILE = os.path.join(CONFIG_DIR, "sessions.json")
GROUPS_FILE = os.path.join(CONFIG_DIR, "groups.json")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
MODES_FILE = os.path.join(CONFIG_DIR, "modes.json")

# VS Code
VSCODE_COMMAND = "code"
VSCODE_WM_CLASS = "code"  # WM_CLASS for matching windows
VSCODE_WINDOW_WAIT_TIMEOUT = 15  # seconds to wait for VS Code window
VSCODE_POLL_INTERVAL = 200  # ms between polls for window discovery

# Window embedding
EMBED_RETRY_INTERVAL = 500  # ms between embed retries
EMBED_MAX_RETRIES = 30  # max retries before fallback

# Session states
STATE_IDLE = "idle"
STATE_STARTING = "starting"
STATE_DISCOVERING = "discovering"
STATE_EMBEDDING = "embedding"
STATE_EMBEDDED = "embedded"
STATE_EXTERNAL = "external"  # fallback mode
STATE_FAILED = "failed"
STATE_CLOSED = "closed"

# UI dimensions
SIDEBAR_WIDTH = 200
MIN_WINDOW_WIDTH = 900
MIN_WINDOW_HEIGHT = 600
DEFAULT_WINDOW_WIDTH = 1280
DEFAULT_WINDOW_HEIGHT = 820

# Colors (CSS-compatible)
COLORS = {
    "bg_dark": "#1a1b26",
    "bg_sidebar": "#16161e",
    "bg_header": "#1a1b26",
    "bg_content": "#24283b",
    "bg_hover": "#292e42",
    "bg_active": "#33394d",
    "bg_button": "#7aa2f7",
    "bg_button_hover": "#89b4fa",
    "bg_danger": "#f7768e",
    "bg_danger_hover": "#ff9e9e",
    "text_primary": "#c0caf5",
    "text_secondary": "#565f89",
    "text_accent": "#7aa2f7",
    "text_bright": "#ffffff",
    "border": "#292e42",
    "border_active": "#7aa2f7",
    "success": "#9ece6a",
    "warning": "#e0af68",
    "error": "#f7768e",
    "info": "#7dcfff",
}

# Editor definitions — each editor has:
#   name       : display name
#   command    : executable name (must be on PATH)
#   wm_class   : X11 WM_CLASS used for window discovery
#   launch_args: list of CLI args; {path} is replaced with the project path
EDITORS = {
    "vscode": {
        "name": "VS Code",
        "command": "code",
        "wm_class": "code",
        "embeddable": True,
        "icon": "📝",
        "launch_args": [
            "--new-window",
            "--disable-features=CalculateNativeWinOcclusion",
            "--ozone-platform=x11",
            "{path}",
        ],
    },
    "cursor": {
        "name": "Cursor",
        "command": "cursor",
        "wm_class": "cursor",
        "embeddable": True,
        "icon": "🚀",
        "launch_args": ["--new-window", "--ozone-platform=x11", "{path}"],
    },
    "zed": {
        "name": "Zed",
        "command": "zed",
        "wm_class": "dev.zed.Zed",
        "embeddable": True,
        "icon": "⚡",
        "launch_args": ["-n", "{path}"],
        # The `zed` command is a thin CLI launcher that exits immediately after
        # handing the project off to the long-running server.  The actual
        # background process is the `zed-editor` binary in libexec/ — that is
        # what must be targeted when killing all Zed instances.
        "process_names": ["zed-editor"],
    },
    "sublime": {
        "name": "Sublime Text",
        "command": "subl",
        "wm_class": "sublime_text",
        # Sublime Text does not properly implement XEMBED input focus — embedding
        # succeeds visually but keyboard/mouse input is broken.  Use external mode.
        "embeddable": False,
        "icon": "🧡",
        "launch_args": ["-n", "{path}"],
    },
    "trae": {
        "name": "Trae",
        "command": "trae",
        "wm_class": "Trae",
        "embeddable": True,
        "icon": "🎨",
        "launch_args": ["--new-window", "--ozone-platform=x11", "{path}"],
    },
    "antigravity": {
        "name": "Antigravity",
        "command": "antigravity",
        "wm_class": "Antigravity",
        "embeddable": True,
        "icon": "🧬",
        "launch_args": [
            "--new-window",
            "--disable-features=CalculateNativeWinOcclusion",
            "--ozone-platform=x11",
            "{path}",
        ],
    },
    "terminal": {
        "name": "Terminal",
        "command": "gnome-terminal",
        "wm_class": "gnome-terminal",
        # gnome-terminal does not implement XEMBED — embedding blocks all input.
        # Use external mode so the terminal window floats and remains interactive.
        "embeddable": False,
        "icon": "⬛",
        "launch_args": ["--window", "--working-directory", "{path}"],
    },
    "nautilus": {
        "name": "File Manager (Nautilus)",
        "command": "nautilus",
        "wm_class": "org.gnome.Nautilus",
        # Nautilus (GTK4) does not support XEMBED at all.  External mode only.
        "embeddable": False,
        "icon": "📁",
        "launch_args": ["--new-window", "{path}"],
    },
    "nemo": {
        "name": "File Manager (Nemo)",
        "command": "nemo",
        "wm_class": "nemo",
        # Nemo (GTK3) embedding produces a frozen, non-interactive view.
        # External mode only.
        "embeddable": False,
        "icon": "📁",
        "launch_args": ["--new-window", "{path}"],
    },
    "custom": {
        "name": "Custom",
        "command": "",
        "wm_class": "",
        "embeddable": True,
        "icon": "🔧",
        "launch_args": ["{path}"],
    },

}

# Workspace app definitions — general-purpose apps that can be launched inside
# a session workspace alongside the editor.  Unlike EDITORS, these do not open
# the project folder by default (though {path} can be used in launch_args).
#
# Each entry has:
#   name           : display name shown in the app bar / add-app dialog
#   command        : executable name (must be on PATH)
#   wm_class       : X11 WM_CLASS used for window discovery
#   launch_args    : list of CLI args; {path} is replaced with session project path
#   icon           : emoji/symbol for the app bar tab
#   isolation_args : extra CLI args appended to force a separate instance per
#                    session.  {session_id} is replaced with the session ID.
#                    Typically this sets a unique user-data-dir / profile so
#                    single-instance apps (Chrome, Postman, …) don't steal
#                    each other's windows.
APPS = {
    "postman": {
        "name": "Postman",
        "command": "postman",
        "wm_class": "postman",
        "launch_args": [],
        "icon": "📮",
        # Postman (Electron) respects --user-data-dir for process isolation
        "isolation_args": ["--user-data-dir=/tmp/codehub-postman-{session_id}"],
    },
    "chrome": {
        "name": "Google Chrome",
        "command": "google-chrome",
        "wm_class": "google-chrome",
        "launch_args": ["--new-window"],
        "icon": "🌐",
        # Separate user-data-dir forces a fully isolated Chrome process
        "isolation_args": ["--user-data-dir=/tmp/codehub-chrome-{session_id}"],
    },
    "firefox": {
        "name": "Firefox",
        "command": "firefox",
        "wm_class": "Navigator",
        "launch_args": ["--new-window"],
        "icon": "🦊",
        # -no-remote prevents connecting to an existing instance;
        # -profile gives it an isolated profile directory.
        "isolation_args": ["-no-remote", "-profile", "/tmp/codehub-firefox-{session_id}"],
    },
    "insomnia": {
        "name": "Insomnia",
        "command": "insomnia",
        "wm_class": "insomnia",
        "launch_args": [],
        "icon": "🌙",
        "isolation_args": ["--user-data-dir=/tmp/codehub-insomnia-{session_id}"],
    },
    "dbeaver": {
        "name": "DBeaver",
        "command": "dbeaver",
        "wm_class": "DBeaver",
        "launch_args": [],
        "icon": "🗄",
        "isolation_args": [],
    },
    "terminal": {
        "name": "Terminal",
        "command": "gnome-terminal",
        "wm_class": "gnome-terminal",
        "launch_args": ["--window", "--working-directory", "{path}"],
        "icon": "⬛",
        # gnome-terminal natively supports multiple windows per invocation
        "isolation_args": [],
    },
    "file_manager": {
        "name": "File Manager",
        "command": "nemo",
        "wm_class": "nemo",
        "launch_args": ["--new-window", "{path}"],
        "icon": "📁",
        "isolation_args": [],
    },
    "custom": {
        "name": "Custom App",
        "command": "",
        "wm_class": "",
        "launch_args": [],
        "icon": "🔧",
        "isolation_args": [],
    },
}


def get_app_info(app_type: str) -> dict:
    """Get app info from APPS or EDITORS dictionary."""
    info = APPS.get(app_type)
    if not info:
        info = EDITORS.get(app_type, APPS.get("custom", {}))
    return info
