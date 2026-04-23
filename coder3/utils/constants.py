"""Application-wide constants and defaults."""

import os

# App identity
APP_ID = "com.coder3.app"
APP_NAME = "Coder3"
APP_VERSION = "0.1.0"

# Paths
CONFIG_DIR = os.path.expanduser("~/.config/coder3")
SESSIONS_FILE = os.path.join(CONFIG_DIR, "sessions.json")
GROUPS_FILE = os.path.join(CONFIG_DIR, "groups.json")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")

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
SIDEBAR_WIDTH = 280
MIN_WINDOW_WIDTH = 1000
MIN_WINDOW_HEIGHT = 600
DEFAULT_WINDOW_WIDTH = 1400
DEFAULT_WINDOW_HEIGHT = 900

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
        "launch_args": ["--new-window", "--ozone-platform=x11", "{path}"],
    },
    "zed": {
        "name": "Zed",
        "command": "zed",
        "wm_class": "dev.zed.Zed",
        "embeddable": True,
        "launch_args": ["{path}"],
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
        "launch_args": ["-n", "{path}"],
    },
    "trae": {
        "name": "Trae",
        "command": "trae",
        "wm_class": "trae",
        "embeddable": True,
        "launch_args": ["--new-window", "--ozone-platform=x11", "{path}"],
    },
    "antigravity": {
        "name": "Antigravity",
        "command": "antigravity",
        "wm_class": "antigravity",
        "embeddable": True,
        "launch_args": ["{path}"],
    },
    "terminal": {
        "name": "Terminal",
        "command": "gnome-terminal",
        "wm_class": "gnome-terminal",
        # gnome-terminal does not implement XEMBED — embedding blocks all input.
        # Use external mode so the terminal window floats and remains interactive.
        "embeddable": False,
        "launch_args": ["--window", "--working-directory", "{path}"],
    },
    "nautilus": {
        "name": "File Manager (Nautilus)",
        "command": "nautilus",
        "wm_class": "org.gnome.Nautilus",
        # Nautilus (GTK4) does not support XEMBED at all.  External mode only.
        "embeddable": False,
        "launch_args": ["--new-window", "{path}"],
    },
    "nemo": {
        "name": "File Manager (Nemo)",
        "command": "nemo",
        "wm_class": "nemo",
        # Nemo (GTK3) embedding produces a frozen, non-interactive view.
        # External mode only.
        "embeddable": False,
        "launch_args": ["--new-window", "{path}"],
    },
    "custom": {
        "name": "Custom",
        "command": "",
        "wm_class": "",
        "embeddable": True,
        "launch_args": ["{path}"],
    },
}
