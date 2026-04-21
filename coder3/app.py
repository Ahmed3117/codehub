"""Coder3 — Main GTK Application.

A desktop application that embeds editor windows inside a host application
using X11 native window reparenting on Linux.
"""

import os
import sys
import signal
import threading
from typing import Optional

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Gio

from coder3 import __version__, __app_id__
from coder3.session_registry import Session, SessionRegistry
from coder3.group_registry import Group, GroupRegistry
from coder3.process_manager import ProcessManager
from coder3.window_discovery import WindowDiscovery
from coder3.embedding_manager import EmbeddingManager
from coder3.ui.header_bar import HeaderBar
from coder3.ui.sidebar import Sidebar, SessionRow, GroupRow
from coder3.ui.content_area import ContentArea
from coder3.ui.session_dialog import SessionDialog, GroupDialog
from coder3.utils.config import load_settings, save_settings
from coder3.utils.constants import (
    APP_NAME, APP_ID,
    MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT,
    STATE_IDLE, STATE_STARTING, STATE_DISCOVERING,
    STATE_EMBEDDING, STATE_EMBEDDED, STATE_EXTERNAL, STATE_FAILED, STATE_CLOSED,
    VSCODE_POLL_INTERVAL, VSCODE_WINDOW_WAIT_TIMEOUT,
    EDITORS,
)


