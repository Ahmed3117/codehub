"""Session workspace — app bar + app container stack for multi-app sessions.

Each session gets a SessionWorkspace widget that contains:
  1. An App Bar (tab-style horizontal bar to switch between apps)
  2. An App Stack (Gtk.Stack holding one container per app)

The editor is always the first, pinned tab.  Additional apps can be added
via the "+" button and removed via right-click → Close.
"""

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango

from coder3.session_app import SessionApp
from coder3.utils.constants import (
    APPS, EDITORS,
    STATE_IDLE, STATE_STARTING, STATE_DISCOVERING,
    STATE_EMBEDDING, STATE_EXTERNAL, STATE_EMBEDDED, STATE_CLOSED, STATE_FAILED,
)


class AppTab(Gtk.EventBox):
    """A single tab in the session app bar."""

    def __init__(self, app_id: str, display_name: str, icon: str = "🔧",
                 is_editor: bool = False, closable: bool = True):
        super().__init__()
        self.app_id = app_id
        self.is_editor = is_editor
        self.get_style_context().add_class("app-tab")

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        hbox.set_margin_start(8)
        hbox.set_margin_end(4)
        hbox.set_margin_top(4)
        hbox.set_margin_bottom(4)

        # Icon
        icon_label = Gtk.Label(label=icon)
        icon_label.get_style_context().add_class("app-tab-icon")
        hbox.pack_start(icon_label, False, False, 0)

        # Name
        self.name_label = Gtk.Label(label=display_name)
        self.name_label.get_style_context().add_class("app-tab-name")
        self.name_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.name_label.set_max_width_chars(16)
        hbox.pack_start(self.name_label, False, False, 0)

        # Status indicator
        self.status_dot = Gtk.Label()
        self.status_dot.get_style_context().add_class("app-tab-status")
        hbox.pack_start(self.status_dot, False, False, 2)

        # Close button (not on pinned editor tab)
        if closable and not is_editor:
            close_btn = Gtk.Button(label="×")
            close_btn.set_relief(Gtk.ReliefStyle.NONE)
            close_btn.get_style_context().add_class("app-tab-close")
            close_btn.set_size_request(20, 20)
            close_btn.connect("clicked", self._on_close_clicked)
            hbox.pack_end(close_btn, False, False, 0)

        self.add(hbox)

        # Callbacks set by SessionWorkspace
        self.on_click = None   # (app_id)
        self.on_close = None   # (app_id)
        self.on_right_click = None  # (app_id, event)

        self.connect("button-press-event", self._on_button_press)

    def set_active(self, active: bool):
        """Highlight this tab as the active/selected one."""
        ctx = self.get_style_context()
        if active:
            ctx.add_class("app-tab-active")
        else:
            ctx.remove_class("app-tab-active")

    def update_status(self, state: str):
        """Update the status indicator dot."""
        status_map = {
            STATE_IDLE: ("○", "status-idle"),
            STATE_STARTING: ("◐", "status-starting"),
            STATE_DISCOVERING: ("◑", "status-discovering"),
            STATE_EMBEDDING: ("◓", "status-starting"),
            STATE_EXTERNAL: ("◉", "status-external"),
            STATE_EMBEDDED: ("●", "status-embedded"),
            STATE_CLOSED: ("○", "status-idle"),
            STATE_FAILED: ("✖", "status-failed"),
        }
        text, css_class = status_map.get(state, ("○", "status-idle"))
        self.status_dot.set_text(text)
        ctx = self.status_dot.get_style_context()
        for _, cls in status_map.values():
            ctx.remove_class(cls)
        ctx.add_class(css_class)

    def _on_button_press(self, widget, event):
        if event.button == 1:
            if self.on_click:
                self.on_click(self.app_id)
            return True
        elif event.button == 3:
            if self.on_right_click:
                self.on_right_click(self.app_id, event)
            return True
        return False

    def _on_close_clicked(self, button):
        if self.on_close:
            self.on_close(self.app_id)


