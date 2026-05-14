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
from typing import Optional

from codehub.session_app import SessionApp
from codehub.utils.constants import (
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
        hbox.set_margin_start(7)
        hbox.set_margin_end(4)
        hbox.set_margin_top(4)
        hbox.set_margin_bottom(4)

        # Icon
        self.icon_label = Gtk.Label(label=icon)
        self.icon_label.get_style_context().add_class("app-tab-icon")
        hbox.pack_start(self.icon_label, False, False, 0)

        # Name
        self.name_label = Gtk.Label(label=display_name)
        self.name_label.get_style_context().add_class("app-tab-name")
        self.name_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.name_label.set_max_width_chars(16)
        hbox.pack_start(self.name_label, False, False, 0)

        # Status indicator
        self.status_dot = Gtk.Label()
        self.status_dot.get_style_context().add_class("app-tab-status")
        hbox.pack_start(self.status_dot, False, False, 0)

        # Close button (not on pinned editor tab)
        if closable and not is_editor:
            close_btn = Gtk.Button(label="✕")
            close_btn.set_relief(Gtk.ReliefStyle.NONE)
            close_btn.get_style_context().add_class("app-tab-close")
            close_btn.set_size_request(18, 18)
            close_btn.set_tooltip_text(f"Close {display_name}")
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
            STATE_STARTING: ("⚡", "status-starting"),
            STATE_DISCOVERING: ("🔍", "status-discovering"),
            STATE_EMBEDDING: ("📥", "status-starting"),
            STATE_EXTERNAL: ("↗", "status-external"),
            STATE_EMBEDDED: ("●", "status-embedded"),
            STATE_CLOSED: ("○", "status-idle"),
            STATE_FAILED: ("⚠️", "status-failed"),
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

        # Add Tasks button
        self._tasks_btn = Gtk.Button(label="✓")
        self._tasks_btn.set_tooltip_text("Tasks")
        self._tasks_btn.get_style_context().add_class("action-btn")
        self._tasks_btn.set_size_request(30, 28)
        self.app_bar.pack_end(self._tasks_btn, False, False, 4)

        # Add Plans button
        self._plans_btn = Gtk.Button(label="📋")
        self._plans_btn.set_tooltip_text("Plans")
        self._plans_btn.get_style_context().add_class("action-btn")
        self._plans_btn.set_size_request(30, 28)
        self.app_bar.pack_end(self._plans_btn, False, False, 4)

        # Add Notes button
        self._notes_btn = Gtk.Button(label="📝")
        self._notes_btn.set_tooltip_text("Notes")
        self._notes_btn.get_style_context().add_class("action-btn")
        self._notes_btn.set_size_request(30, 28)
        self.app_bar.pack_end(self._notes_btn, False, False, 4)

        # Add Terminal button
        self._terminal_btn = Gtk.Button(label=">_")
        self._terminal_btn.set_tooltip_text("Open Integrated Terminal")
        self._terminal_btn.get_style_context().add_class("action-btn")
        self._terminal_btn.set_size_request(34, 28)
        self.app_bar.pack_end(self._terminal_btn, False, False, 4)

        # Add App button
        self._add_app_btn = Gtk.Button(label="＋")
        self._add_app_btn.set_tooltip_text("Add application to this session")
        self._add_app_btn.get_style_context().add_class("add-app-btn")
        self._add_app_btn.set_size_request(30, 28)
        self.app_bar.pack_end(self._add_app_btn, False, False, 4)

        self.pack_start(self.app_bar, False, False, 0)

        # ── App Stack (Main Area) ────────────────────────────────────────────────
        self.main_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.main_paned.set_hexpand(True)
        self.main_paned.set_vexpand(True)
        self.pack_start(self.main_paned, True, True, 0)

        self.editor_stack = Gtk.Stack()
        self.editor_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.editor_stack.set_transition_duration(150)
        
        self.apps_stack = Gtk.Stack()
        self.apps_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.apps_stack.set_transition_duration(150)

        self.main_paned.pack1(self.editor_stack, resize=True, shrink=False)
        self.main_paned.pack2(self.apps_stack, resize=True, shrink=False)
        
        self.apps_stack.hide() # Hidden by default, editor takes full width


        # ── Internal state ───────────────────────────────────────────
        self._tabs: dict[str, AppTab] = {}         # app_id → AppTab
        self._containers: dict[str, Gtk.Box] = {}  # app_id → container box
        self._active_app_id: str = None
        self._editor_app_id: str = "editor"        # fixed ID for the editor
        self._drag_tab: Optional[AppTab] = None
        self._drag_highlight_tab: Optional[AppTab] = None

        # Split view state
        self._split_active: bool = False
        self._split_secondary: str = None

        # ── Public callbacks ─────────────────────────────────────────
        self.on_add_app = None          # (session_id)
        self.on_close_app = None        # (session_id, app_id)
        self.on_app_selected = None     # (session_id, app_id)
        self.on_restart_app = None      # (session_id, app_id)
        self.on_start_app = None        # (session_id, app_id)
        self.on_stop_app = None         # (session_id, app_id)
        self.on_open_terminal = None    # (session_id)
        self.on_kill_app = None         # (session_id, app_id)
        self.on_detach_app = None       # (session_id, app_id)
        self.on_duplicate_app = None    # (session_id, app_id)
        self.on_open_notes = None       # (session_id)
        self.on_open_plans = None       # (session_id)
        self.on_open_tasks = None       # (session_id)
        self.on_reorder_apps = None      # (session_id, app_ids)
        self.on_recover_app = None      # (session_id, app_id)
        self.on_rename_app = None       # (session_id, app_id)


        # Wire the add buttons
        self._add_app_btn.connect("clicked", self._on_add_clicked)
        self._terminal_btn.connect("clicked", self._on_terminal_clicked)
        self._notes_btn.connect("clicked", self._on_notes_clicked)
        self._plans_btn.connect("clicked", self._on_plans_clicked)
        self._tasks_btn.connect("clicked", self._on_tasks_clicked)

        # Add the editor tab (always first, pinned)
        if editor_name and editor_name != "none":
            editor_info = EDITORS.get(editor_name, {})
            editor_display = editor_info.get("name", "Editor") if editor_info else "Editor"
            editor_icon = editor_info.get("icon", "📝") if editor_info else "📝"
        else:
            editor_display = "No Editor"
            editor_icon = "📋"
        self.add_app_tab("editor", editor_display, icon=editor_icon, is_editor=True)

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

        # Enable DnD reordering (not for editor)
        if not is_editor:
            tab.drag_source_set(Gdk.ModifierType.BUTTON1_MASK,
                                 [Gtk.TargetEntry.new("application/x-codehub-tab", 0, 0)],
                                 Gdk.DragAction.MOVE)
            tab.connect("drag-begin", self._on_tab_drag_begin)
            tab.connect("drag-end", self._on_tab_drag_end)
            tab.connect("drag-data-get", self._on_tab_drag_data_get)

        tab.drag_dest_set(Gtk.DestDefaults.MOTION | Gtk.DestDefaults.HIGHLIGHT,
                           [Gtk.TargetEntry.new("application/x-codehub-tab", 0, 0)],
                           Gdk.DragAction.MOVE)
        tab.connect("drag-motion", self._on_tab_drag_motion)
        tab.connect("drag-drop", self._on_tab_drag_drop)
        tab.connect("drag-leave", self._on_tab_drag_leave)

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
        
        if is_editor:
            self.editor_stack.add_named(container, app_id)
        else:
            self.apps_stack.add_named(container, app_id)
            
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
            self.apps_stack.remove(container)
            container.destroy()

        # If the removed tab was active, switch to editor
        if self._active_app_id == app_id:
            self.select_app(self._editor_app_id)

    def select_app(self, app_id: str):
        """Switch to showing a specific app."""
        if app_id not in self._containers:
            return

        self._active_app_id = app_id
        if app_id == self._editor_app_id:
            self.editor_stack.set_visible_child_name(app_id)
            if not self._split_active:
                self.editor_stack.show()
                self.apps_stack.hide()
        else:
            self.apps_stack.set_visible_child_name(app_id)
            if not self._split_active:
                self.apps_stack.show()
                self.editor_stack.hide()

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

    def rename_app_tab(self, app_id: str, display_name: str):
        """Update the visible label and tooltip for an app tab."""
        tab = self._tabs.get(app_id)
        if tab:
            tab.name_label.set_text(display_name)
            tab.name_label.set_tooltip_text(display_name)

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

    def _on_terminal_clicked(self, button):
        if self.on_open_terminal:
            self.on_open_terminal(self.session_id)

    def _on_tab_clicked(self, app_id: str):
        self.select_app(app_id)

    def _on_tab_close(self, app_id: str):
        if self.on_close_app:
            self.on_close_app(self.session_id, app_id)

    def _on_notes_clicked(self, button):
        if self.on_open_notes:
            self.on_open_notes(self.session_id)

    def _on_plans_clicked(self, button):
        if self.on_open_plans:
            self.on_open_plans(self.session_id)

    def _on_tasks_clicked(self, button):
        if self.on_open_tasks:
            self.on_open_tasks(self.session_id)

    def _on_tab_drag_begin(self, tab, context):
        self._drag_tab = tab
        Gtk.drag_set_icon_name(context, "emblem-symbolic", 0, 0)

    def _on_tab_drag_data_get(self, tab, context, selection, info, timestamp):
        """Provide drag data so the DnD protocol is satisfied."""
        payload = tab.app_id.encode("utf-8")
        selection.set(selection.get_target(), 8, payload)

    def _on_tab_drag_end(self, tab, context):
        self._drag_tab = None
        self._clear_tab_highlight()

    def _on_tab_drag_motion(self, widget, context, x, y, timestamp):
        if self._drag_highlight_tab and self._drag_highlight_tab is not widget:
            self._clear_tab_highlight()
            
        if widget and widget is not self._drag_tab:
            alloc = widget.get_allocation()
            sc = widget.get_style_context()
            if x < alloc.width // 2:
                sc.remove_class("dnd-drop-after")
                sc.add_class("dnd-drop-before")
            else:
                sc.remove_class("dnd-drop-before")
                sc.add_class("dnd-drop-after")
            self._drag_highlight_tab = widget
            
        Gdk.drag_status(context, Gdk.DragAction.MOVE, timestamp)
        return True

    def _on_tab_drag_leave(self, widget, context, timestamp):
        self._clear_tab_highlight()

    def _clear_tab_highlight(self):
        if self._drag_highlight_tab:
            sc = self._drag_highlight_tab.get_style_context()
            sc.remove_class("dnd-drop-before")
            sc.remove_class("dnd-drop-after")
            self._drag_highlight_tab = None

    def _on_tab_drag_drop(self, widget, context, x, y, timestamp):
        """Handle a tab drop using the stored _drag_tab reference."""
        success = False
        if self._drag_tab:
            src_id = self._drag_tab.app_id
            dst_id = widget.app_id

            if src_id and dst_id and src_id != dst_id:
                alloc = widget.get_allocation()
                drop_before = x < alloc.width // 2
                self._reorder_tabs(src_id, dst_id, drop_before)
                success = True

        self._clear_tab_highlight()
        Gtk.drag_finish(context, success, False, timestamp)
        return True

    def _reorder_tabs(self, src_id: str, dst_id: str, drop_before: bool = True):
        """Move src_id tab to the position of dst_id."""
        tabs = self._tabs_box.get_children()
        src_tab = self._tabs.get(src_id)
        dst_tab = self._tabs.get(dst_id)

        if not src_tab or not dst_tab:
            return

        src_pos = -1
        dst_pos = -1

        for i, tab in enumerate(tabs):
            if tab == src_tab:
                src_pos = i
            if tab == dst_tab:
                dst_pos = i

        if src_pos != -1 and dst_pos != -1:
            new_pos = dst_pos
            if not drop_before:
                new_pos += 1
            
            # Prevent moving things to index 0 (editor spot)
            if new_pos == 0:
                new_pos = 1
            
            self._tabs_box.reorder_child(src_tab, new_pos)

            # Notify caller to persist order
            if self.on_reorder_apps:
                # Build new list of app IDs (excluding 'editor' which is always first)
                new_ids = []
                for tab in self._tabs_box.get_children():
                    if tab.app_id != "editor":
                        new_ids.append(tab.app_id)
                self.on_reorder_apps(self.session_id, new_ids)

    def _on_tab_right_click(self, app_id: str, event):
        """Show context menu on right-click."""
        menu = Gtk.Menu()

        tab = self._tabs.get(app_id)
        is_editor = tab.is_editor if tab else False

        # Kill
        kill_item = Gtk.MenuItem(label="☠  Process Control")
        kill_item.connect("activate", lambda w: self.on_kill_app(self.session_id, app_id) if hasattr(self, "on_kill_app") and self.on_kill_app else None)
        menu.append(kill_item)

        # Restart
        restart_item = Gtk.MenuItem(label="🔄  Restart via Process Control")
        restart_item.connect("activate", lambda w: self.on_restart_app(self.session_id, app_id) if hasattr(self, "on_restart_app") and self.on_restart_app else None)
        menu.append(restart_item)

        # Recover / Re-embed
        recover_item = Gtk.MenuItem(label="🧲  Attempt Re-embed")
        recover_item.connect("activate", lambda w: self.on_recover_app(self.session_id, app_id) if hasattr(self, "on_recover_app") and self.on_recover_app else None)
        menu.append(recover_item)

        menu.append(Gtk.SeparatorMenuItem())

        if not is_editor:
            rename_item = Gtk.MenuItem(label="✎  Rename App")
            rename_item.connect(
                "activate",
                lambda w: self.on_rename_app(self.session_id, app_id)
                if self.on_rename_app else None,
            )
            menu.append(rename_item)

            menu.append(Gtk.SeparatorMenuItem())

            # Start / Stop
            start_item = Gtk.MenuItem(label="▶  Start")
            start_item.connect("activate",
                               lambda w: self.on_start_app(self.session_id, app_id) if hasattr(self, "on_start_app") and self.on_start_app else None)
            menu.append(start_item)

            stop_item = Gtk.MenuItem(label="■  Stop")
            stop_item.connect("activate",
                              lambda w: self.on_stop_app(self.session_id, app_id) if hasattr(self, "on_stop_app") and self.on_stop_app else None)
            menu.append(stop_item)

            menu.append(Gtk.SeparatorMenuItem())

        # Split View toggle
        split_item = Gtk.MenuItem(label="⊟  Split View with Editor" if not is_editor else "⊟  Toggle Split View")
        split_item.connect("activate", lambda w, aid=app_id: self._toggle_split_view(aid))
        menu.append(split_item)

        if not is_editor:
            # Detach — open in external floating window
            detach_item = Gtk.MenuItem(label="⇱  Detach to Window")
            detach_item.connect("activate",
                                lambda w, aid=app_id: self.on_detach_app(self.session_id, aid)
                                if hasattr(self, "on_detach_app") and self.on_detach_app else None)
            menu.append(detach_item)

            # Duplicate — add another instance of the same app
            dup_item = Gtk.MenuItem(label="⧉  Duplicate App")
            dup_item.connect("activate",
                             lambda w, aid=app_id: self.on_duplicate_app(self.session_id, aid)
                             if hasattr(self, "on_duplicate_app") and self.on_duplicate_app else None)
            menu.append(dup_item)

            menu.append(Gtk.SeparatorMenuItem())

            # Close (remove) app
            close_item = Gtk.MenuItem(label="✖  Remove App")
            close_item.connect("activate",
                               lambda w: self.on_close_app(self.session_id, app_id) if hasattr(self, "on_close_app") and self.on_close_app else None)
            menu.append(close_item)

        menu.show_all()
        menu.popup_at_pointer(event)

    # ------------------------------------------------------------------
    # Split View
    # ------------------------------------------------------------------

    def _toggle_split_view(self, secondary_app_id: str):
        """Toggle a side-by-side split between editor and *secondary_app_id*."""
        if self._split_active:
            self._exit_split_view()
        else:
            self._enter_split_view(secondary_app_id)

    def _enter_split_view(self, secondary_app_id: str):
        """Rearrange the workspace into a horizontal pane with two live views."""
        if self._split_active:
            return
        if secondary_app_id == "editor":
            return  # Nothing to split against

        # Show both stacks
        self.editor_stack.set_visible_child_name("editor")
        self.apps_stack.set_visible_child_name(secondary_app_id)
        
        self.editor_stack.show()
        self.apps_stack.show()
        
        # Approximate 50/50 split
        width = self.get_allocated_width()
        if width > 100:
            self.main_paned.set_position(width // 2)
        else:
            self.main_paned.set_position(600)
            
        self.main_paned.get_style_context().add_class("split-paned")

        self._split_active = True
        self._split_secondary = secondary_app_id

        # Highlight both tabs
        for aid, tab in self._tabs.items():
            tab.set_active(aid in ("editor", secondary_app_id))

    def _exit_split_view(self):
        """Restore normal single-app view from split mode."""
        if not self._split_active:
            return

        self.main_paned.get_style_context().remove_class("split-paned")
        self._split_active = False
        self._split_secondary = None

        self.select_app("editor")
        self._split_secondary = None

        self.select_app("editor")

    def set_enabled(self, enabled: bool):
        """Enable or disable the entire workspace UI based on Mode rules."""
        self.set_sensitive(enabled)
        if not enabled:
            self.set_opacity(0.2)
        else:
            self.set_opacity(1.0)