class Coder3App(Gtk.Application):
    """Main application class."""

    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )

        self.window = None
        self.registry = SessionRegistry()
        self.group_registry = GroupRegistry()
        self.process_mgr = ProcessManager()
        self.window_discovery = WindowDiscovery()
        self.embedding_mgr = EmbeddingManager()
        self.settings = load_settings()

        self._active_session_id = None
        self._health_check_id = None
        self._sidebar_visible = True
        self._launch_tokens: dict[str, int] = {}
        # Saved width used when restoring sidebar after toggle-off
        self._saved_sidebar_width = self.settings.get("sidebar_width", 280)

    def do_activate(self):
        """Called when the application is activated."""
        if self.window:
            self.window.present()
            return

        self._load_css()
        self._create_window()
        self._populate_sessions()
        self._setup_keybindings()
        self._start_health_check()

        self.window.show_all()

    def _load_css(self):
        """Load the GTK CSS stylesheet."""
        css_provider = Gtk.CssProvider()
        css_path = os.path.join(os.path.dirname(__file__), "ui", "styles.css")
        try:
            css_provider.load_from_path(css_path)
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        except Exception as e:
            print(f"[App] Failed to load CSS: {e}")

    def _create_window(self):
        """Create the main application window."""
        self.window = Gtk.ApplicationWindow(application=self)
        self.window.set_title(APP_NAME)
        self.window.get_style_context().add_class("main-window")
        self.window.set_default_size(
            self.settings.get("window_width", DEFAULT_WINDOW_WIDTH),
            self.settings.get("window_height", DEFAULT_WINDOW_HEIGHT),
        )
        self.window.set_size_request(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

        # Restore position
        x = self.settings.get("window_x", -1)
        y = self.settings.get("window_y", -1)
        if x >= 0 and y >= 0:
            self.window.move(x, y)

        if self.settings.get("window_maximized", False):
            self.window.maximize()

        # ── Header bar ────────────────────────────────────────────────
        self.headerbar = HeaderBar()
        self.headerbar.add_btn.connect("clicked", lambda b: self._on_new_session())
        self.headerbar.on_about = self._on_about
        self.headerbar.on_quit = self._on_quit
        self.headerbar.on_sidebar_toggle = self._on_toggle_sidebar
        self.headerbar.on_kill_editor_processes = self._on_kill_editor_processes
        self.window.set_titlebar(self.headerbar)

        # ── Main layout — horizontal pane ─────────────────────────────
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)

        # ── Sidebar ───────────────────────────────────────────────────
        self.sidebar = Sidebar()

        # Wire all sidebar callbacks BEFORE populate (rebuild() uses them)
        self.sidebar.on_start_session = self._on_start_session
        self.sidebar.on_stop_session = self._on_stop_session
        self.sidebar.on_start_all = self._on_start_all_sessions
        self.sidebar.on_stop_all = self._on_stop_all_sessions
        self.sidebar.on_new_group = self._on_new_group
        self.sidebar.on_reorder = self._on_reorder
        self.sidebar.on_group_toggle = self._on_group_toggle

        # ListBox signals
        self.sidebar.listbox.connect("row-selected", self._on_session_selected)
        self.sidebar.listbox.connect("row-activated", self._on_session_activated)
        self.sidebar.listbox.connect("button-press-event", self._on_sidebar_button_press)

        self.paned.pack1(self.sidebar, resize=False, shrink=False)

        # ── Content area ──────────────────────────────────────────────
        self.content = ContentArea()
        self.content.on_new_session = self._on_new_session
        self.paned.pack2(self.content, resize=True, shrink=False)

        # Set pane position
        self.paned.set_position(self.settings.get("sidebar_width", 280))

        self.window.add(self.paned)

        # Window events
        self.window.connect("delete-event", self._on_delete)
        self.window.connect("configure-event", self._on_configure)

    def _populate_sessions(self):
        """Load sessions and groups from registries into the sidebar."""
        sessions = self.registry.get_all()
        groups = self.group_registry.get_all()

        # Rebuild the sidebar (callbacks already wired on self.sidebar)
        self.sidebar.rebuild(sessions, groups)

        # Create embedding containers for every session
        for session in sessions:
            container = self.embedding_mgr.create_container(session.id)
            self.content.add_session_container(session.id, container)

    def _setup_keybindings(self):
        """Set up keyboard shortcuts."""
        accel_group = Gtk.AccelGroup()
        self.window.add_accel_group(accel_group)

        # Ctrl+N — New session
        key, mod = Gtk.accelerator_parse("<Control>n")
        accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                           lambda *a: self._on_new_session())

        # Ctrl+W — Close/stop active session
        key, mod = Gtk.accelerator_parse("<Control>w")
        accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                           lambda *a: self._on_stop_session())

        # Ctrl+Q — Quit
        key, mod = Gtk.accelerator_parse("<Control>q")
        accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                           lambda *a: self._on_quit())

        # Ctrl+Return — Start active session
        key, mod = Gtk.accelerator_parse("<Control>Return")
        accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                           lambda *a: self._on_start_session())

        # Ctrl+Shift+R — Force restart active session
        key, mod = Gtk.accelerator_parse("<Control><Shift>r")
        accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                           lambda *a: self._on_force_restart_session())

        # Ctrl+B — Toggle sidebar
        key, mod = Gtk.accelerator_parse("<Control>b")
        accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                           lambda *a: self._on_toggle_sidebar())

    def _start_health_check(self):
        """Periodically check for dead editor windows.

        Uses XID-based window liveness checks instead of PID polling,
        because the `code` CLI wrapper exits immediately.
        """
        def check():
            dead = self.process_mgr.check_dead_sessions()
            for session_id in dead:
                session = self.registry.get(session_id)
                if session and session.state not in (STATE_IDLE, STATE_CLOSED):
                    print(f"[App] Session {session_id} window died, marking as closed")
                    session.state = STATE_CLOSED
                    session.pid = None
                    session.xid = None
                    self.sidebar.update_status(session_id, STATE_CLOSED)
                    self.embedding_mgr.unembed_window(session_id)
            return True  # Keep running

        self._health_check_id = GLib.timeout_add_seconds(5, check)

    # =========================================
    # Sidebar toggle
    # =========================================

    def _on_toggle_sidebar(self):
        """Show or hide the sidebar panel."""
        if self._sidebar_visible:
            self._saved_sidebar_width = self.paned.get_position()
            self.settings["sidebar_width"] = self._saved_sidebar_width
            self.sidebar.hide()
            self._sidebar_visible = False
        else:
            self.sidebar.show_all()
            self.paned.set_position(self.settings.get("sidebar_width", 280))
            self._sidebar_visible = True

    # =========================================
    # Batch session actions
    # =========================================

    def _on_start_all_sessions(self):
        """Start every idle/closed/failed session."""
        for session in self.registry.get_all():
            if session.state in (STATE_IDLE, STATE_CLOSED, STATE_FAILED):
                self._on_start_session(session.id)

    def _on_stop_all_sessions(self):
        """Stop every running session."""
        for session in self.registry.get_all():
            if session.state in (STATE_STARTING, STATE_DISCOVERING,
                                 STATE_EMBEDDING, STATE_EMBEDDED, STATE_EXTERNAL):
                self._on_stop_session(session.id)

    # =========================================
    # Session actions
    # =========================================

    def _on_new_session(self):
        """Show the new session dialog."""
        groups = self.group_registry.get_all()
        dialog = SessionDialog(self.window, groups=groups)
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            valid, error = dialog.validate()
            if valid:
                session = dialog.get_session()
                # Assign a sensible default order
                session.order = self.registry.count()
                self.registry.add(session)

                self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())

                # Create embedding container
                container = self.embedding_mgr.create_container(session.id)
                self.content.add_session_container(session.id, container)

                # Select the new session
                self.sidebar.select_session(session.id)
            else:
                self._show_error("Validation Error", error)

        dialog.destroy()

    def _on_edit_session(self, session_id: str):
        """Show the edit session dialog."""
        session = self.registry.get(session_id)
        if not session:
            return

        groups = self.group_registry.get_all()
        dialog = SessionDialog(self.window, session=session, groups=groups)
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            valid, error = dialog.validate()
            if valid:
                updated = dialog.get_session()
                self.registry.update(updated)
                self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())
                self.sidebar.select_session(updated.id)
            else:
                self._show_error("Validation Error", error)

        dialog.destroy()

    def _on_remove_session(self, session_id: str):
        """Remove a session after confirmation."""
        session = self.registry.get(session_id)
        if not session:
            return

        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"Remove session '{session.name}'?",
        )
        dialog.format_secondary_text(
            "This will stop any running editor instance and remove the session."
        )

        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES:
            self._next_launch_token(session_id)
            self.process_mgr.terminate(session_id)
            self.embedding_mgr.remove_session(session_id)
            self.content.remove_session_container(session_id)
            self.sidebar.remove_session(session_id)
            self.registry.remove(session_id)

            if self._active_session_id == session_id:
                self._active_session_id = None
                self.content.show_empty()
                self.headerbar.set_session_info("")

    def _on_session_activated(self, listbox, row):
        """Handle double-click / Enter on a session row — start the session."""
        if not isinstance(row, SessionRow):
            return
        session_id = row.session.id
        session = self.registry.get(session_id)
        if session and session.state in (STATE_IDLE, STATE_CLOSED, STATE_FAILED):
            self._on_start_session(session_id)
        elif session and session.state == STATE_EMBEDDED:
            self.embedding_mgr.focus_embedded(session_id)
        elif session and session.state == STATE_EXTERNAL:
            self._focus_session_window(session_id)

    def _next_launch_token(self, session_id: str) -> int:
        """Invalidate prior async launch work and return a fresh token."""
        token = self._launch_tokens.get(session_id, 0) + 1
        self._launch_tokens[session_id] = token
        return token

    def _is_current_launch_token(self, session_id: str, launch_token: Optional[int]) -> bool:
        """Check whether an async callback still belongs to the latest launch."""
        return launch_token is None or self._launch_tokens.get(session_id) == launch_token

    def _set_session_closed(self, session: Session, header_status: str = "Stopped"):
        """Reset transient session state after stopping or restarting."""
        session.state = STATE_CLOSED
        session.pid = None
        session.xid = None
        self.sidebar.update_status(session.id, STATE_CLOSED)
        self.headerbar.set_session_info(session.name, header_status)

    def _find_session_window_xid(self, session: Session) -> Optional[int]:
        """Locate the current top-level window for a session."""
        if session.xid and self.window_discovery._is_window_visible(session.xid):
            return session.xid

        editor_info = EDITORS.get(session.editor, EDITORS["vscode"])
        wm_class = editor_info.get("wm_class", "")
        project_basename = os.path.basename(session.project_path.rstrip("/")).lower()

        if session.pid and wm_class:
            xid = self.window_discovery.find_window_by_pid(
                session.pid,
                wm_class=wm_class,
                project_path=session.project_path,
                timeout=1,
                poll_interval=0.2,
            )
            if xid:
                return xid

        if wm_class:
            visible = self.window_discovery.get_visible_main_windows_by_class(wm_class)
            if project_basename:
                for xid, title in visible.items():
                    if project_basename in title.lower():
                        return xid
            if len(visible) == 1:
                return next(iter(visible))

        return None

    def _focus_session_window(self, session_id: str):
        """Focus the running window for a session, embedded or external."""
        session = self.registry.get(session_id)
        if not session:
            return False

        if session.state == STATE_EMBEDDED:
            self.embedding_mgr.focus_embedded(session_id)
            return False

        xid = self._find_session_window_xid(session)
        if xid:
            session.xid = xid
            self.process_mgr.set_xid(session_id, xid)
            self.embedding_mgr.focus_xid(xid)
        return False

    def _is_editor_still_open_elsewhere(self, session: Session, exclude_xids: Optional[set[int]] = None) -> bool:
        """Return True when the editor still has other visible main windows."""
        exclude_xids = exclude_xids or set()
        editor_info = EDITORS.get(session.editor, EDITORS["vscode"])
        wm_class = editor_info.get("wm_class", "")
        if not wm_class:
            return False

        visible = self.window_discovery.get_visible_main_windows_by_class(wm_class)
        return any(xid not in exclude_xids for xid in visible)

    def _shutdown_session_runtime(self, session: Session, kill_editor_if_last_window: bool = False):
        """Stop a session and optionally kill the editor process when it owns no other windows."""
        matching_xids = self._find_matching_editor_windows(session)
        tracked_xid = session.xid

        self.process_mgr.terminate(session.id)
        self.embedding_mgr.unembed_window(session.id)

        if kill_editor_if_last_window and tracked_xid and not self._is_editor_still_open_elsewhere(session, {tracked_xid}):
            self.process_mgr.terminate_window_owner(tracked_xid)

        self.process_mgr.forget(session.id)
        self._set_session_closed(session, "Stopped")

    def _schedule_embedded_focus(self, session_id: str, delays_ms=(250, 500, 900)):
        """Retry focus handoff after session switches and fresh embeds."""
        def focus_once():
            if self._active_session_id != session_id:
                return False

            session = self.registry.get(session_id)
            if not session or session.state != STATE_EMBEDDED:
                return False

            self.embedding_mgr.focus_embedded(session_id)
            return False

        for delay in delays_ms:
            GLib.timeout_add(delay, focus_once)

    def _find_matching_editor_windows(self, session: Session) -> list[int]:
        """Find tracked or discoverable windows that likely belong to this session."""
        xids: list[int] = []

        if session.xid:
            xids.append(session.xid)

        editor_info = EDITORS.get(session.editor, EDITORS["vscode"])
        wm_class = editor_info.get("wm_class", "")
        project_basename = os.path.basename(session.project_path.rstrip("/")).lower()

        if wm_class and project_basename:
            for xid, title in self.window_discovery.snapshot_windows(wm_class).items():
                if project_basename in title.lower() and xid not in xids:
                    xids.append(xid)

        return xids

    def _restart_session_after_force_close(self, session_id: str):
        """Start a session after the force-close grace period finishes."""
        self._on_start_session(session_id, reuse_existing=False)
        return False

    def _on_start_session(self, session_id: str = None, reuse_existing: bool = True):
        """Launch the editor for a session and begin the embedding process."""
        if session_id is None:
            session_id = self._active_session_id
        if session_id is None:
            return

        session = self.registry.get(session_id)
        if not session:
            return

        # Don't re-launch if already running
        if session.state in (STATE_STARTING, STATE_DISCOVERING, STATE_EMBEDDING, STATE_EMBEDDED):
            if session.state == STATE_EMBEDDED:
                self.embedding_mgr.focus_embedded(session_id)
            return

        # Determine editor info
        editor_info = EDITORS.get(session.editor, EDITORS["vscode"])
        wm_class = editor_info.get("wm_class", "")
        embeddable = editor_info.get("embeddable", True)
        launch_token = self._next_launch_token(session_id)

        session.state = STATE_STARTING
        self.sidebar.update_status(session_id, STATE_STARTING)
        self.headerbar.set_session_info(session.name, "Starting…")

        # Make sure the content area shows this session's container
        self.content.show_session(session_id)

        # Check if there is already a window open for this project
        project_basename = os.path.basename(session.project_path.rstrip("/"))
        existing = self.window_discovery.get_visible_main_windows_by_class(wm_class) if wm_class else {}
        if reuse_existing and embeddable:
            for xid, title in existing.items():
                if project_basename.lower() in title.lower():
                    print(f"[App] Found existing {editor_info['name']} window "
                          f"for '{project_basename}': XID {xid}")
                    GLib.idle_add(self._do_embed, session_id, xid, launch_token)
                    return

        before_snapshot = existing
        print(f"[App] Pre-launch snapshot: {len(before_snapshot)} existing windows "
              f"(class={wm_class or 'n/a'})")

        # Launch the editor
        pid = self.process_mgr.launch_editor(
            session_id,
            session.project_path,
            session.editor,
            session.custom_editor_cmd,
            session.vscode_args,
        )

        if pid is None:
            session.state = STATE_FAILED
            self.sidebar.update_status(session_id, STATE_FAILED)
            self.headerbar.set_session_info(session.name, "Failed to start")
            cmd = (session.custom_editor_cmd.split()[0]
                   if session.editor == "custom" and session.custom_editor_cmd
                   else editor_info.get("command", session.editor))
            self._show_error(
                "Launch Failed",
                f"Could not start {editor_info['name']}. "
                f"Make sure '{cmd}' is in your PATH."
            )
            return

        if not embeddable:
            session.pid = pid
            session.state = STATE_EXTERNAL
            self.sidebar.update_status(session_id, STATE_EXTERNAL)
            self.headerbar.set_session_info(session.name, f"{editor_info['name']} window")
            
            # Start background thread just to discover the window for focusing
            def discover_external_xid():
                xid = self.window_discovery.find_new_window(
                    before_snapshot,
                    wm_class=wm_class,
                    project_path=session.project_path,
                    timeout=VSCODE_WINDOW_WAIT_TIMEOUT,
                    allow_title_fallback=True,
                )
                if xid is None:
                    xid = self.window_discovery.find_window_by_pid(
                        pid,
                        wm_class=wm_class,
                        project_path=session.project_path,
                        timeout=5,
                    )
                if xid:
                    session.xid = xid
                    self.process_mgr.set_xid(session_id, xid)
                    print(f"[App] Discovered external window for {session_id}: {xid}")
            
            threading.Thread(target=discover_external_xid, daemon=True).start()
            return

        session.pid = pid
        session.state = STATE_DISCOVERING
        self.sidebar.update_status(session_id, STATE_DISCOVERING)
        self.headerbar.set_session_info(session.name, "Discovering window…")

        # Start window discovery in a background thread
        thread = threading.Thread(
            target=self._discover_and_embed,
            args=(session_id, pid, before_snapshot, session.project_path,
                  wm_class, launch_token, reuse_existing),
            daemon=True,
        )
        thread.start()

    def _discover_and_embed(self, session_id: str, pid: int,
                             before_snapshot: dict, project_path: str,
                             wm_class: str = "code",
                             launch_token: Optional[int] = None,
                             allow_title_fallback: bool = True):
        """Background thread: discover the editor window and embed it."""
        xid = self.window_discovery.find_new_window(
            before_snapshot,
            wm_class=wm_class,
            project_path=project_path,
            timeout=VSCODE_WINDOW_WAIT_TIMEOUT,
            allow_title_fallback=allow_title_fallback,
        )

        if xid is None:
            # Fallback: PID-based discovery
            xid = self.window_discovery.find_window_by_pid(
                pid,
                wm_class=wm_class,
                project_path=project_path,
                timeout=5,
            )

        if xid is None:
            GLib.idle_add(self._on_discovery_failed, session_id, launch_token)
            return

        GLib.idle_add(self._do_embed, session_id, xid, launch_token)

    def _on_discovery_failed(self, session_id: str, launch_token: Optional[int] = None):
        """Called when window discovery times out — fall back to external mode."""
        if not self._is_current_launch_token(session_id, launch_token):
            return

        session = self.registry.get(session_id)
        if not session:
            return

        session.state = STATE_EXTERNAL
        session.xid = None
        self.sidebar.update_status(session_id, STATE_EXTERNAL)
        self.headerbar.set_session_info(session.name, "External window")
        print(f"[App] Window discovery failed for session {session_id}, "
              "using external mode")

    def _do_embed(self, session_id: str, xid: int, launch_token: Optional[int] = None):
        """Attempt to embed the discovered window (runs on main thread)."""
        if not self._is_current_launch_token(session_id, launch_token):
            return

        session = self.registry.get(session_id)
        if not session:
            return

        session.xid = xid
        session.state = STATE_EMBEDDING
        self.sidebar.update_status(session_id, STATE_EMBEDDING)

        title = self.window_discovery.get_window_title(xid)
        print(f"[App] Attempting to embed: XID={xid}, title='{title}'")

        # Register XID with process manager for liveness tracking
        self.process_mgr.set_xid(session_id, xid)

        # Try to get the actual Electron/app PID from the window
        electron_pid = self.window_discovery.get_window_pid(xid)
        if electron_pid:
            self.process_mgr.set_electron_pid(session_id, electron_pid)
            print(f"[App] App PID for session {session_id}: {electron_pid}")

        container = self.embedding_mgr.get_container(session_id)
        if container is None:
            container = self.embedding_mgr.create_container(session_id)
            self.content.add_session_container(session_id, container)

        success = self.embedding_mgr.embed_window(session_id, xid, container)

        if success:
            session.state = STATE_EMBEDDED
            self.sidebar.update_status(session_id, STATE_EMBEDDED)
            self.headerbar.set_session_info(session.name, "Embedded")

            if self._active_session_id == session_id:
                self.content.show_session(session_id)
                self._schedule_embedded_focus(session_id)
        else:
            session.state = STATE_EXTERNAL
            self.sidebar.update_status(session_id, STATE_EXTERNAL)
            self.headerbar.set_session_info(session.name, "External window")
            print(f"[App] Embedding failed for session {session_id}, "
                  "using external mode")

    def _on_stop_session(self, session_id: str = None):
        """Stop the editor and clean up for a session."""
        if session_id is None:
            session_id = self._active_session_id
        if session_id is None:
            return

        session = self.registry.get(session_id)
        if not session:
            return

        self._next_launch_token(session_id)
        self._shutdown_session_runtime(session, kill_editor_if_last_window=True)

    def _on_force_restart_session(self, session_id: str = None):
        """Force-close any matching editor window for a session, then relaunch it."""
        if session_id is None:
            session_id = self._active_session_id
        if session_id is None:
            return

        session = self.registry.get(session_id)
        if not session:
            return

        matching_xids = self._find_matching_editor_windows(session)

        self._next_launch_token(session_id)
        self.process_mgr.terminate(session_id)
        self.process_mgr.terminate_windows(matching_xids)
        self.embedding_mgr.unembed_window(session_id)
        self.process_mgr.forget(session_id)
        self._set_session_closed(session, "Restarting…")

        self.sidebar.select_session(session_id)
        GLib.timeout_add(700, self._restart_session_after_force_close, session_id)

    def _on_session_selected(self, listbox, row):
        """Handle sidebar session selection."""
        if row is None or not isinstance(row, SessionRow):
            return

        session_id = row.session.id
        self._active_session_id = session_id
        session = self.registry.get(session_id)

        if session:
            state_display = {
                STATE_IDLE:       "Idle",
                STATE_STARTING:   "Starting…",
                STATE_DISCOVERING:"Discovering…",
                STATE_EMBEDDING:  "Embedding…",
                STATE_EMBEDDED:   "Embedded",
                STATE_EXTERNAL:   "External",
                STATE_FAILED:     "Failed",
                STATE_CLOSED:     "Stopped",
            }
            self.headerbar.set_session_info(
                session.name,
                state_display.get(session.state, "")
            )

            self.content.show_session(session_id)

            if session.state == STATE_EMBEDDED:
                self._schedule_embedded_focus(session_id)
            elif session.state == STATE_EXTERNAL:
                GLib.timeout_add(80, self._focus_session_window, session_id)

    def _on_kill_editor_processes(self):
        """Prompt for an editor and kill all of its processes."""
        dialog = Gtk.Dialog(
            title="Kill Editor Processes",
            transient_for=self.window,
            modal=True,
            destroy_with_parent=True,
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        kill_btn = dialog.add_button("Kill Processes", Gtk.ResponseType.OK)
        kill_btn.get_style_context().add_class("destructive-action")

        content = dialog.get_content_area()
        content.get_style_context().add_class("dialog-content")
        content.set_spacing(12)

        label = Gtk.Label(
            label="Select an editor. All processes for that editor will be terminated.",
            xalign=0,
        )
        content.pack_start(label, False, False, 0)

        combo = Gtk.ComboBoxText()
        for key, info in EDITORS.items():
            command = info.get("command", "")
            if command:
                combo.append(key, info["name"])
        combo.set_active(0)
        content.pack_start(combo, False, False, 0)

        dialog.show_all()
        response = dialog.run()
        editor_key = combo.get_active_id()
        dialog.destroy()

        if response != Gtk.ResponseType.OK or not editor_key:
            return

        editor_info = EDITORS.get(editor_key, {})
        command = editor_info.get("command", "")

        self.process_mgr.terminate_editor_processes(command)

        for session in self.registry.get_all():
            if session.editor != editor_key:
                continue
            self._next_launch_token(session.id)
            self.embedding_mgr.unembed_window(session.id)
            self.process_mgr.forget(session.id)
            self._set_session_closed(session, f"{editor_info.get('name', editor_key)} killed")

    # =========================================
    # Group actions
    # =========================================

    def _on_new_group(self):
        """Show the new group dialog."""
        dialog = GroupDialog(self.window)
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            valid, error = dialog.validate()
            if valid:
                group = dialog.get_group()
                group.order = self.group_registry.count()
                self.group_registry.add(group)
                self.sidebar.add_group(group, 0)
            else:
                self._show_error("Validation Error", error)

        dialog.destroy()

    def _on_edit_group(self, group_id: str):
        """Show the edit group dialog."""
        group = self.group_registry.get(group_id)
        if not group:
            return

        dialog = GroupDialog(self.window, group=group)
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            valid, error = dialog.validate()
            if valid:
                updated = dialog.get_group()
                self.group_registry.update(updated)
                count = len(self.registry.get_by_group(group_id))
                self.sidebar.update_group(updated, count)
            else:
                self._show_error("Validation Error", error)

        dialog.destroy()

    def _on_remove_group(self, group_id: str):
        """Remove a group after confirmation; its sessions become ungrouped."""
        group = self.group_registry.get(group_id)
        if not group:
            return

        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"Remove group '{group.name}'?",
        )
        dialog.format_secondary_text(
            "Sessions in this group will be moved to the top level."
        )

        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES:
            # Ungroup sessions
            for s in self.registry.get_by_group(group_id):
                s.group_id = None
            self.registry.save()

            self.group_registry.remove(group_id)

            # Full rebuild to reflect new layout
            self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())

    def _on_reorder(self, order_updates: list):
        """Persist order changes emitted by the sidebar after a DnD drop."""
        for row_type, item_id, new_order in order_updates:
            if row_type == "session":
                s = self.registry.get(item_id)
                if s:
                    s.order = new_order
            elif row_type == "group":
                g = self.group_registry.get(item_id)
                if g:
                    g.order = new_order
        self.registry.save()
        self.group_registry.save()

    def _on_group_toggle(self, group_id: str, collapsed: bool):
        """Persist a group's collapsed/expanded state."""
        g = self.group_registry.get(group_id)
        if g:
            g.collapsed = collapsed
            self.group_registry.update(g)

    def _move_session_to_group(self, session_id: str, group_id: Optional[str]):
        """Move a session between groups or back to the top level."""
        session = self.registry.get(session_id)
        if not session or session.group_id == group_id:
            return

        if group_id is None:
            top_level_orders = [
                item.order
                for item in self.group_registry.get_all()
            ] + [
                item.order
                for item in self.registry.get_by_group(None)
            ]
            new_order = (max(top_level_orders) + 1) if top_level_orders else 0
        else:
            new_order = len(self.registry.get_by_group(group_id))

        session.group_id = group_id
        session.order = new_order

        self.registry.save()
        self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())
        self.sidebar.select_session(session_id)

    # =========================================
    # Right-click context menu
    # =========================================

    def _on_sidebar_button_press(self, widget, event):
        """Handle right-click on sidebar rows."""
        if event.button != 3:
            return False

        row = widget.get_row_at_y(int(event.y))
        if row is None:
            return False

        # ── Group row context menu ─────────────────────────────────────
        if isinstance(row, GroupRow):
            group_id = row.group.id
            group = self.group_registry.get(group_id)
            if not group:
                return False

            widget.select_row(row)
            menu = Gtk.Menu()

            edit_item = Gtk.MenuItem(label="✎  Edit Group")
            edit_item.connect("activate", lambda w: self._on_edit_group(group_id))
            menu.append(edit_item)

            remove_item = Gtk.MenuItem(label="✖  Remove Group")
            remove_item.connect("activate", lambda w: self._on_remove_group(group_id))
            menu.append(remove_item)

            menu.show_all()
            menu.popup_at_pointer(event)
            return True

        # ── Session row context menu ───────────────────────────────────
        if not isinstance(row, SessionRow):
            return False

        session_id = row.session.id
        session = self.registry.get(session_id)
        if not session:
            return False

        widget.select_row(row)
        menu = Gtk.Menu()

        if session.state in (STATE_IDLE, STATE_CLOSED, STATE_FAILED):
            start_item = Gtk.MenuItem(label="▶  Start && Embed")
            start_item.connect("activate", lambda w: self._on_start_session(session_id))
            menu.append(start_item)
        elif session.state in (STATE_EMBEDDED, STATE_EXTERNAL):
            focus_item = Gtk.MenuItem(label="◎  Focus Window")
            focus_item.connect("activate", lambda w: self._focus_session_window(session_id))
            menu.append(focus_item)

            stop_item = Gtk.MenuItem(label="■  Stop Session")
            stop_item.connect("activate", lambda w: self._on_stop_session(session_id))
            menu.append(stop_item)

        restart_item = Gtk.MenuItem(label="↻  Force Restart")
        restart_item.connect("activate", lambda w: self._on_force_restart_session(session_id))
        menu.append(restart_item)

        menu.append(Gtk.SeparatorMenuItem())

        edit_item = Gtk.MenuItem(label="✎  Edit Session")
        edit_item.connect("activate", lambda w: self._on_edit_session(session_id))
        menu.append(edit_item)

        move_menu = Gtk.Menu()

        top_level_item = Gtk.MenuItem(label="Top Level")
        top_level_item.connect("activate", lambda w: self._move_session_to_group(session_id, None))
        move_menu.append(top_level_item)

        for group in self.group_registry.get_all():
            item = Gtk.MenuItem(label=group.name)
            item.connect("activate", lambda w, gid=group.id: self._move_session_to_group(session_id, gid))
            move_menu.append(item)

        move_item = Gtk.MenuItem(label="↗  Move to Group")
        move_item.set_submenu(move_menu)
        menu.append(move_item)

        remove_item = Gtk.MenuItem(label="✖  Remove Session")
        remove_item.connect("activate", lambda w: self._on_remove_session(session_id))
        menu.append(remove_item)

        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    # =========================================
    # Window events
    # =========================================

    def _on_configure(self, window, event):
        """Save window geometry on resize/move."""
        if not window.is_maximized():
            self.settings["window_width"] = event.width
            self.settings["window_height"] = event.height
            self.settings["window_x"] = event.x
            self.settings["window_y"] = event.y
        self.settings["window_maximized"] = window.is_maximized()
        # Only save sidebar width when the sidebar is actually visible
        if self._sidebar_visible:
            self.settings["sidebar_width"] = self.paned.get_position()

    def _on_delete(self, window, event):
        """Handle window close."""
        self._save_and_cleanup()
        return False

    def _on_quit(self):
        """Quit the application."""
        self._save_and_cleanup()
        self.quit()

    def _save_and_cleanup(self):
        """Save settings and clean up resources."""
        save_settings(self.settings)

        if self._health_check_id:
            GLib.source_remove(self._health_check_id)

        # VS Code / editors survive the app — don't terminate them
        self.embedding_mgr.cleanup()
        self.window_discovery.close()

    def _on_about(self):
        """Show about dialog."""
        about = Gtk.AboutDialog(
            transient_for=self.window,
            modal=True,
        )
        about.set_program_name("Coder3")
        about.set_version(__version__)
        about.set_comments(
            "A desktop app that embeds editor windows inside\n"
            "a unified session manager using X11 reparenting."
        )
        about.set_license_type(Gtk.License.MIT_X11)
        about.set_website("https://github.com/coder3")
        about.run()
        about.destroy()

    def _show_error(self, title: str, message: str):
        """Show an error dialog."""
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()


def main():
    """Entry point for the application."""
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = Coder3App()
    exit_status = app.run(sys.argv)
    sys.exit(exit_status)