class SessionWorkspace(Gtk.Box):
    """Full workspace widget for a session.

    Layout::

        ┌─────────────────────────────────────────────┐
        │  [Editor] [Postman] [Chrome]        [+ App] │  ← App Bar
        ├─────────────────────────────────────────────┤
        │                                             │
        │         Active App Container                │  ← App Stack
        │                                             │
        └─────────────────────────────────────────────┘
    """

    def __init__(self, session_id: str, editor_name: str = "Editor"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.session_id = session_id
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.get_style_context().add_class("session-workspace")

        # ── App Bar ──────────────────────────────────────────────────
        self.app_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.app_bar.get_style_context().add_class("session-app-bar")

        # Scrolled container for tabs (in case there are many)
        self._tabs_scroll = Gtk.ScrolledWindow()
        self._tabs_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self._tabs_scroll.set_shadow_type(Gtk.ShadowType.NONE)
        self._tabs_scroll.set_hexpand(True)

        self._tabs_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self._tabs_box.set_margin_start(4)
        self._tabs_box.get_style_context().add_class("session-tabs-box")
        self._tabs_scroll.add(self._tabs_box)

        self.app_bar.pack_start(self._tabs_scroll, True, True, 0)

        # Add App button
        self._add_app_btn = Gtk.Button(label="＋")
        self._add_app_btn.set_tooltip_text("Add application to this session")
        self._add_app_btn.get_style_context().add_class("add-app-btn")
        self._add_app_btn.set_size_request(36, 32)
        self.app_bar.pack_end(self._add_app_btn, False, False, 4)

        self.pack_start(self.app_bar, False, False, 0)

        # ── App Stack ────────────────────────────────────────────────
        self.app_stack = Gtk.Stack()
        self.app_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.app_stack.set_transition_duration(150)
        self.app_stack.set_hexpand(True)
        self.app_stack.set_vexpand(True)
        self.pack_start(self.app_stack, True, True, 0)

        # ── Internal state ───────────────────────────────────────────
        self._tabs: dict[str, AppTab] = {}         # app_id → AppTab
        self._containers: dict[str, Gtk.Box] = {}  # app_id → container box
        self._active_app_id: str = None
        self._editor_app_id: str = "editor"        # fixed ID for the editor

        # ── Public callbacks ─────────────────────────────────────────
        self.on_add_app = None          # (session_id)
        self.on_close_app = None        # (session_id, app_id)
        self.on_app_selected = None     # (session_id, app_id)
        self.on_restart_app = None      # (session_id, app_id)
        self.on_start_app = None        # (session_id, app_id)
        self.on_stop_app = None         # (session_id, app_id)

        # Wire the add button
        self._add_app_btn.connect("clicked", self._on_add_clicked)

        # Add the editor tab (always first, pinned)
        editor_info = EDITORS.get(editor_name, {})
        editor_display = editor_info.get("name", "Editor") if editor_info else "Editor"
        self.add_app_tab("editor", editor_display, icon="📝", is_editor=True)

    # ------------------------------------------------------------------
    # Tab management
    # ------------------------------------------------------------------

    def add_app_tab(self, app_id: str, display_name: str, icon: str = "🔧",
                    is_editor: bool = False, container: Gtk.Box = None) -> Gtk.Box:
        """Add a new app tab and its container to the workspace.

        Returns the container widget for this app slot.
        """
        # Create tab
        tab = AppTab(app_id, display_name, icon=icon,
                     is_editor=is_editor, closable=not is_editor)
        tab.on_click = self._on_tab_clicked
        tab.on_close = self._on_tab_close
        tab.on_right_click = self._on_tab_right_click
        self._tabs[app_id] = tab
        self._tabs_box.pack_start(tab, False, False, 0)
        tab.show_all()

        # Create container if not provided
        if container is None:
            container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            container.set_hexpand(True)
            container.set_vexpand(True)
            container.get_style_context().add_class("embed-container")
        self._containers[app_id] = container
        self.app_stack.add_named(container, app_id)
        container.show_all()

        # Auto-select if first tab
        if self._active_app_id is None:
            self.select_app(app_id)

        return container

    def remove_app_tab(self, app_id: str):
        """Remove an app tab and its container."""
        if app_id == self._editor_app_id:
            return  # Can't remove the editor

        tab = self._tabs.pop(app_id, None)
        if tab:
            self._tabs_box.remove(tab)
            tab.destroy()

        container = self._containers.pop(app_id, None)
        if container:
            self.app_stack.remove(container)
            container.destroy()

        # If the removed tab was active, switch to editor
        if self._active_app_id == app_id:
            self.select_app(self._editor_app_id)

    def select_app(self, app_id: str):
        """Switch to showing a specific app."""
        if app_id not in self._containers:
            return

        self._active_app_id = app_id
        self.app_stack.set_visible_child_name(app_id)

        # Update tab highlights
        for aid, tab in self._tabs.items():
            tab.set_active(aid == app_id)

        # Notify
        if self.on_app_selected:
            self.on_app_selected(self.session_id, app_id)

    def update_app_status(self, app_id: str, state: str):
        """Update the status indicator on a tab."""
        tab = self._tabs.get(app_id)
        if tab:
            tab.update_status(state)

    def get_container(self, app_id: str) -> Gtk.Box:
        """Get the embed container for an app."""
        return self._containers.get(app_id)

    def get_active_app_id(self) -> str:
        """Get the currently active app ID."""
        return self._active_app_id

    def get_app_ids(self) -> list[str]:
        """Get all app IDs in this workspace (including editor)."""
        return list(self._tabs.keys())

    def get_app_count(self) -> int:
        """Get the number of apps (including editor)."""
        return len(self._tabs)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_add_clicked(self, button):
        if self.on_add_app:
            self.on_add_app(self.session_id)

    def _on_tab_clicked(self, app_id: str):
        self.select_app(app_id)

    def _on_tab_close(self, app_id: str):
        if self.on_close_app:
            self.on_close_app(self.session_id, app_id)

    def _on_tab_right_click(self, app_id: str, event):
        """Show context menu on right-click."""
        menu = Gtk.Menu()

        tab = self._tabs.get(app_id)
        is_editor = tab.is_editor if tab else False

        if not is_editor:
            # Start / Stop
            start_item = Gtk.MenuItem(label="▶  Start")
            start_item.connect("activate",
                               lambda w: self.on_start_app(self.session_id, app_id) if self.on_start_app else None)
            menu.append(start_item)

            stop_item = Gtk.MenuItem(label="■  Stop")
            stop_item.connect("activate",
                              lambda w: self.on_stop_app(self.session_id, app_id) if self.on_stop_app else None)
            menu.append(stop_item)

            menu.append(Gtk.SeparatorMenuItem())

            # Close (remove) app
            close_item = Gtk.MenuItem(label="✖  Remove App")
            close_item.connect("activate",
                               lambda w: self.on_close_app(self.session_id, app_id) if self.on_close_app else None)
            menu.append(close_item)

        menu.show_all()
        menu.popup_at_pointer(event)
