"""CodeHub — Main GTK Application.

A desktop application that embeds editor windows inside a host application
using X11 native window reparenting on Linux.
"""

import os
import sys
import signal
import threading
import time
from typing import Optional

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Gio

from codehub import __version__, __app_id__
from codehub.account_manager import AccountManager, Account
from codehub.session_registry import Session, SessionRegistry
from codehub.group_registry import Group, GroupRegistry
from codehub.template_registry import TemplateRegistry, SessionTemplate
from codehub.process_manager import ProcessManager
from codehub.window_discovery import WindowDiscovery
from codehub.embedding_manager import EmbeddingManager
from codehub.app_manager import AppManager
from codehub.session_app import SessionApp
from codehub.ui.header_bar import HeaderBar
from codehub.ui.sidebar import Sidebar, SessionRow, GroupRow
from codehub.ui.content_area import ContentArea
from codehub.ui.session_workspace import SessionWorkspace
from codehub.ui.session_dialog import SessionDialog, GroupDialog
from codehub.ui.app_dialog import AddAppDialog, RenameAppDialog
from codehub.ui.account_dialog import (
    AccountChooserDialog,
    AccountDeleteDialog,
    AccountFormDialog,
    RESPONSE_CREATE,
    RESPONSE_DELETE,
    RESPONSE_EDIT,
)
from codehub.ui.notes_dialog import NotesDialog
from codehub.ui.ideas_dialog import IdeasDialog
from codehub.ui.tasks_dialog import TasksDialog
from codehub.ui.modes_dialog import ModesDialog
from codehub.ui.toast import ToastManager
from codehub.app_notes import AppNotesRegistry
from codehub.session_history import SessionHistoryRegistry
from codehub.mode_manager import ModeManager

from codehub.utils.config import load_settings, save_settings
from codehub.utils.constants import (
    APP_NAME, APP_ID,
    MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT,
    STATE_IDLE, STATE_STARTING, STATE_DISCOVERING,
    STATE_EMBEDDING, STATE_EMBEDDED, STATE_EXTERNAL, STATE_FAILED, STATE_CLOSED,
    VSCODE_POLL_INTERVAL, VSCODE_WINDOW_WAIT_TIMEOUT,
    EDITORS, APPS, get_app_info,
)


class CodeHubApp(Gtk.Application):
    """Main application class."""

    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.NON_UNIQUE
        )

        self.window = None
        self.account_mgr = AccountManager()
        self.active_account: Optional[Account] = None
        self.active_config_dir: Optional[str] = None
        self.registry = None
        self.group_registry = None
        self.template_registry = None
        self.process_mgr = ProcessManager()
        self.window_discovery = WindowDiscovery()
        self.embedding_mgr = EmbeddingManager()
        self.app_mgr = AppManager(self.embedding_mgr, self.window_discovery)
        self.settings = None
        self.app_notes = None
        self.session_history = None
        self.mode_mgr = None

        self._active_session_id = None
        self._health_check_id = None
        self._sidebar_visible = True
        self._launch_tokens: dict[str, int] = {}
        # Saved width used when restoring sidebar after toggle-off
        self._saved_sidebar_width = 280
        # Tracks open NotesDialogs per session so we don't open duplicates
        self._notes_dialogs: dict[str, NotesDialog] = {}
        self._plans_dialogs: dict[str, NotesDialog] = {}
        self._tasks_dialogs: dict[str, TasksDialog] = {}
        # General-notes dialog (app-level, not per-session)
        self._general_notes_dialog: Optional[NotesDialog] = None
        self._general_plans_dialog: Optional[NotesDialog] = None
        self._general_ideas_dialog: Optional[IdeasDialog] = None
        # Session workspaces — session_id → SessionWorkspace
        self._workspaces: dict[str, SessionWorkspace] = {}
        # Toast notification manager (initialised after content area is created)
        self._toast: Optional[ToastManager] = None
        # Track which session is *visually selected* for active-time tracking
        self._active_session_timer_id: Optional[int] = None
        # Track if the goal alert has been shown for a session
        self._goal_alerted: set[str] = set()
        # Show hidden sessions toggle
        self._show_hidden = False

        # ── General (global) timer state ──────────────────────────────
        self._global_paused: bool = False
        self._global_start_time: float = 0.0
        self._global_goal_alerted: bool = False
        self._global_timer_id: Optional[int] = None
        # Periodic tick for UI updates and goal checks
        self._timer_tick_id: Optional[int] = None
        self._timer_tick_count: int = 0

        # ── Idle / auto-away detection ────────────────────────────────
        self._last_activity_time: float = time.time()
        self._idle_check_id: Optional[int] = None
        self._idle_dialog_active: bool = False
        self._last_idle_alert_time: float = 0.0


    def do_activate(self):
        """Called when the application is activated."""
        if self.window:
            self.window.present()
            return

        self._load_css()
        if not self._select_account_for_startup():
            self.quit()
            return

        self._create_window()
        self._populate_sessions()
        self._setup_keybindings()
        self._start_health_check()

        # Wire app manager callbacks
        self.app_mgr.on_app_state_changed = self._on_app_state_changed

        # Wire header bar backup callbacks
        self.headerbar.on_export_backup = self._on_export_backup
        self.headerbar.on_import_backup = self._on_import_backup

        # Initialise toast manager (overlay lives inside content area)
        self._toast = ToastManager(self.content.overlay)

        # Wire Pomodoro callbacks
        self.headerbar.pomodoro.update_settings(self.settings)
        self.headerbar.pomodoro._on_phase_complete = self._on_pomodoro_phase_complete
        self.headerbar.pomodoro.on_state_changed = self._on_pomodoro_state_changed

        # Wire header bar history / pomodoro settings callbacks
        self.headerbar.on_history = self._on_show_history
        self.headerbar.on_pomodoro_settings = self._on_pomodoro_settings
        self.headerbar.on_general_timer_pause = self._on_global_pause_toggle
        self.headerbar.on_general_timer_reset = self._on_global_reset_timer
        self.headerbar.on_general_goal_settings = self._on_general_goal_settings
        self.headerbar.on_reset_all_session_timers = self._on_reset_all_session_timers
        self.headerbar.on_modes_settings = self._on_modes_settings
        self.headerbar.on_switch_account = self._on_switch_account
        self.headerbar.on_edit_account = self._on_edit_active_account
        self.headerbar.on_logout = self._on_logout
        if self.active_account:
            self.headerbar.set_account_name(self.active_account.name)

        # Wire ModeManager callback
        self.mode_mgr.on_state_changed = self._on_mode_state_changed

        # Start periodic timer tick
        self._timer_tick_id = GLib.timeout_add_seconds(1, self._tick_timers)

        # Start idle / auto-away detection
        self._setup_activity_tracking()
        self._idle_check_id = GLib.timeout_add_seconds(10, self._check_idle)

        self.window.show_all()

        # Check for orphaned processes from a previous crash
        self._check_for_orphaned_processes()

        # Restore previously active sessions and auto-start sessions
        last_active = self.settings.get("last_active_sessions", [])
        for session in self.registry.get_all():
            if session.id in last_active or session.auto_start:
                # Add a small delay between startups
                GLib.timeout_add(100, self._on_start_session, session.id)

        # Initial UI mode update
        self._on_mode_state_changed()

    def _initialize_account(self, account: Account):
        """Load all account-owned state into fresh registries."""
        self.active_account = account
        self.active_config_dir = self.account_mgr.get_account_config_dir(account.id)
        self.registry = SessionRegistry(self.active_config_dir)
        self.group_registry = GroupRegistry(self.active_config_dir)
        self.template_registry = TemplateRegistry(self.active_config_dir)
        self.settings = load_settings(self.active_config_dir)
        self.app_notes = AppNotesRegistry(self.active_config_dir)
        self.session_history = SessionHistoryRegistry(self.active_config_dir)
        self.mode_mgr = ModeManager(self.active_config_dir)
        self.account_mgr.set_last_active_account_id(account.id)

    def _select_account_for_startup(self) -> bool:
        """Ask the user to create or select an account before loading app data."""
        accounts = self.account_mgr.get_accounts()
        if not accounts:
            return self._create_first_account()

        while True:
            dialog = AccountChooserDialog(
                None,
                self.account_mgr.get_accounts(),
                self.account_mgr.get_last_active_account_id(),
            )
            response = dialog.run()

            if response == RESPONSE_CREATE:
                dialog.destroy()
                self._create_account_dialog()
                continue

            selected_id = dialog.get_selected_account_id()

            if response == RESPONSE_EDIT:
                password = dialog.get_password()
                dialog.destroy()
                if selected_id and self.account_mgr.verify_password(selected_id, password):
                    self._edit_account_dialog(selected_id, parent=None)
                else:
                    self._show_message(None, "Password is incorrect.", Gtk.MessageType.ERROR)
                continue

            if response == RESPONSE_DELETE:
                dialog.destroy()
                if selected_id:
                    self._delete_account_dialog(selected_id, parent=None)
                continue

            if response != Gtk.ResponseType.OK:
                dialog.destroy()
                return False

            password = dialog.get_password()
            if selected_id and self.account_mgr.verify_password(selected_id, password):
                account = self.account_mgr.get(selected_id)
                dialog.destroy()
                if account:
                    self._initialize_account(account)
                    return True
            else:
                dialog.destroy()
                self._show_message(None, "Password is incorrect.", Gtk.MessageType.ERROR)

    def _create_first_account(self) -> bool:
        """Create the first account and migrate existing shared data if present."""
        while True:
            dialog = AccountFormDialog(None, title="Create First Account", require_password=True)
            response = dialog.run()
            if response != Gtk.ResponseType.OK:
                dialog.destroy()
                return False
            try:
                name, password = dialog.get_values()
                account = self.account_mgr.create_account(name, password or "")
                backup_dir = self.account_mgr.migrate_legacy_data(account.id)
                dialog.destroy()
                self._initialize_account(account)
                if backup_dir:
                    print(f"[Account] Legacy data copied to account and backed up at {backup_dir}")
                return True
            except ValueError as e:
                dialog.set_error(str(e))

    def _create_account_dialog(self, parent=None) -> Optional[Account]:
        while True:
            dialog = AccountFormDialog(parent, title="Create Account", require_password=True)
            response = dialog.run()
            if response != Gtk.ResponseType.OK:
                dialog.destroy()
                return None
            try:
                name, password = dialog.get_values()
                account = self.account_mgr.create_account(name, password or "")
                dialog.destroy()
                return account
            except ValueError as e:
                dialog.set_error(str(e))

    def _edit_account_dialog(self, account_id: str, parent=None) -> Optional[Account]:
        account = self.account_mgr.get(account_id)
        if not account:
            return None
        while True:
            dialog = AccountFormDialog(
                parent, title="Edit Account", account=account, require_password=False
            )
            response = dialog.run()
            if response != Gtk.ResponseType.OK:
                dialog.destroy()
                return None
            try:
                name, password = dialog.get_values()
                updated = self.account_mgr.update_account(account_id, name=name, password=password)
                dialog.destroy()
                return updated
            except ValueError as e:
                dialog.set_error(str(e))

    def _delete_account_dialog(self, account_id: str, parent=None) -> bool:
        account = self.account_mgr.get(account_id)
        if not account:
            return False
        while True:
            dialog = AccountDeleteDialog(parent, account.name)
            response = dialog.run()
            if response != Gtk.ResponseType.OK:
                dialog.destroy()
                return False
            try:
                self.account_mgr.delete_account(account_id, dialog.get_password())
                dialog.destroy()
                return True
            except ValueError as e:
                dialog.set_error(str(e))

    def _show_message(self, parent, text: str, message_type=Gtk.MessageType.INFO):
        dialog = Gtk.MessageDialog(
            transient_for=parent,
            modal=True,
            message_type=message_type,
            buttons=Gtk.ButtonsType.OK,
            text=text,
        )
        dialog.run()
        dialog.destroy()

    def _save_settings(self):
        if self.settings is not None and self.active_config_dir:
            save_settings(self.settings, self.active_config_dir)

    def _check_for_orphaned_processes(self):
        """Check for orphaned processes from previous runs and prompt to kill them."""
        import psutil
        orphaned_pids = []
        for session in self.registry.get_all():
            for pid in session.spawned_pids:
                if psutil.pid_exists(pid):
                    orphaned_pids.append(pid)
            
            for app_dict in session.apps:
                for pid in app_dict.get("spawned_pids", []):
                    if psutil.pid_exists(pid):
                        orphaned_pids.append(pid)

        if orphaned_pids:
            count = len(orphaned_pids)
            dialog = Gtk.MessageDialog(
                transient_for=self.window,
                flags=0,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.YES_NO,
                text="Orphaned Processes Detected",
            )
            dialog.format_secondary_text(
                f"{count} orphaned process(es) from the last run were found. "
                "Kill them now?"
            )
            dialog.get_widget_for_response(Gtk.ResponseType.YES).set_label("Kill All")
            dialog.get_widget_for_response(Gtk.ResponseType.NO).set_label("Ignore")
            response = dialog.run()
            dialog.destroy()
            
            if response == Gtk.ResponseType.YES:
                for pid in orphaned_pids:
                    self.process_mgr.terminate_pid_tree(pid)
            
            # Clean up the references regardless of choice
            for session in self.registry.get_all():
                session.spawned_pids.clear()
                for app_dict in session.apps:
                    if "spawned_pids" in app_dict:
                        app_dict["spawned_pids"].clear()
                self.registry.update(session)

    def _load_css(self):
        """Load the GTK CSS stylesheet with high priority."""
        css_provider = Gtk.CssProvider()
        css_path = os.path.join(os.path.dirname(__file__), "ui", "styles.css")
        
        if not os.path.exists(css_path):
            print(f"[App] ✗ CSS file not found at {css_path}")
            return

        try:
            with open(css_path, "r") as f:
                css_data = f.read()
            
            # Use load_from_data to potentially get better error info if it fails
            css_provider.load_from_data(css_data.encode("utf-8"))
            
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_USER
            )
            print(f"[App] ✓ CSS loaded successfully from {css_path} (Priority: USER)")
        except Exception as e:
            print(f"[App] ✗ Failed to load CSS: {e}")
            # Fallback to a very basic rule if the file is broken
            try:
                css_provider.load_from_data(b"window { background-color: #0d0f17; color: #c0caf5; }")
                Gtk.StyleContext.add_provider_for_screen(
                    Gdk.Screen.get_default(),
                    css_provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
            except:
                pass

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
        self.headerbar.on_general_notes = self._on_open_general_notes
        self.headerbar.on_general_plans = self._on_open_general_plans
        self.headerbar.on_general_ideas = self._on_open_general_ideas
        self.headerbar.on_scan_projects = self._on_scan_projects
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
        self.sidebar.on_open_notes = self._on_open_notes
        self.sidebar.on_open_plans = self._on_open_plans
        self.sidebar.on_open_tasks = self._on_open_tasks
        self.sidebar.on_show_details = self._on_show_session_details
        self.sidebar.show_hidden_btn.connect("toggled", lambda btn: self._on_toggle_show_hidden())

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

    def _on_modes_settings(self):
        """Open the Modes configuration dialog."""
        dialog = ModesDialog(self.window, self.mode_mgr, self.registry.get_all())
        if dialog.run() == Gtk.ResponseType.OK:
            dialog.save_settings()
        dialog.destroy()

    def _on_mode_state_changed(self):
        """Called when ModeManager changes which sessions are active/allowed."""
        # We need to update sidebar UI and workspace UI.
        enabled_sessions = []
        for session in self.registry.get_all():
            allowed = self.mode_mgr.is_session_allowed(session.id)
            if allowed:
                enabled_sessions.append(session.id)
            # Update sidebar
            self.sidebar.set_session_enabled(session.id, allowed)
            # Update workspace
            workspace = self._workspaces.get(session.id)
            if workspace:
                workspace.set_enabled(allowed)

        # Update currently active workspace lock overlay and auto-switch if needed
        if self._active_session_id:
            allowed = self.mode_mgr.is_session_allowed(self._active_session_id)
            if not allowed and enabled_sessions:
                # The current session was disabled, and there are other enabled sessions.
                # Auto-switch to the first allowed session to keep the flow seamless.
                self.sidebar.select_session(enabled_sessions[0])

        # Update HeaderBar button
        mode_labels = {
            "normal": "Normal",
            "focus": "Focus",
            "managed": "Managed",
            "focus_managed": "Focus+Managed"
        }
        name = mode_labels.get(self.mode_mgr.current_mode, "Unknown")
        
        # Check if period changed automatically
        prev_period = getattr(self, "_prev_focus_period_id", None)
        curr_period = self.mode_mgr.active_focus_period_id
        if prev_period != curr_period:
            if curr_period and self._toast:
                self._toast.show("Scheduled Focus Period Started!", kind="success")
            elif prev_period and not curr_period and self._toast:
                self._toast.show("Scheduled Focus Period Ended.", kind="info")
            self._prev_focus_period_id = curr_period

        if curr_period:
            self.headerbar.modes_btn.set_label(f"⚙️ {name} (Auto)")
        else:
            self.headerbar.modes_btn.set_label(f"⚙️ Mode: {name}")

    def _populate_sessions(self):
        """Load sessions and groups from registries into the sidebar."""
        sessions = self.registry.get_all()
        groups = self.group_registry.get_all()

        # Filter hidden sessions unless show_hidden is on
        visible_sessions = sessions
        if not self._show_hidden:
            visible_sessions = [s for s in sessions if not s.hidden]

        # Rebuild the sidebar (callbacks already wired on self.sidebar)
        self.sidebar.rebuild(visible_sessions, groups)

        # Create session workspaces for ALL sessions (including hidden)
        for session in sessions:
            if session.id not in self._workspaces:
                self._create_session_workspace(session)

    def _on_switch_session(self, index: int):
        """Switch to the Nth session in the sidebar."""
        from codehub.ui.sidebar import SessionRow
        rows = self.sidebar.listbox.get_children()
        session_rows = [r for r in rows if isinstance(r, SessionRow) and r.get_child_visible()]
        if 0 <= index < len(session_rows):
            self.sidebar.select_session(session_rows[index].session.id)

    def _on_next_session(self, direction: int):
        """Switch to next (+1) or prev (-1) session."""
        from codehub.ui.sidebar import SessionRow
        rows = self.sidebar.listbox.get_children()
        session_rows = [r for r in rows if isinstance(r, SessionRow) and r.get_child_visible()]
        if not session_rows:
            return
        current_idx = -1
        for i, row in enumerate(session_rows):
            if row.session.id == self._active_session_id:
                current_idx = i
                break
        next_idx = 0 if current_idx == -1 else (current_idx + direction) % len(session_rows)
        self.sidebar.select_session(session_rows[next_idx].session.id)

    def _on_switch_app_tab(self, index: int):
        """Switch to the Nth app tab in the active session."""
        if not self._active_session_id:
            return
        workspace = self._workspaces.get(self._active_session_id)
        if not workspace:
            return
        app_ids = workspace.get_app_ids()
        if 0 <= index < len(app_ids):
            workspace.select_app(app_ids[index])

    def _on_close_active_app_tab(self):
        """Close the currently active app tab in the active session."""
        if not self._active_session_id:
            return
        workspace = self._workspaces.get(self._active_session_id)
        if not workspace:
            return
        app_id = workspace.get_active_app_id()
        if app_id and app_id != "editor":
            self._on_close_app(self._active_session_id, app_id)

    def _setup_keybindings(self):
        """Set up keyboard shortcuts."""
        accel_group = Gtk.AccelGroup()
        self.window.add_accel_group(accel_group)

        # Ctrl+N — New session
        key, mod = Gtk.accelerator_parse("<Control>n")
        accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                           lambda *a: self._on_new_session())

        # Ctrl+W — Close active app tab
        key, mod = Gtk.accelerator_parse("<Control>w")
        accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                           lambda *a: self._on_close_active_app_tab())

        # Ctrl+Shift+X — Close/stop active session
        key, mod = Gtk.accelerator_parse("<Control><Shift>x")
        accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                           lambda *a: self._on_stop_session())

        # Ctrl+Q — Quit
        key, mod = Gtk.accelerator_parse("<Control>q")
        accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                           lambda *a: self._on_quit())

        # Ctrl+Return / Ctrl+Shift+S — Start active session
        key, mod = Gtk.accelerator_parse("<Control>Return")
        accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                           lambda *a: self._on_start_session())
        key, mod = Gtk.accelerator_parse("<Control><Shift>s")
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

        # Ctrl+P — Command Palette
        key, mod = Gtk.accelerator_parse("<Control>p")
        accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                           lambda *a: self._on_command_palette())

        # Ctrl+Shift+N — General Notes
        key, mod = Gtk.accelerator_parse("<Control><Shift>n")
        accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                           lambda *a: self._on_open_general_notes())

        # Ctrl+1..9 — Switch to session 1..9
        for i in range(1, 10):
            key, mod = Gtk.accelerator_parse(f"<Control>{i}")
            accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                               lambda *a, idx=i-1: self._on_switch_session(idx))

        # Alt+1..9 — Switch to app tab 1..9
        for i in range(1, 10):
            key, mod = Gtk.accelerator_parse(f"<Alt>{i}")
            accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                               lambda *a, idx=i-1: self._on_switch_app_tab(idx))

        # Ctrl+Tab — Next session
        key, mod = Gtk.accelerator_parse("<Control>Tab")
        accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                           lambda *a: self._on_next_session(1))

        # Ctrl+Shift+Tab — Previous session
        key, mod = Gtk.accelerator_parse("<Control><Shift>ISO_Left_Tab")
        if key == 0:  # Fallback
            key, mod = Gtk.accelerator_parse("<Control><Shift>Tab")
        accel_group.connect(key, mod, Gtk.AccelFlags.VISIBLE,
                           lambda *a: self._on_next_session(-1))

    def _on_command_palette(self):
        """Open the Command Palette."""
        from codehub.ui.command_palette import CommandPalette
        palette = CommandPalette(self)
        palette.show_all()
        return True

    def _start_health_check(self):
        """Periodically check for dead editor windows.

        Uses XID-based window liveness checks instead of PID polling,
        because the `code` CLI wrapper exits immediately.

        The actual xwininfo subprocess calls run in a background thread so the
        GTK main loop is never blocked while waiting for them to complete.  A
        simple flag prevents a new check from starting before the previous one
        has finished (avoids piling up threads under load).
        """
        _checking = [False]

        def check():
            if _checking[0]:
                # Previous check still running — skip this tick
                return True
            _checking[0] = True

            def run_in_thread():
                try:
                    dead = self.process_mgr.check_dead_sessions()
                except Exception as e:
                    print(f"[App] Health check error: {e}")
                    dead = []

                # Also check workspace apps
                try:
                    dead_apps = self.app_mgr.check_dead_apps()
                except Exception as e:
                    print(f"[App] App health check error: {e}")
                    dead_apps = []

                _checking[0] = False

                if dead or dead_apps:
                    GLib.idle_add(apply_on_main, dead, dead_apps)

            def apply_on_main(dead, dead_apps=None):
                for session_id in dead:
                    try:
                        self._mark_session_dead(session_id)
                    except Exception as e:
                        print(f"[App] Error applying dead session {session_id}: {e}")
                for session_id, app_id in (dead_apps or []):
                    try:
                        self.app_mgr.mark_app_dead(session_id, app_id)
                        workspace = self._workspaces.get(session_id)
                        if workspace:
                            workspace.update_app_status(app_id, STATE_CLOSED)
                    except Exception as e:
                        print(f"[App] Error applying dead app {app_id}: {e}")

            threading.Thread(target=run_in_thread, daemon=True).start()
            return True  # Keep timer running

        self._health_check_id = GLib.timeout_add_seconds(5, check)

    def _mark_session_dead(self, session_id: str):
        """Mark a session as closed when its window has died.

        Safe to call from the GTK main thread only.
        """
        session = self.registry.get(session_id)
        if session and session.state not in (STATE_IDLE, STATE_CLOSED):
            print(f"[App] Session {session_id} window died, marking as closed")
            session.state = STATE_CLOSED
            session.pid = None
            session.xid = None
            self._update_session_state(session_id, STATE_CLOSED)
            self.embedding_mgr.unembed_window(session_id)
            self._on_timer_conditions_changed()
            if self._toast:
                self._toast.show(
                    f"'{session.name}' window closed unexpectedly",
                    kind="crash"
                )


    def _on_session_window_died(self, session_id: str):
        """Immediate notification from EmbeddingManager when a session's embedded
        window exits (via the GTK Socket plug-removed signal).

        This fires much faster than waiting for the 5-second health check.
        Runs on the GTK main thread (called via GLib.idle_add).
        """
        try:
            print(f"[App] Session {session_id}: embedded window exited (plug-removed)")
            self._mark_session_dead(session_id)
        except Exception as e:
            print(f"[App] _on_session_window_died error for {session_id}: {e}")

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
    # Session workspace management
    # =========================================

    def _create_session_workspace(self, session: Session):
        """Create a SessionWorkspace for a session and register it."""
        workspace = SessionWorkspace(session.id, editor_name=session.editor)

        # Create the editor embed container inside the workspace
        editor_container = workspace.get_container("editor")
        editor_slot_key = session.id  # backward compat: editor uses plain session_id
        self.embedding_mgr._containers[editor_slot_key] = editor_container

        # Wire workspace callbacks
        workspace.on_add_app = self._on_add_app
        workspace.on_close_app = self._on_close_app
        workspace.on_app_selected = self._on_workspace_app_selected
        workspace.on_start_app = self._on_start_workspace_app
        workspace.on_stop_app = self._on_stop_workspace_app
        workspace.on_open_terminal = self._on_open_terminal
        workspace.on_kill_app = self._on_kill_workspace_app
        workspace.on_restart_app = self._on_restart_workspace_app
        workspace.on_detach_app = self._on_detach_workspace_app
        workspace.on_duplicate_app = self._on_duplicate_workspace_app
        workspace.on_open_notes = self._on_open_notes
        workspace.on_open_plans = self._on_open_plans
        workspace.on_open_tasks = self._on_open_tasks
        workspace.on_reorder_apps = self._on_reorder_workspace_apps
        workspace.on_recover_app = self._on_recover_workspace_app
        workspace.on_rename_app = self._on_rename_workspace_app


        # Restore persisted apps
        for app_dict in session.apps:
            app = SessionApp.from_dict(app_dict)
            app.session_id = session.id
            self.app_mgr.register_app(app)

            app_info = APPS.get(app.app_type, APPS.get("custom", {}))
            container = workspace.add_app_tab(
                app.id, app.display_name,
                icon=app.icon or app_info.get("icon", "🔧"),
            )
            # Register the container with the embedding manager
            self.embedding_mgr._containers[app.slot_key] = container

        self._workspaces[session.id] = workspace
        self.content.add_session_container(session.id, workspace)

    def _on_reorder_workspace_apps(self, session_id: str, app_ids: list[str]):
        """Persist the new app order for a session."""
        session = self.registry.get(session_id)
        if not session:
            return

        # Build a new apps list in the specified order
        id_to_app = {app["id"]: app for app in session.apps}
        new_apps = []
        for aid in app_ids:
            if aid in id_to_app:
                new_apps.append(id_to_app[aid])

        # Add any apps that might have been missing from the IDs list (safety)
        missing_ids = set(id_to_app.keys()) - set(app_ids)
        for mid in missing_ids:
            new_apps.append(id_to_app[mid])

        session.apps = new_apps
        self.registry.update(session)
        print(f"[App] Reordered apps for session {session_id}")

    def _on_rename_workspace_app(self, session_id: str, app_id: str):
        """Rename a non-editor app tab and persist the display name."""
        session = self.registry.get(session_id)
        if not session:
            return

        target = None
        for app_dict in session.apps:
            if app_dict.get("id") == app_id:
                target = app_dict
                break

        if not target:
            return

        while True:
            dialog = RenameAppDialog(self.window, target.get("display_name", "App"))
            response = dialog.run()
            if response != Gtk.ResponseType.OK:
                dialog.destroy()
                return
            try:
                new_name = dialog.get_name()
                dialog.destroy()
                break
            except ValueError as e:
                dialog.set_error(str(e))

        target["display_name"] = new_name
        self.registry.update(session)

        app_obj = self.app_mgr.get_app(f"{session_id}:{app_id}")
        if app_obj:
            app_obj.display_name = new_name

        workspace = self._workspaces.get(session_id)
        if workspace:
            workspace.rename_app_tab(app_id, new_name)

        self._populate_sessions()
        if self._toast:
            self._toast.show("App renamed", kind="success")

    def _on_add_app(self, session_id: str):
        """Handle '+ App' button in a session workspace."""
        session = self.registry.get(session_id)
        if not session:
            return

        dialog = AddAppDialog(self.window, session_id)
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            valid, error = dialog.validate()
            if valid:
                app = dialog.get_session_app()
                self.app_mgr.register_app(app)

                # Add tab to workspace
                workspace = self._workspaces.get(session_id)
                if workspace:
                    app_info = get_app_info(app.app_type)
                    container = workspace.add_app_tab(
                        app.id, app.display_name,
                        icon=app.icon or app_info.get("icon", "🔧"),
                    )
                    self.embedding_mgr._containers[app.slot_key] = container
                    workspace.select_app(app.id)

                # Persist to session
                session.apps.append(app.to_dict())
                self.registry.update(session)

                # Auto-launch
                self.app_mgr.launch_app(app, project_path=session.project_path, env_vars=session.env_vars)
            else:
                self._show_error("Validation Error", error)

        dialog.destroy()

    def _on_close_app(self, session_id: str, app_id: str):
        """Handle closing/removing an app from a session workspace."""
        if app_id.startswith("term-"):
            workspace = self._workspaces.get(session_id)
            if workspace:
                workspace.remove_app_tab(app_id)
            return

        slot_key = f"{session_id}:{app_id}"
        app = self.app_mgr.get_app(slot_key)
        if app:
            self.app_mgr.remove_app(app)

        # Remove from workspace UI
        workspace = self._workspaces.get(session_id)
        if workspace:
            workspace.remove_app_tab(app_id)

        # Remove from persisted session
        session = self.registry.get(session_id)
        if session:
            session.apps = [a for a in session.apps if a.get("id") != app_id]
            self.registry.update(session)

    def _on_start_workspace_app(self, session_id: str, app_id: str):
        """Start a workspace app."""
        slot_key = f"{session_id}:{app_id}"
        app = self.app_mgr.get_app(slot_key)
        if app:
            session = self.registry.get(session_id)
            project_path = session.project_path if session else ""
            env_vars = getattr(session, "env_vars", {}) if session else {}
            if self.app_mgr.launch_app(app, project_path=project_path, env_vars=env_vars):
                for i, a in enumerate(session.apps):
                    if a.get("id") == app.id:
                        session.apps[i] = app.to_dict()
                        break
                self.registry.update(session)

    def _on_stop_workspace_app(self, session_id: str, app_id: str):
        """Stop a workspace app."""
        slot_key = f"{session_id}:{app_id}"
        app = self.app_mgr.get_app(slot_key)
        if app:
            self.app_mgr.stop_app(app)

    def _start_session_apps(self, session_id: str):
        """Launch all idle/closed/failed workspace apps for a session."""
        session = self.registry.get(session_id)
        if not session:
            return
        for app in self.app_mgr.get_apps(session_id):
            if app.state in (STATE_IDLE, STATE_CLOSED, STATE_FAILED):
                self.app_mgr.launch_app(
                    app,
                    project_path=session.project_path,
                    env_vars=getattr(session, "env_vars", {}),
                )

    def _process_names_for_editor(self, session: Session) -> set[str]:
        """Return process executable names that likely belong to a session editor."""
        import shlex

        names = set()
        editor_info = EDITORS.get(session.editor, EDITORS.get("vscode", {}))
        if session.editor == "custom" and session.custom_editor_cmd:
            try:
                names.add(os.path.basename(shlex.split(session.custom_editor_cmd)[0]))
            except (ValueError, IndexError):
                pass
        else:
            command = editor_info.get("command", session.editor)
            if command:
                names.add(os.path.basename(command))
        for name in editor_info.get("process_names", []):
            if name:
                names.add(os.path.basename(name))
        return {name for name in names if name}

    def _process_names_for_app(self, app: SessionApp) -> set[str]:
        """Return process executable names that likely belong to a workspace app."""
        import shlex

        names = set()
        app_info = get_app_info(app.app_type)
        if app.app_type == "custom" and app.custom_command:
            try:
                names.add(os.path.basename(shlex.split(app.custom_command)[0]))
            except (ValueError, IndexError):
                pass
        else:
            command = app_info.get("command", app.app_type)
            if command:
                names.add(os.path.basename(command))
        for name in app_info.get("process_names", []):
            if name:
                names.add(os.path.basename(name))
        return {name for name in names if name}

    def _find_system_pids(self, process_names: set[str]) -> list[int]:
        """Find system PIDs whose executable name matches any target name."""
        if not process_names:
            return []

        import psutil

        names = {name.lower() for name in process_names}
        matches = set()
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                proc_name = os.path.basename(proc.info.get("name") or "").lower()
                cmdline = proc.info.get("cmdline") or []
                cmd0 = os.path.basename(cmdline[0]).lower() if cmdline else ""
                if proc_name in names or cmd0 in names:
                    matches.add(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return sorted(matches)

    def _expand_pids(self, pids) -> list[int]:
        """Return sorted live PID trees for the given roots."""
        roots = []
        seen = set()
        for pid in pids or []:
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                continue
            if pid > 0 and pid not in seen:
                roots.append(pid)
                seen.add(pid)
        return sorted(self.process_mgr.expand_pid_tree(roots))

    @staticmethod
    def _add_pid_detail(details: list[dict], label: str, pid: int,
                        state: str = "", xid: int = None):
        if not pid:
            return
        key = (label, int(pid))
        if any((item.get("_key") == key) for item in details):
            return
        item = {"_key": key, "label": label, "pid": int(pid), "state": state}
        if xid:
            item["xid"] = hex(xid)
        details.append(item)

    def _editor_runtime(self, session: Session) -> dict:
        """Collect runtime PID/window information for a session editor."""
        pids = set(session.spawned_pids)
        details: list[dict] = []

        if session.pid:
            pids.add(session.pid)
            self._add_pid_detail(details, "Editor launcher", session.pid,
                                 session.state)

        active_pid = self.process_mgr.get_pid(session.id)
        if active_pid:
            pids.add(active_pid)
            self._add_pid_detail(details, "Editor tracked process", active_pid,
                                 session.state)

        if session.xid:
            window_pid = (
                self.window_discovery.get_window_pid(session.xid)
                or self.process_mgr.get_window_owner_pid(session.xid)
            )
            if window_pid:
                pids.add(window_pid)
                self._add_pid_detail(details, "Editor window owner", window_pid,
                                     session.state, xid=session.xid)

        for pid in session.spawned_pids:
            self._add_pid_detail(details, "Editor spawned process", pid,
                                 session.state)

        return {
            "pids": sorted(pids),
            "expanded_pids": self._expand_pids(pids),
            "process_names": self._process_names_for_editor(session),
            "details": details,
            "xids": [session.xid] if session.xid else [],
        }

    def _app_runtime(self, app: SessionApp) -> dict:
        """Collect runtime PID/window information for a workspace app."""
        pids = set(app.spawned_pids)
        details: list[dict] = []

        if app.pid:
            pids.add(app.pid)
            self._add_pid_detail(details, f"{app.display_name} launcher",
                                 app.pid, app.state)

        if getattr(app, "window_pid", None):
            pids.add(app.window_pid)
            self._add_pid_detail(details, f"{app.display_name} window owner",
                                 app.window_pid, app.state, xid=app.xid)
        elif app.xid:
            window_pid = (
                self.window_discovery.get_window_pid(app.xid)
                or self.process_mgr.get_window_owner_pid(app.xid)
            )
            if window_pid:
                app.window_pid = window_pid
                pids.add(window_pid)
                self._add_pid_detail(details, f"{app.display_name} window owner",
                                     window_pid, app.state, xid=app.xid)

        for pid in app.spawned_pids:
            self._add_pid_detail(details, f"{app.display_name} spawned process",
                                 pid, app.state)

        return {
            "pids": sorted(pids),
            "expanded_pids": self._expand_pids(pids),
            "process_names": self._process_names_for_app(app),
            "details": details,
            "xids": [app.xid] if app.xid else [],
        }

    def _session_runtime(self, session_id: str) -> dict:
        """Collect runtime information for a whole session."""
        session = self.registry.get(session_id)
        if not session:
            return {"expanded_pids": [], "process_names": set(),
                    "details": [], "xids": []}

        pids = set()
        process_names = set()
        details = []
        xids = []

        editor_rt = self._editor_runtime(session)
        pids.update(editor_rt["pids"])
        process_names.update(editor_rt["process_names"])
        details.extend(editor_rt["details"])
        xids.extend(editor_rt["xids"])

        for app in self.app_mgr.get_apps(session_id):
            app_rt = self._app_runtime(app)
            pids.update(app_rt["pids"])
            process_names.update(app_rt["process_names"])
            details.extend(app_rt["details"])
            xids.extend(app_rt["xids"])

        return {
            "pids": sorted(pids),
            "expanded_pids": self._expand_pids(pids),
            "process_names": process_names,
            "details": details,
            "xids": xids,
        }

    def _all_codehub_pids_for_target(self, target: dict) -> list[int]:
        """Collect same-target PID trees across CodeHub."""
        pids = set()
        kind = target.get("kind")

        if kind == "editor":
            editor = target.get("editor")
            for session in self.registry.get_all():
                if session.editor == editor:
                    pids.update(self._editor_runtime(session)["pids"])
        elif kind == "app":
            app_type = target.get("app_type")
            for session in self.registry.get_all():
                for app in self.app_mgr.get_apps(session.id):
                    if app.app_type == app_type:
                        pids.update(self._app_runtime(app)["pids"])
        elif kind == "session":
            for session in self.registry.get_all():
                pids.update(self._session_runtime(session.id)["pids"])

        return self._expand_pids(pids)

    def _build_process_target(self, session_id: str, app_id: str = "editor") -> Optional[dict]:
        """Build a ProcessKillDialog target for editor/app/session control."""
        session = self.registry.get(session_id)
        if not session:
            return None

        session_rt = self._session_runtime(session_id)

        if app_id == "__session__":
            target = {
                "id": f"session:{session_id}",
                "kind": "session",
                "session_id": session_id,
                "name": f"Session: {session.name}",
                "description": "Controls the editor and every workspace app in this session.",
                "all_codehub_label": "All CodeHub sessions",
                "pids": session_rt["expanded_pids"],
                "session_pids": session_rt["expanded_pids"],
                "process_names": session_rt["process_names"],
                "process_details": session_rt["details"],
                "xids": session_rt["xids"],
            }
        elif app_id == "editor":
            editor_info = EDITORS.get(session.editor, EDITORS.get("vscode", {}))
            editor_rt = self._editor_runtime(session)
            target = {
                "id": f"editor:{session_id}",
                "kind": "editor",
                "session_id": session_id,
                "editor": session.editor,
                "name": f"Editor: {session.name} ({editor_info.get('name', session.editor)})",
                "description": "Controls this session's editor window/process.",
                "all_codehub_label": "Same editor in CodeHub",
                "pids": editor_rt["expanded_pids"],
                "session_pids": session_rt["expanded_pids"],
                "process_names": editor_rt["process_names"],
                "process_details": editor_rt["details"],
                "xids": editor_rt["xids"],
            }
        else:
            app = self.app_mgr.get_app(f"{session_id}:{app_id}")
            if not app:
                return None
            app_rt = self._app_runtime(app)
            target = {
                "id": f"app:{session_id}:{app_id}",
                "kind": "app",
                "session_id": session_id,
                "app_id": app_id,
                "app_type": app.app_type,
                "name": f"App: {app.display_name} ({session.name})",
                "description": "Controls this workspace app window/process.",
                "all_codehub_label": "Same app type in CodeHub",
                "pids": app_rt["expanded_pids"],
                "session_pids": session_rt["expanded_pids"],
                "process_names": app_rt["process_names"],
                "process_details": app_rt["details"],
                "xids": app_rt["xids"],
            }

        target["all_codehub_pids"] = self._all_codehub_pids_for_target(target)
        target["sys_pids"] = self._expand_pids(
            self._find_system_pids(target["process_names"])
        )
        return target

    def _open_process_control(self, target: dict, default_action: str = "kill",
                              default_scope: str = "codehub") -> bool:
        """Open the process-control dialog for one target and execute it."""
        from codehub.ui.kill_dialog import ProcessKillDialog

        if not target:
            return False

        dialog = ProcessKillDialog(
            self.window,
            target_name=target["name"],
            app_pids=target.get("pids", []),
            sys_pids=target.get("sys_pids", []),
            all_codehub_pids=target.get("all_codehub_pids", []),
            session_pids=target.get("session_pids", []),
            process_details=target.get("process_details", []),
            description=target.get("description", ""),
            all_codehub_label=target.get(
                "all_codehub_label", "Same app/editor in CodeHub"
            ),
        )
        self._set_process_dialog_defaults(dialog, default_action, default_scope)

        response = dialog.run()
        _, scope, action, _ = dialog.get_result()
        dialog.destroy()

        if response != Gtk.ResponseType.OK:
            return False

        self._execute_process_control(target, scope, action)
        return True

    @staticmethod
    def _set_process_dialog_defaults(dialog, default_action: str, default_scope: str):
        if default_action == "restart":
            dialog.rb_restart.set_active(True)
        else:
            dialog.rb_kill.set_active(True)

        scope_map = {
            "codehub": dialog.rb_codehub,
            "session": getattr(dialog, "rb_session", None),
            "all_codehub": getattr(dialog, "rb_all_codehub", None),
            "out_session": dialog.rb_out_session,
            "out_codehub": dialog.rb_out_codehub,
            "all": dialog.rb_all,
        }
        rb = scope_map.get(default_scope)
        if rb and rb.get_sensitive():
            rb.set_active(True)

    def _pids_for_scope(self, target: dict, scope: str) -> list[int]:
        target_set = set(target.get("pids", []))
        session_set = set(target.get("session_pids", []))
        all_codehub_set = set(target.get("all_codehub_pids", []))
        sys_set = set(target.get("sys_pids", []))

        if scope == "codehub":
            return sorted(target_set)
        if scope == "session":
            return sorted(session_set)
        if scope == "all_codehub":
            return sorted(all_codehub_set)
        if scope == "out_session":
            return sorted(sys_set - session_set)
        if scope == "out_codehub":
            return sorted(sys_set - all_codehub_set)
        if scope == "all":
            return sorted(sys_set)
        return []

    def _execute_process_control(self, target: dict, scope: str, action: str):
        """Terminate selected PID scope, then clean/restart matching CodeHub state."""
        pids_to_kill = self._pids_for_scope(target, scope)
        for pid in pids_to_kill:
            self.process_mgr.terminate_pid_tree(pid)

        selected_affected = scope in ("codehub", "session", "all_codehub", "all")
        family_affected = scope in ("all_codehub", "all")
        session_affected = scope == "session"

        if session_affected:
            self._cleanup_session_target(target["session_id"], restart=(action == "restart"))
        elif family_affected:
            self._cleanup_process_family(target, restart=(action == "restart"))
        elif selected_affected or action == "restart":
            self._cleanup_selected_process_target(target, restart=(action == "restart"))

        if self._toast:
            verb = "Restarted" if action == "restart" else "Killed"
            self._toast.show(f"{verb} {len(pids_to_kill)} process(es)", kind="warning")

    def _cleanup_selected_process_target(self, target: dict, restart: bool):
        kind = target.get("kind")
        if kind == "session":
            self._cleanup_session_target(target["session_id"], restart=restart)
        elif kind == "editor":
            self._cleanup_editor_target(target["session_id"], restart=restart)
        elif kind == "app":
            self._cleanup_app_target(target["session_id"], target["app_id"], restart=restart)

    def _cleanup_process_family(self, target: dict, restart: bool):
        kind = target.get("kind")
        if kind == "session":
            for i, session in enumerate(self.registry.get_all()):
                GLib.timeout_add(i * 150, self._cleanup_session_target,
                                 session.id, restart)
        elif kind == "editor":
            editor = target.get("editor")
            delay = 0
            for session in self.registry.get_all():
                if session.editor == editor:
                    GLib.timeout_add(delay, self._cleanup_editor_target,
                                     session.id, restart)
                    delay += 150
        elif kind == "app":
            app_type = target.get("app_type")
            delay = 0
            for session in self.registry.get_all():
                for app in self.app_mgr.get_apps(session.id):
                    if app.app_type == app_type:
                        GLib.timeout_add(delay, self._cleanup_app_target,
                                         session.id, app.id, restart)
                        delay += 150

    def _cleanup_session_target(self, session_id: str, restart: bool = False):
        session = self.registry.get(session_id)
        if not session:
            return False

        self._next_launch_token(session_id)
        if session.xid:
            self.embedding_mgr.unregister_xid(session.xid, session.id)
        self.embedding_mgr.unembed_window(session_id)
        self.process_mgr.forget(session_id)
        self.app_mgr.stop_all_apps(session_id)
        session.spawned_pids.clear()
        self._set_session_closed(session, "Restarting…" if restart else "Killed")
        self._on_timer_conditions_changed()

        if restart:
            GLib.timeout_add(700, self._restart_session_after_force_close, session_id)
        return False

    def _cleanup_editor_target(self, session_id: str, restart: bool = False):
        session = self.registry.get(session_id)
        if not session:
            return False

        self._next_launch_token(session_id)
        if session.xid:
            self.embedding_mgr.unregister_xid(session.xid, session.id)
        self.embedding_mgr.unembed_window(session_id)
        self.process_mgr.forget(session_id)
        session.spawned_pids.clear()
        self._set_session_closed(session, "Restarting…" if restart else "Killed")
        self._on_timer_conditions_changed()

        if restart:
            GLib.timeout_add(700, self._restart_session_after_force_close, session_id)
        return False

    def _cleanup_app_target(self, session_id: str, app_id: str, restart: bool = False):
        app = self.app_mgr.get_app(f"{session_id}:{app_id}")
        if not app:
            return False

        self.app_mgr.stop_app(app)
        workspace = self._workspaces.get(session_id)
        if workspace:
            workspace.update_app_status(app_id, STATE_CLOSED)

        if restart:
            GLib.timeout_add(700, self._on_start_workspace_app, session_id, app_id)
        return False

    def _prompt_kill_restart_app(self, session_id: str, app_id: str, default_action: str):
        target = self._build_process_target(session_id, app_id)
        self._open_process_control(target, default_action=default_action,
                                   default_scope="codehub")

    def _on_kill_workspace_app(self, session_id: str, app_id: str):
        self._prompt_kill_restart_app(session_id, app_id, "kill")

    def _on_restart_workspace_app(self, session_id: str, app_id: str):
        self._prompt_kill_restart_app(session_id, app_id, "restart")

    def _on_detach_workspace_app(self, session_id: str, app_id: str):
        """Detach an app into its own floating window (external state)."""
        session = self.registry.get(session_id)
        if not session:
            return
        
        # Stop embedded instance
        self._on_stop_workspace_app(session_id, app_id)
        
        # Restart it as external
        def start_external():
            app = self.app_mgr.get_app(f"{session_id}:{app_id}")
            if app:
                self.app_mgr.launch_app(app, project_path=session.project_path, env_vars=getattr(session, "env_vars", {}), force_external=True)
                if self._toast:
                    self._toast.show("App detached to window", kind="info")
        
        GLib.timeout_add(1000, start_external)

    def _on_duplicate_workspace_app(self, session_id: str, app_id: str):
        """Duplicate an app tab in the workspace."""
        session = self.registry.get(session_id)
        if not session:
            return
        
        target_app = None
        for a in session.apps:
            if a["id"] == app_id:
                target_app = a
                break
                
        if not target_app:
            return
            
        import uuid
        import copy
        new_app = copy.deepcopy(target_app)
        new_app["id"] = f"{new_app.get('app_type', 'app')}-{uuid.uuid4().hex[:6]}"
        new_app["display_name"] = f"{new_app.get('display_name', 'App')} (Copy)"
        new_app["spawned_pids"] = []
        
        session.apps.append(new_app)
        self.registry.update(session)
        
        workspace = self._workspaces.get(session_id)
        if workspace:
            app_obj = SessionApp.from_dict(new_app)
            app_obj.session_id = session_id
            self.app_mgr.register_app(app_obj)
            
            from codehub.utils.constants import APPS
            app_info = APPS.get(app_obj.app_type, APPS.get("custom", {}))
            workspace.add_app_tab(
                app_obj.id, app_obj.display_name,
                icon=app_obj.icon or app_info.get("icon", "🔧"),
            )
            if self._toast:
                self._toast.show(f"Duplicated {app_obj.display_name}", kind="success")

    def _on_workspace_app_selected(self, session_id: str, app_id: str):
        """Handle app tab selection in a workspace — focus the app window."""
        if app_id == "editor":
            session = self.registry.get(session_id)
            if session and session.state == STATE_EMBEDDED:
                self._schedule_embedded_focus(session_id)
            elif session and session.state == STATE_EXTERNAL:
                self._focus_session_window(session_id)
        elif app_id.startswith("term-"):
            # Focus native widget if needed
            workspace = self._workspaces.get(session_id)
            if workspace:
                container = workspace.get_container(app_id)
                if container:
                    container.grab_focus()
        else:
            slot_key = f"{session_id}:{app_id}"
            app = self.app_mgr.get_app(slot_key)
            if app and app.xid:
                if app.state == STATE_EMBEDDED:
                    # Focus the embedded socket/window
                    self.embedding_mgr.focus_embedded(slot_key)
                elif app.state == STATE_EXTERNAL:
                    self.embedding_mgr.show_external_window(app.xid)

    def _on_recover_workspace_app(self, session_id: str, app_id: str):
        """Allow manual re-embedding of an orphaned or invisible window."""
        session = self.registry.get(session_id)
        if not session:
            return

        from codehub.ui.recovery_dialog import RecoveryDialog
        from codehub.utils.constants import EDITORS, APPS

        # 1. Identify target info
        if app_id == "editor":
            editor_info = EDITORS.get(session.editor, EDITORS.get("vscode", {}))
            wm_class = editor_info.get("wm_class", "code")
            target_name = f"Editor: {editor_info.get('name', session.editor)}"
            slot_key = session_id
        else:
            slot_key = f"{session_id}:{app_id}"
            app = self.app_mgr.get_app(slot_key)
            if not app:
                return
            app_info = APPS.get(app.app_type, APPS.get("custom", {}))
            wm_class = app.custom_wm_class or app_info.get("wm_class", "")
            target_name = f"App: {app.display_name}"

        # 2. Find candidates (unmanaged windows of this class)
        owned_xids = self.embedding_mgr.get_owned_xids()
        all_windows = self.window_discovery.snapshot_windows(wm_class)
        
        candidates = []
        for xid, title in all_windows.items():
            if xid not in owned_xids or self.embedding_mgr._owned_xids.get(xid) == slot_key:
                candidates.append((xid, title))

        if not candidates:
            # Search by PID tree as fallback
            spawned = session.spawned_pids if app_id == "editor" else app.spawned_pids
            for pid in spawned:
                xid = self.window_discovery.find_window_by_pid(pid, wm_class=wm_class, timeout=1)
                if xid and (xid not in owned_xids or self.embedding_mgr._owned_xids.get(xid) == slot_key) and xid not in [c[0] for c in candidates]:
                    candidates.append((xid, self.window_discovery.get_window_title(xid)))

        if not candidates:
            # BROAD SEARCH: find ANY main window not owned by us
            all_main = self.window_discovery.snapshot_all_main_windows()
            for xid, title in all_main.items():
                if xid not in owned_xids or self.embedding_mgr._owned_xids.get(xid) == slot_key:
                    candidates.append((xid, title))
            
            if candidates and self._toast:
                self._toast.show(f"No {wm_class} windows found. Showing all visible windows.", kind="warning")

        # 3. Show dialog
        dialog = RecoveryDialog(self.window, target_name, candidates)
        response = dialog.run()
        xid = dialog.get_selected_xid()
        dialog.destroy()

        if response == Gtk.ResponseType.CLOSE:
            # Kill & Restart requested
            if app_id == "editor":
                self._cleanup_session_target(session_id, restart=True)
            else:
                self._cleanup_app_target(session_id, app_id, restart=True)
            return

        if response == Gtk.ResponseType.OK and xid:
            print(f"[App] Manually attaching XID {xid} to slot {slot_key}")
            # Reset state if already embedded
            if self.embedding_mgr.is_embedded(slot_key):
                self.embedding_mgr.unembed_window(slot_key)
            
            self.embedding_mgr.register_xid(xid, slot_key)
            
            workspace = self._workspaces.get(session_id)
            container = workspace.get_container(app_id) if workspace else None
            
            if app_id == "editor":
                session.xid = xid
                session.state = STATE_EMBEDDING
                self._update_session_state(session_id, STATE_EMBEDDING)
                self.process_mgr.set_xid(session_id, xid)
            else:
                app.xid = xid
                app.state = STATE_EMBEDDING
                if workspace:
                    workspace.update_app_status(app_id, STATE_EMBEDDING)

            def on_success():
                try:
                    if app_id == "editor":
                        session.state = STATE_EMBEDDED
                        self._update_session_state(session_id, STATE_EMBEDDED)
                        self._on_timer_conditions_changed()
                        self.headerbar.set_session_info(session.name, "Embedded")
                        self.embedding_mgr.set_plug_removed_callback(
                            session_id, self._on_session_window_died)
                    else:
                        app.state = STATE_EMBEDDED
                        if workspace:
                            workspace.update_app_status(app_id, STATE_EMBEDDED)
                    if self._toast:
                        self._toast.show(f"Embedded {target_name} successfully", kind="success")
                except Exception as e:
                    print(f"[App] Recovery success error: {e}")

            def on_failure():
                try:
                    if app_id == "editor":
                        session.state = STATE_EXTERNAL
                        self._update_session_state(session_id, STATE_EXTERNAL)
                        self._on_timer_conditions_changed()
                        self.headerbar.set_session_info(session.name, "External window")
                    else:
                        app.state = STATE_EXTERNAL
                        if workspace:
                            workspace.update_app_status(app_id, STATE_EXTERNAL)
                    if self._toast:
                        self._toast.show(f"Failed to embed {target_name}", kind="error")
                except Exception as e:
                    print(f"[App] Recovery failure error: {e}")

            self.embedding_mgr.embed_window(slot_key, xid, container,
                                             on_success=on_success,
                                             on_failure=on_failure)

    def _on_rebuild_sidebar(self, search_text=""):
        self.sidebar.rebuild(self.registry.get_all(), search_text=search_text)

    def _on_open_terminal(self, session_id: str):
        session = self.registry.get(session_id)
        if not session:
            return
        workspace = self._workspaces.get(session_id)
        if not workspace:
            return

        import uuid
        from codehub.ui.terminal import IntegratedTerminal
        from codehub.utils.constants import STATE_EMBEDDED

        term_id = f"term-{uuid.uuid4().hex[:6]}"
        env_vars = getattr(session, "env_vars", {})
        term_container = IntegratedTerminal(cwd=session.project_path, env_vars=env_vars)
        workspace.add_app_tab(term_id, "Terminal", icon=">_", container=term_container)
        workspace.update_app_status(term_id, STATE_EMBEDDED)
        workspace.select_app(term_id)

    def _on_app_state_changed(self, session_id: str, app_id: str, new_state: str):
        """Update workspace tab status when an app's state changes."""
        workspace = self._workspaces.get(session_id)
        if workspace:
            workspace.update_app_status(app_id, new_state)

        session = self.registry.get(session_id)
        app = self.app_mgr.get_app(f"{session_id}:{app_id}")
        if session and app:
            for i, item in enumerate(session.apps):
                if item.get("id") == app_id:
                    session.apps[i] = app.to_dict()
                    self.registry.update(session)
                    break

    def _update_session_state(self, session_id: str, state: str):
        """Update both the sidebar status AND workspace editor tab status.

        This single entry-point replaces direct ``self.sidebar.update_status``
        calls so the workspace tab stays in sync automatically.
        """
        self.sidebar.update_status(session_id, state)
        workspace = self._workspaces.get(session_id)
        if workspace and hasattr(workspace, "get_parent") and workspace.get_parent():
            workspace.update_app_status("editor", state)

        if state in (STATE_IDLE, STATE_CLOSED, STATE_FAILED):
            # Flush any running timer so history gets accurate accumulated time
            self._flush_session_timer(session_id)
            session = self.registry.get(session_id)
            if session:
                # Log to session history using time since reset as the duration
                from datetime import datetime
                duration = getattr(session, "time_since_reset", 0)
                if duration > 0:
                    self.session_history.add_entry(
                        session_id=session_id,
                        session_name=session.name,
                        duration_seconds=duration,
                        editor=session.editor,
                        stopped_at=datetime.now().isoformat(),
                    )
                    # Reset time_since_reset after logging so each history entry
                    # represents a distinct "run" of the session.
                    session.time_since_reset = 0
                    self.registry.update(session)
                # Clear goal alert flag so it can trigger again next run
                self._goal_alerted.discard(session_id)

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

    def _on_scan_projects(self):
        """Prompt for a directory, scan for projects, and show a dialog."""
        dialog = Gtk.FileChooserDialog(
            title="Select Directory to Scan",
            parent=self.window,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Scan", Gtk.ResponseType.OK
        )
        
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            dialog.destroy()
            self._do_scan_projects(path)
        else:
            dialog.destroy()

    def _do_scan_projects(self, path: str):
        pass  # Implementation is elsewhere in app.py or will be added later if needed

    def _on_export_backup(self):
        """Export all sessions to a JSON file."""
        dialog = Gtk.FileChooserDialog(
            title="Export Backup",
            parent=self.window,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Export", Gtk.ResponseType.OK
        )
        
        # Add JSON filter
        filter_json = Gtk.FileFilter()
        filter_json.set_name("JSON Files")
        filter_json.add_pattern("*.json")
        dialog.add_filter(filter_json)
        
        dialog.set_current_name("codehub_backup.json")
        
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            filepath = dialog.get_filename()
            dialog.destroy()
            try:
                import json
                import shutil
                shutil.copy2(self.registry._path, filepath)
                if self._toast:
                    self._toast.show(f"Backup exported successfully", kind="success")
            except Exception as e:
                self._show_error("Export Failed", str(e))
        else:
            dialog.destroy()

    def _on_import_backup(self):
        """Import sessions from a JSON file."""
        dialog = Gtk.FileChooserDialog(
            title="Import Backup",
            parent=self.window,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Import", Gtk.ResponseType.OK
        )
        
        filter_json = Gtk.FileFilter()
        filter_json.set_name("JSON Files")
        filter_json.add_pattern("*.json")
        dialog.add_filter(filter_json)
        
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            filepath = dialog.get_filename()
            dialog.destroy()
            try:
                import json
                with open(filepath, "r") as f:
                    data = json.load(f)
                
                # Check format validity loosely
                if not isinstance(data, list):
                    raise ValueError("Invalid backup format")
                    
                import shutil
                shutil.copy2(filepath, self.registry._path)
                self.registry.load()
                self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())
                
                if self._toast:
                    self._toast.show("Backup imported successfully", kind="success")
            except Exception as e:
                self._show_error("Import Failed", str(e))
        else:
            dialog.destroy()
        import os
        from codehub.session_registry import Session
        
        found = []
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            if 'package.json' in files or 'requirements.txt' in files or '.git' in os.listdir(root):
                found.append(root)
                dirs.clear()
        
        if not found:
            self._show_error("Scan Complete", f"No projects found in {path}")
            return
            
        dialog = Gtk.Dialog(
            title="Projects Found",
            transient_for=self.window,
            modal=True,
            use_header_bar=True
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Add Selected", Gtk.ResponseType.OK
        )
        dialog.set_default_size(500, 400)
        
        content = dialog.get_content_area()
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        content.pack_start(scroll, True, True, 0)
        
        listbox = Gtk.ListBox()
        scroll.add(listbox)
        
        checkboxes = {}
        for proj in sorted(found):
            row = Gtk.ListBoxRow()
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            hbox.set_margin_start(10)
            hbox.set_margin_end(10)
            hbox.set_margin_top(5)
            hbox.set_margin_bottom(5)
            
            chk = Gtk.CheckButton()
            chk.set_active(True)
            checkboxes[proj] = chk
            hbox.pack_start(chk, False, False, 0)
            
            lbl = Gtk.Label(label=proj, xalign=0)
            hbox.pack_start(lbl, True, True, 0)
            row.add(hbox)
            listbox.add(row)
            
        dialog.show_all()
        response = dialog.run()
        
        if response == Gtk.ResponseType.OK:
            added = 0
            for proj, chk in checkboxes.items():
                if chk.get_active():
                    name = os.path.basename(proj)
                    s = Session(name=name, project_path=proj)
                    s.order = self.registry.count()
                    self.registry.add(s)
                    self._create_session_workspace(s)
                    added += 1
            if added > 0:
                self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())
                
        dialog.destroy()

    def _on_new_session(self):
        """Show the new session dialog."""
        groups = self.group_registry.get_all()
        templates = self.template_registry.get_all()
        dialog = SessionDialog(self.window, groups=groups, templates=templates)
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            valid, error = dialog.validate()
            if valid:
                session = dialog.get_session()
                # Assign a sensible default order
                session.order = self.registry.count()
                self.registry.add(session)

                self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())

                # Create session workspace
                self._create_session_workspace(session)

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
                # If goal changed, clear the alert so it can re-trigger
                if updated.goal_time_seconds != getattr(session, "goal_time_seconds", 0):
                    self._goal_alerted.discard(session_id)
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
            # Flush timer so accumulated time is not lost
            self._flush_session_timer(session_id)
            # Stop and clean up all workspace apps
            self.app_mgr.stop_all_apps(session_id)
            self.process_mgr.terminate(session_id)
            self.embedding_mgr.remove_session(session_id)
            self.content.remove_session_container(session_id)
            self.sidebar.remove_session(session_id)
            self.registry.remove(session_id)
            self._workspaces.pop(session_id, None)

            if self._active_session_id == session_id:
                self._active_session_id = None
                self.content.show_empty()
                self.headerbar.set_session_info("")
                self._on_timer_conditions_changed()
            # Close any open notes dialog for this session
            dlg = self._notes_dialogs.pop(session_id, None)
            if dlg:
                dlg.destroy()
            dlg_plans = self._plans_dialogs.pop(session_id, None)
            if dlg_plans:
                dlg_plans.destroy()
            dlg_tasks = self._tasks_dialogs.pop(session_id, None)
            if dlg_tasks:
                dlg_tasks.destroy()

    def _on_quick_rename_session(self, session_id: str):
        """Show a quick inline rename dialog for a session."""
        session = self.registry.get(session_id)
        if not session:
            return

        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Rename Session",
        )
        dialog.format_secondary_text("Enter a new name for this session:")
        content = dialog.get_content_area()
        entry = Gtk.Entry()
        entry.set_text(session.name)
        entry.set_margin_top(8)
        entry.set_margin_start(12)
        entry.set_margin_end(12)
        entry.set_margin_bottom(8)
        entry.connect("activate", lambda w: dialog.response(Gtk.ResponseType.OK))
        content.pack_start(entry, False, False, 0)
        entry.show()
        entry.grab_focus()

        response = dialog.run()
        new_name = entry.get_text().strip()
        dialog.destroy()

        if response == Gtk.ResponseType.OK and new_name:
            session.name = new_name
            self.registry.update(session)
            self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())
            self.sidebar.select_session(session_id)
            if self._toast:
                self._toast.show(f"Session renamed to '{new_name}'", kind="success")

    def _on_replace_editor(self, session_id: str):
        """Let the user select a new editor for a session, kill the old one, and start the new one."""
        session = self.registry.get(session_id)
        if not session:
            return

        # Build a small editor-picker dialog
        dialog = Gtk.Dialog(
            title="Replace Editor",
            transient_for=self.window,
            modal=True,
            destroy_with_parent=True,
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok_btn = dialog.add_button("Replace", Gtk.ResponseType.OK)
        ok_btn.get_style_context().add_class("suggested-action")
        dialog.set_default_size(360, -1)

        content = dialog.get_content_area()
        content.get_style_context().add_class("dialog-content")
        content.set_spacing(12)

        info_label = Gtk.Label(xalign=0)
        info_label.set_markup(
            f"<b>Current session:</b> {GLib.markup_escape_text(session.name)}\n"
            f"<b>Current editor:</b> {session.editor or 'none'}"
        )
        info_label.set_margin_start(4)
        content.pack_start(info_label, False, False, 0)

        sep = Gtk.Separator()
        content.pack_start(sep, False, False, 0)

        editor_label = Gtk.Label(label="Select new editor:", xalign=0)
        content.pack_start(editor_label, False, False, 0)

        editor_combo = Gtk.ComboBoxText()
        editor_combo.append("none", "None (No Editor)")
        for key, info in EDITORS.items():
            editor_combo.append(key, info["name"])

        editor_combo.set_active_id(session.editor or "none")
        content.pack_start(editor_combo, False, False, 0)

        # Custom command row
        custom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        custom_lbl = Gtk.Label(label="Custom Editor Command:", xalign=0)
        custom_box.pack_start(custom_lbl, False, False, 0)
        custom_entry = Gtk.Entry()
        custom_entry.set_placeholder_text("e.g. /usr/bin/gedit")
        if session.custom_editor_cmd:
            custom_entry.set_text(session.custom_editor_cmd)
        custom_box.pack_start(custom_entry, False, False, 0)
        content.pack_start(custom_box, False, False, 0)
        custom_box.set_no_show_all(True)
        custom_box.set_visible(session.editor == "custom")

        def on_editor_changed(combo):
            custom_box.set_visible(combo.get_active_id() == "custom")
        editor_combo.connect("changed", on_editor_changed)

        dialog.show_all()
        custom_box.set_visible(session.editor == "custom")

        response = dialog.run()
        new_editor = editor_combo.get_active_id() or "none"
        new_custom_cmd = custom_entry.get_text().strip()
        dialog.destroy()

        if response != Gtk.ResponseType.OK:
            return

        if new_editor == session.editor:
            return  # No change

        # Stop the current editor (if running)
        was_running = session.state in (STATE_EMBEDDED, STATE_EXTERNAL, STATE_STARTING,
                                        STATE_DISCOVERING, STATE_EMBEDDING)
        if was_running:
            self._next_launch_token(session_id)
            self._shutdown_session_runtime(session)

        # Update the session
        old_editor = session.editor
        session.editor = new_editor
        session.custom_editor_cmd = new_custom_cmd if new_editor == "custom" else ""
        self.registry.update(session)

        # Rebuild workspace with new editor label
        workspace = self._workspaces.get(session_id)
        if workspace:
            editor_info = EDITORS.get(new_editor, {})
            editor_display = editor_info.get("name", "Editor") if editor_info else "No Editor"
            workspace.rename_app_tab("editor", editor_display)

        self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())
        self.sidebar.select_session(session_id)

        if self._toast:
            self._toast.show(
                f"Editor replaced: {old_editor or 'none'} → {new_editor}",
                kind="success",
            )

        # If it was running, restart with the new editor
        if was_running and new_editor != "none":
            GLib.timeout_add(300, self._on_start_session, session_id)

    def _on_open_notes(self, session_id: str):
        """Open (or focus) the Notes & Plans window for a session."""
        # Re-present if already open
        existing = self._notes_dialogs.get(session_id)
        if existing:
            existing.present()
            return

        session = self.registry.get(session_id)
        if not session:
            return

        def _notes_changed():
            # Refresh the sidebar row so the notes-count badge stays current.
            session_now = self.registry.get(session_id)
            if session_now:
                self.sidebar.update_session(session_now)

        dlg = NotesDialog(
            self.window, session,
            save_fn=lambda: self.registry.update(session),
            on_notes_changed=_notes_changed,
            attr_name="notes",
            title_prefix="Notes",
        )
        self._notes_dialogs[session_id] = dlg
        dlg.connect("destroy", lambda w: self._notes_dialogs.pop(session_id, None))

    def _on_open_plans(self, session_id: str):
        """Open (or focus) the Plans window for a session."""
        existing = self._plans_dialogs.get(session_id)
        if existing:
            existing.present()
            return

        session = self.registry.get(session_id)
        if not session:
            return

        def _plans_changed():
            session_now = self.registry.get(session_id)
            if session_now:
                self.sidebar.update_session(session_now)

        dlg = NotesDialog(
            self.window, session,
            save_fn=lambda: self.registry.update(session),
            on_notes_changed=_plans_changed,
            attr_name="plans",
            title_prefix="Plans",
        )
        self._plans_dialogs[session_id] = dlg
        dlg.connect("destroy", lambda w: self._plans_dialogs.pop(session_id, None))

    def _on_open_tasks(self, session_id: str):
        """Open (or focus) the Tasks window for a session."""
        existing = self._tasks_dialogs.get(session_id)
        if existing:
            existing.present()
            return

        session = self.registry.get(session_id)
        if not session:
            return

        def _tasks_changed():
            session_now = self.registry.get(session_id)
            if session_now:
                self.sidebar.update_session(session_now)

        dlg = TasksDialog(
            self.window, session,
            save_fn=lambda: self.registry.update(session),
            on_tasks_changed=_tasks_changed,
        )
        self._tasks_dialogs[session_id] = dlg
        dlg.connect("destroy", lambda w: self._tasks_dialogs.pop(session_id, None))

    def _on_open_general_notes(self):
        """Open (or focus) the app-level General Notes window."""
        if self._general_notes_dialog:
            self._general_notes_dialog.present()
            return
        dlg = NotesDialog(
            self.window,
            self.app_notes.notes_obj,
            save_fn=self.app_notes.save,
            attr_name="notes",
            title_prefix="Notes",
        )
        self._general_notes_dialog = dlg
        dlg.connect("destroy", self._on_general_notes_closed)

    def _on_general_notes_closed(self, window):
        self._general_notes_dialog = None

    def _on_open_general_plans(self):
        """Open (or focus) the app-level General Plans window."""
        if self._general_plans_dialog:
            self._general_plans_dialog.present()
            return
        dlg = NotesDialog(
            self.window,
            self.app_notes.notes_obj,
            save_fn=self.app_notes.save,
            attr_name="plans",
            title_prefix="Plans",
        )
        self._general_plans_dialog = dlg
        dlg.connect("destroy", self._on_general_plans_closed)

    def _on_general_plans_closed(self, window):
        self._general_plans_dialog = None

    def _on_open_general_ideas(self):
        """Open (or focus) the app-level General Ideas window."""
        if self._general_ideas_dialog:
            self._general_ideas_dialog.present()
            return
        dlg = IdeasDialog(
            self.window,
            self.app_notes.notes_obj,
            save_fn=self.app_notes.save,
        )
        self._general_ideas_dialog = dlg
        dlg.connect("destroy", self._on_general_ideas_closed)

    def _on_general_ideas_closed(self, window):
        self._general_ideas_dialog = None

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
        self._update_session_state(session.id, STATE_CLOSED)
        self.registry.update(session)
        self.headerbar.set_session_info(session.name, header_status)

    def _find_session_window_xid(self, session: Session) -> Optional[int]:
        """Locate the current top-level window for a session."""
        if session.xid and self.window_discovery._is_window_visible(session.xid):
            return session.xid

        editor_info = EDITORS.get(session.editor, EDITORS["vscode"])
        wm_class = editor_info.get("wm_class", "")
        project_basename = os.path.basename((session.project_path or "").rstrip("/")).lower()

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
        """Focus the running window for a session, embedded or external.

        For embedded sessions the GTK socket already owns the XID, so we can
        call focus_embedded() directly on the main thread.

        For external sessions all window-visibility checks go through xwininfo
        and xdotool (blocking subprocess calls).  Those are dispatched to a
        daemon thread so the GTK main thread is never stalled.  Results are
        applied back via GLib.idle_add once the XID is resolved.
        """
        session = self.registry.get(session_id)
        if not session:
            return False

        if session.state == STATE_EMBEDDED:
            self.embedding_mgr.focus_embedded(session_id)
            return False

        # Capture what we need before leaving the main thread
        editor_info = EDITORS.get(session.editor, EDITORS["vscode"])
        wm_class = editor_info.get("wm_class", "")
        cached_xid = session.xid
        project_basename = (
            os.path.basename(session.project_path.rstrip("/")).lower()
            if session.project_path else ""
        )

        def _discover_and_focus():
            xid = None

            # Fast path: cached XID is still mapped/visible
            if cached_xid and self.window_discovery._is_window_visible(cached_xid):
                xid = cached_xid
            elif wm_class:
                visible = self.window_discovery.get_visible_main_windows_by_class(wm_class)
                if project_basename:
                    for candidate, title in visible.items():
                        if project_basename in title.lower():
                            if not self.embedding_mgr.is_owned(candidate) or self.embedding_mgr._owned_xids.get(candidate) == session_id:
                                xid = candidate
                                break
                if xid is None and len(visible) == 1:
                    candidate = next(iter(visible))
                    if not self.embedding_mgr.is_owned(candidate) or self.embedding_mgr._owned_xids.get(candidate) == session_id:
                        xid = candidate

            if not xid:
                return

            def _apply():
                session_now = self.registry.get(session_id)
                if session_now:
                    session_now.xid = xid
                    self.process_mgr.set_xid(session_id, xid)
                self.embedding_mgr.focus_xid(xid)
                return False

            GLib.idle_add(_apply)

        threading.Thread(target=_discover_and_focus, daemon=True).start()
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

    def _shutdown_session_runtime(self, session: Session):
        """Stop a session's editor window without killing shared server processes."""
        tracked_xid = session.xid

        if tracked_xid:
            self.embedding_mgr.unregister_xid(tracked_xid, session.id)

        self.embedding_mgr.unembed_window(session.id)
        self.process_mgr.terminate(session.id)

        # NOTE: We intentionally do NOT kill session.spawned_pids here.
        # Single-instance editors (Zed, VS Code, etc.) share one background
        # server process across all sessions. Killing the PID would destroy
        # every other session's window.  The window close inside terminate()
        # is sufficient to stop this session's editor.
        session.spawned_pids.clear()

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
        project_basename = os.path.basename((session.project_path or "").rstrip("/")).lower()

        if wm_class and project_basename:
            for xid, title in self.window_discovery.snapshot_windows(wm_class).items():
                if project_basename in title.lower() and xid not in xids:
                    xids.append(xid)

        return xids

    def _restart_session_after_force_close(self, session_id: str):
        """Start a session after the force-close grace period finishes."""
        self._on_start_session(session_id, reuse_existing=False)
        return False

    def _on_start_session(self, session_id: str = None, reuse_existing: bool = False):
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

        # ── No editor: just mark session as running so apps can be launched
        if not session.editor or session.editor == "none":
            session.state = STATE_EXTERNAL
            self._update_session_state(session_id, STATE_EXTERNAL)
            self._on_timer_conditions_changed()
            self.headerbar.set_session_info(session.name, "Running (no editor)")
            self.content.show_session(session_id)
            # Start workspace apps
            self._start_session_apps(session_id)
            return

        # Determine editor info
        editor_info = EDITORS.get(session.editor, EDITORS["vscode"])
        wm_class = editor_info.get("wm_class", "")
        embeddable = editor_info.get("embeddable", True)
        launch_token = self._next_launch_token(session_id)

        session.state = STATE_STARTING
        self._update_session_state(session_id, STATE_STARTING)
        self._on_timer_conditions_changed()
        self.headerbar.set_session_info(session.name, "Starting…")

        # Make sure the content area shows this session's container
        self.content.show_session(session_id)

        # Check if there is already a window open for this project
        project_basename = os.path.basename((session.project_path or "").rstrip("/"))
        existing = self.window_discovery.get_visible_main_windows_by_class(wm_class) if wm_class else {}
        if reuse_existing and embeddable:
            for xid, title in existing.items():
                if project_basename.lower() in title.lower():
                    # Only reuse if no other session already owns it!
                    if not self.embedding_mgr.is_owned(xid):
                        print(f"[App] Found existing {editor_info['name']} window "
                              f"for '{project_basename}': XID {xid}")
                        GLib.idle_add(self._do_embed, session_id, xid, launch_token)
                        return

        # Snapshot ALL windows (including hidden/embedded ones) to avoid false positives
        before_snapshot = self.window_discovery.snapshot_windows(wm_class) if wm_class else {}
        for xid in self.embedding_mgr.get_owned_xids():
            if xid not in before_snapshot:
                before_snapshot[xid] = "Managed Window"
                
        print(f"[App] Pre-launch snapshot: {len(before_snapshot)} existing windows "
              f"(class={wm_class or 'n/a'})")

        # Launch the editor
        pid = self.process_mgr.launch_editor(
            session_id, session.project_path,
            editor=session.editor,
            custom_editor_cmd=session.custom_editor_cmd,
            extra_args=session.vscode_args,
            env_vars=getattr(session, "env_vars", {})
        )

        if pid is None:
            session.state = STATE_FAILED
            self._update_session_state(session_id, STATE_FAILED)
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

        if pid not in session.spawned_pids:
            session.spawned_pids.append(pid)
            self.registry.update(session)

        if not embeddable:
            session.pid = pid
            session.state = STATE_EXTERNAL
            self._update_session_state(session_id, STATE_EXTERNAL)
            self._on_timer_conditions_changed()
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
                    self.embedding_mgr.register_xid(xid, session_id)
                    print(f"[App] Discovered external window for {session_id}: {xid}")
            
            threading.Thread(target=discover_external_xid, daemon=True).start()
            self._start_session_apps(session_id)
            return

        session.pid = pid
        session.state = STATE_DISCOVERING
        self._update_session_state(session_id, STATE_DISCOVERING)
        self.headerbar.set_session_info(session.name, "Discovering window…")

        # Start workspace apps alongside the editor
        self._start_session_apps(session_id)

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
        try:
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

            # Reject XIDs already owned by another session/app
            if xid and self.embedding_mgr.is_owned(xid):
                owner = self.embedding_mgr._owned_xids.get(xid)
                if owner != session_id:
                    print(f"[App] Discovered XID {xid} but it is already "
                          f"owned by {owner}; discarding for {session_id}")
                    xid = None

            if xid is None:
                GLib.idle_add(self._on_discovery_failed, session_id, launch_token)
                return

            GLib.idle_add(self._do_embed, session_id, xid, launch_token)
        except Exception as e:
            print(f"[App] Window discovery thread crashed for session {session_id}: {e}")
            GLib.idle_add(self._on_discovery_failed, session_id, launch_token)

    def _on_discovery_failed(self, session_id: str, launch_token: Optional[int] = None):
        """Called when window discovery times out — fall back to external mode."""
        if not self._is_current_launch_token(session_id, launch_token):
            return

        session = self.registry.get(session_id)
        if not session:
            return

        session.state = STATE_EXTERNAL
        session.xid = None
        self._update_session_state(session_id, STATE_EXTERNAL)
        self._on_timer_conditions_changed()
        self.headerbar.set_session_info(session.name, "External window")
        print(f"[App] Window discovery failed for session {session_id}, "
              "using external mode")

        # Start a background thread to discover the XID later so that
        # _focus_session_window can raise the window when the user clicks it.
        self._start_external_xid_discovery(session_id, session)

    def _start_external_xid_discovery(self, session_id: str, session):
        """
        Background thread: locate the window XID for an external session.

        Once the XID is found it is stored in session.xid so that subsequent
        calls to _focus_session_window can raise the window immediately.
        """
        editor_info = EDITORS.get(session.editor, EDITORS["vscode"])
        wm_class = editor_info.get("wm_class", "")
        pid = session.pid
        project_path = session.project_path

        def discover():
            xid = None

            # Strategy 1: PID tree — works for apps that own their process
            if pid and wm_class:
                xid = self.window_discovery.find_window_by_pid(
                    pid,
                    wm_class=wm_class,
                    project_path=project_path,
                    timeout=8,
                )

            # Strategy 2: visible window with matching class + title
            if xid is None and wm_class:
                visible = self.window_discovery.get_visible_main_windows_by_class(
                    wm_class)
                project_basename = (
                    os.path.basename(project_path.rstrip("/")).lower()
                    if project_path else ""
                )
                if project_basename:
                    for w_xid, title in visible.items():
                        if project_basename in title.lower():
                            xid = w_xid
                            break
                if xid is None and len(visible) == 1:
                    xid = next(iter(visible))

            if xid is None:
                print(f"[App] External XID discovery gave up for {session_id}")
                return

            def update():
                s = self.registry.get(session_id)
                if s and s.state == STATE_EXTERNAL and s.xid is None:
                    if self.embedding_mgr.register_xid(xid, session_id):
                        s.xid = xid
                        self.process_mgr.set_xid(session_id, xid)
                        print(f"[App] External XID discovered for {session_id}: {xid}")
                    else:
                        print(f"[App] External XID {xid} already owned, discarding for {session_id}")

            GLib.idle_add(update)

        threading.Thread(target=discover, daemon=True).start()

    def _do_embed(self, session_id: str, xid: int, launch_token: Optional[int] = None):
        """Attempt to embed the discovered window (runs on main thread)."""
        if not self._is_current_launch_token(session_id, launch_token):
            return

        session = self.registry.get(session_id)
        if not session:
            return

        session.xid = xid
        session.state = STATE_EMBEDDING
        self.embedding_mgr.register_xid(xid, session_id)
        self._update_session_state(session_id, STATE_EMBEDDING)

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

        # embed_window is async — outcome arrives via on_success / on_failure
        def on_embed_success():
            try:
                if not self._is_current_launch_token(session_id, launch_token):
                    return
                s = self.registry.get(session_id)
                if not s:
                    return
                s.state = STATE_EMBEDDED
                self._update_session_state(session_id, STATE_EMBEDDED)
                self._on_timer_conditions_changed()
                self.headerbar.set_session_info(s.name, "Embedded")
                # Register callback so we hear immediately when the window dies
                self.embedding_mgr.set_plug_removed_callback(
                    session_id, self._on_session_window_died)
                if self._active_session_id == session_id:
                    self.content.show_session(session_id)
                    self._schedule_embedded_focus(session_id)
                if self._toast:
                    self._toast.show(f"'{s.name}' embedded successfully", kind="success")
            except Exception as e:
                print(f"[App] on_embed_success error for session {session_id}: {e}")


        def on_embed_failure():
            try:
                if not self._is_current_launch_token(session_id, launch_token):
                    return
                s = self.registry.get(session_id)
                if not s:
                    return
                s.state = STATE_EXTERNAL
                self._update_session_state(session_id, STATE_EXTERNAL)
                self._on_timer_conditions_changed()
                self.headerbar.set_session_info(s.name, "External window")
                print(f"[App] Embedding failed for session {session_id}, "
                      "using external mode")
                # session.xid was set above from the discovered XID — keep it so
                # _focus_session_window can raise the window directly.
            except Exception as e:
                print(f"[App] on_embed_failure error for session {session_id}: {e}")

        self.embedding_mgr.embed_window(session_id, xid, container,
                                         on_success=on_embed_success,
                                         on_failure=on_embed_failure)

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
        self._shutdown_session_runtime(session)

        # Stop all workspace apps in this session
        self.app_mgr.stop_all_apps(session_id)

    def _on_kill_session_processes(self, session_id: str):
        """Open full process control for all processes in a session."""
        target = self._build_process_target(session_id, "__session__")
        self._open_process_control(target, default_action="kill",
                                   default_scope="session")

    def _on_embed_editor(self, session_id: str):
        """Action to attempt manual embedding of the session's editor."""
        self._on_recover_workspace_app(session_id, "editor")

        self._on_timer_conditions_changed()

    def _on_force_restart_session(self, session_id: str = None):
        """Force-close the editor and all apps for a session, then relaunch them."""
        if session_id is None:
            session_id = self._active_session_id
        if session_id is None:
            return

        target = self._build_process_target(session_id, "__session__")
        if self._open_process_control(target, default_action="restart",
                                      default_scope="session"):
            self.sidebar.select_session(session_id)

    def _on_session_selected(self, listbox, row):
        """Handle sidebar session selection."""
        if row is None or not isinstance(row, SessionRow):
            return

        session_id = row.session.id
        prev_session_id = self._active_session_id

        # ── Session isolation: hide previous session's apps ──────────
        if prev_session_id and prev_session_id != session_id:
            self.app_mgr.hide_session_apps(prev_session_id)
            # Also hide the editor's external window if it has one
            prev_session = self.registry.get(prev_session_id)
            if (prev_session and prev_session.state == STATE_EXTERNAL
                    and prev_session.xid):
                self.embedding_mgr.hide_external_window(prev_session.xid)

        self._active_session_id = session_id
        session = self.registry.get(session_id)

        # ── Update timers based on new selection ─────────────────────
        self._on_timer_conditions_changed()

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

            # ── Session isolation: show new session's apps ───────────
            self.app_mgr.show_session_apps(session_id)

            if session.state == STATE_EMBEDDED:
                self._schedule_embedded_focus(session_id)
            elif session.state == STATE_EXTERNAL:
                # Show the editor's external window
                if session.xid:
                    self.embedding_mgr.show_external_window(session.xid)
                # Retry focus at increasing delays — the background XID
                # discovery thread may still be running on first attempt.
                for delay in (80, 350, 900, 2000):
                    GLib.timeout_add(delay, self._focus_session_window, session_id)

    def _on_show_session_details(self, session_id: str, relative_to):
        """Show live session details, including window owner PIDs."""
        session = self.registry.get(session_id)
        if not session:
            return

        popover = Gtk.Popover(relative_to=relative_to)
        popover.set_position(Gtk.PositionType.BOTTOM)
        popover.get_style_context().add_class("details-popover")

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.set_margin_start(16)
        outer.set_margin_end(16)
        outer.set_margin_top(16)
        outer.set_margin_bottom(16)

        title = Gtk.Label(xalign=0)
        title.get_style_context().add_class("details-title")
        title.set_markup("SESSION DETAILS")
        outer.pack_start(title, False, False, 0)

        def add_row(parent, key: str, value: str):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            key_lbl = Gtk.Label(label=key.upper(), xalign=0)
            key_lbl.get_style_context().add_class("details-label")
            key_lbl.set_size_request(120, -1)
            val_lbl = Gtk.Label(label=value or "-", xalign=0)
            val_lbl.get_style_context().add_class("details-value")
            val_lbl.set_selectable(True)
            val_lbl.set_line_wrap(True)
            val_lbl.set_max_width_chars(56)
            row.pack_start(key_lbl, False, False, 0)
            row.pack_start(val_lbl, True, True, 0)
            parent.pack_start(row, False, False, 0)

        add_row(outer, "ID", session.id)
        add_row(outer, "Name", session.name)
        add_row(outer, "Path", session.project_path)
        add_row(outer, "State", session.state.upper())

        editor_rt = self._editor_runtime(session)
        outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 2)
        editor_title = Gtk.Label(label="EDITOR PROCESS", xalign=0)
        editor_title.get_style_context().add_class("details-label")
        outer.pack_start(editor_title, False, False, 0)
        add_row(outer, "PIDs", ", ".join(str(pid) for pid in editor_rt["expanded_pids"]) or "-")
        add_row(outer, "Window XID", hex(session.xid) if session.xid else "-")
        for item in editor_rt["details"]:
            suffix = f" ({item.get('state')})" if item.get("state") else ""
            if item.get("xid"):
                suffix += f" xid={item['xid']}"
            add_row(outer, item["label"], f"{item['pid']}{suffix}")

        apps = self.app_mgr.get_apps(session_id)
        if apps:
            outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 2)
            apps_title = Gtk.Label(label="WORKSPACE APPS", xalign=0)
            apps_title.get_style_context().add_class("details-label")
            outer.pack_start(apps_title, False, False, 0)

            for app in apps:
                app_rt = self._app_runtime(app)
                add_row(
                    outer,
                    app.display_name,
                    f"{app.state.upper()} | PIDs: "
                    f"{', '.join(str(pid) for pid in app_rt['expanded_pids']) or '-'}"
                    f" | XID: {hex(app.xid) if app.xid else '-'}",
                )
                for item in app_rt["details"]:
                    suffix = f" ({item.get('state')})" if item.get("state") else ""
                    if item.get("xid"):
                        suffix += f" xid={item['xid']}"
                    add_row(outer, item["label"], f"{item['pid']}{suffix}")

        outer.show_all()
        popover.add(outer)
        popover.popup()

    def _on_kill_editor_processes(self):
        """Open global process control for running CodeHub targets."""
        from codehub.ui.kill_dialog import ProcessKillDialog

        running_targets = {}
        for session in self.registry.get_all():
            session_target = self._build_process_target(session.id, "__session__")
            if session_target and session_target.get("pids"):
                running_targets[session_target["id"]] = session_target

            editor_target = self._build_process_target(session.id, "editor")
            if editor_target and editor_target.get("pids"):
                running_targets[editor_target["id"]] = editor_target

            for app in self.app_mgr.get_apps(session.id):
                app_target = self._build_process_target(session.id, app.id)
                if app_target and app_target.get("pids"):
                    running_targets[app_target["id"]] = app_target
        
        if not running_targets:
            self._show_error("No Processes", "No tracked CodeHub processes are running.")
            return

        dialog = ProcessKillDialog(
            self.window,
            target_name="",
            show_target_selector=True,
            running_targets=running_targets,
        )
        self._set_process_dialog_defaults(dialog, "kill", "codehub")
        response = dialog.run()
        target_id, scope, action, _ = dialog.get_result()
        dialog.destroy()

        if response != Gtk.ResponseType.OK or not target_id:
            return

        self._execute_process_control(running_targets[target_id], scope, action)

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

    def _on_start_all_in_group(self, group_id: str):
        """Start every stopped session in the group.

        Sessions already running (STARTING / DISCOVERING / EMBEDDING /
        EMBEDDED / EXTERNAL) are left untouched.
        """
        stopped = {STATE_IDLE, STATE_CLOSED, STATE_FAILED}
        for session in self.registry.get_by_group(group_id):
            if session.state in stopped:
                self._on_start_session(session.id)

    def _on_force_restart_all_in_group(self, group_id: str):
        """Force-restart every session in the group.

        Running sessions are killed and relaunched.  Stopped sessions are
        started fresh.  A small stagger (150 ms between sessions) avoids
        hammering the window-discovery subsystem simultaneously.
        """
        sessions = self.registry.get_by_group(group_id)
        running = {STATE_STARTING, STATE_DISCOVERING, STATE_EMBEDDING,
                   STATE_EMBEDDED, STATE_EXTERNAL}
        stopped = {STATE_IDLE, STATE_CLOSED, STATE_FAILED}

        for i, session in enumerate(sessions):
            delay = i * 150  # ms
            if session.state in running:
                GLib.timeout_add(delay, self._cleanup_session_target,
                                 session.id, True)
            elif session.state in stopped:
                GLib.timeout_add(delay, self._on_start_session, session.id)

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
    # Session duplication
    # =========================================

    def _on_duplicate_session(self, session_id: str):
        """Duplicate a session (deep copy with new ID)."""
        import copy
        session = self.registry.get(session_id)
        if not session:
            return

        new_session = Session.from_dict(session.to_dict())
        new_session.id = str(__import__("uuid").uuid4())[:8]
        new_session.name = f"{session.name} (Copy)"
        new_session.spawned_pids = []
        new_session.total_time_seconds = 0
        new_session.time_since_reset = 0
        new_session.start_time = 0.0
        new_session.state = STATE_IDLE
        new_session.pid = None
        new_session.xid = None
        new_session.order = self.registry.count()

        self.registry.add(new_session)
        self._create_session_workspace(new_session)
        self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())
        self.sidebar.select_session(new_session.id)

        if self._toast:
            self._toast.show(f"Duplicated '{session.name}'", kind="success")

    # =========================================
    # Session hide / restore
    # =========================================

    def _on_hide_session(self, session_id: str):
        """Hide a session from the sidebar (soft-delete)."""
        session = self.registry.get(session_id)
        if not session:
            return
        session.hidden = True
        self.registry.update(session)
        self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())
        if self._toast:
            self._toast.show(f"'{session.name}' hidden", kind="info")

    def _on_unhide_session(self, session_id: str):
        """Restore a hidden session."""
        session = self.registry.get(session_id)
        if not session:
            return
        session.hidden = False
        self.registry.update(session)
        self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())
        if self._toast:
            self._toast.show(f"'{session.name}' restored", kind="success")

    def _on_hide_group(self, group_id: str):
        """Hide an entire group from the sidebar."""
        group = self.group_registry.get(group_id)
        if not group:
            return
        group.hidden = True
        self.group_registry.update(group)
        self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())
        if self._toast:
            self._toast.show(f"Group '{group.name}' hidden", kind="info")

    def _on_unhide_group(self, group_id: str):
        """Restore a hidden group."""
        group = self.group_registry.get(group_id)
        if not group:
            return
        group.hidden = False
        self.group_registry.update(group)
        self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())
        if self._toast:
            self._toast.show(f"Group '{group.name}' restored", kind="success")

    def _on_toggle_show_hidden(self):
        """Toggle visibility of hidden items in the sidebar."""
        # The toggle button state is used by the sidebar's filter func
        self.sidebar.listbox.invalidate_filter()
        self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())



    def _check_session_goal(self, session_id: str):
        """Periodically check if a session has reached its goal time."""
        session = self.registry.get(session_id)
        if not session or session_id != self._active_session_id:
            return False  # Stop the timer

        if session.goal_time_seconds <= 0:
            return False

        if session_id in self._goal_alerted:
            return True  # Already alerted, keep checking in case goal changes

        import time
        elapsed = session.time_since_reset
        if session.start_time:
            elapsed += int(time.time() - session.start_time)

        if elapsed >= session.goal_time_seconds:
            self._goal_alerted.add(session_id)
            goal_mins = session.goal_time_seconds // 60
            if self._toast:
                self._toast.show(
                    f"🎯 Goal reached! '{session.name}' — {goal_mins} min target hit!",
                    kind="success",
                )

        return True  # Keep checking

    # =========================================
    # Central timer management
    # =========================================

    def _tick_timers(self):
        """Called every second to update UI and periodically check goals."""
        self._timer_tick_count += 1

        # Update sidebar for active session (defensively)
        if self._active_session_id and self.sidebar:
            try:
                row = self.sidebar._rows.get(self._active_session_id)
                if isinstance(row, SessionRow) and row.get_parent():
                    row._update_uptime()
            except Exception:
                pass

        # Update header bar general timer
        try:
            self._update_header_general_timer()
        except Exception:
            pass

        # Flush timers to disk every 60 seconds, then restart any that
        # should still be running so we don't lose time between flushes.
        if self._timer_tick_count % 60 == 0:
            for session in self.registry.get_all():
                try:
                    self._flush_session_timer(session.id)
                except Exception:
                    pass
            try:
                self._flush_global_timer()
            except Exception:
                pass
            try:
                self._on_timer_conditions_changed()
            except Exception:
                pass

        # Check goals every 10 seconds
        if self._timer_tick_count % 10 == 0:
            if self._active_session_id:
                try:
                    self._check_session_goal(self._active_session_id)
                except Exception:
                    pass
            try:
                self._check_general_goal()
            except Exception:
                pass

        return True

    def _flush_session_timer(self, session_id: str):
        """Flush accumulated time from session.start_time into counters."""
        session = self.registry.get(session_id)
        if not session or not session.start_time:
            return
        elapsed = int(time.time() - session.start_time)
        if elapsed > 0:
            session.total_time_seconds += elapsed
            session.time_since_reset += elapsed
            self.registry.update(session)
            # Update sidebar row so badges stay current
            row = self.sidebar._rows.get(session_id)
            if isinstance(row, SessionRow):
                row._update_uptime()
        session.start_time = 0.0

    def _update_session_timer(self, session_id: str):
        """Start or stop a session's timer based on current conditions."""
        session = self.registry.get(session_id)
        if not session:
            return
        should_run = (
            session_id == self._active_session_id
            and session.state in (STATE_EMBEDDED, STATE_EXTERNAL)
            and not self._global_paused
            and not getattr(session, "paused", False)
        )
        if should_run and not session.start_time:
            session.start_time = time.time()
        elif not should_run and session.start_time:
            self._flush_session_timer(session_id)

    def _flush_global_timer(self):
        """Flush accumulated global time into settings."""
        if not self._global_start_time:
            return
        elapsed = int(time.time() - self._global_start_time)
        if elapsed > 0:
            self.settings["general_total_time_seconds"] = self.settings.get("general_total_time_seconds", 0) + elapsed
            self.settings["general_time_since_reset"] = self.settings.get("general_time_since_reset", 0) + elapsed
            self._save_settings()
        self._global_start_time = 0.0

    def _update_global_timer(self):
        """Start or stop the global timer based on whether any session is active."""
        should_run = (
            self._active_session_id is not None
            and self._is_active_session_running()
            and not self._global_paused
        )
        if should_run and not self._global_start_time:
            self._global_start_time = time.time()
        elif not should_run and self._global_start_time:
            self._flush_global_timer()

    def _is_active_session_running(self) -> bool:
        session = self.registry.get(self._active_session_id)
        return (
            session is not None
            and session.state in (STATE_EMBEDDED, STATE_EXTERNAL)
            and not getattr(session, "paused", False)
        )

    def _update_header_general_timer(self):
        elapsed = self.settings.get("general_time_since_reset", 0)
        if self._global_start_time:
            elapsed += int(time.time() - self._global_start_time)
        goal = self.settings.get("general_goal_time_seconds", 0)
        self.headerbar.update_general_timer(elapsed, goal, self._global_paused)

    def _on_timer_conditions_changed(self):
        """Call whenever anything that affects timer state changes."""
        for session in self.registry.get_all():
            self._update_session_timer(session.id)
        self._update_global_timer()
        self._update_header_general_timer()

    # ── Idle / auto-away detection ────────────────────────────────

    def _setup_activity_tracking(self):
        """Track keyboard, mouse and focus events to detect user activity."""
        event_mask = (
            Gdk.EventMask.KEY_PRESS_MASK
            | Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.SCROLL_MASK
            | Gdk.EventMask.FOCUS_CHANGE_MASK
        )
        self.window.add_events(event_mask)
        self.window.connect("key-press-event", self._on_activity_event)
        self.window.connect("button-press-event", self._on_activity_event)
        self.window.connect("scroll-event", self._on_activity_event)
        self.window.connect("motion-notify-event", self._on_activity_event)
        self.window.connect("focus-in-event", self._on_activity_event)
        # Also track key widgets so activity in sidebar / header counts
        for widget in (self.sidebar, self.headerbar):
            widget.add_events(event_mask)
            widget.connect("key-press-event", self._on_activity_event)
            widget.connect("button-press-event", self._on_activity_event)
            widget.connect("scroll-event", self._on_activity_event)
            widget.connect("motion-notify-event", self._on_activity_event)
            widget.connect("focus-in-event", self._on_activity_event)

    def _on_activity_event(self, widget, event):
        """Reset idle timer on any user interaction."""
        self._last_activity_time = time.time()
        return False

    def _get_system_idle_ms(self) -> Optional[int]:
        """Query global idle time via xprintidle (Linux). Returns None if unavailable."""
        try:
            import subprocess
            result = subprocess.run(
                ["xprintidle"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            return int(result.stdout.strip())
        except Exception:
            return None

    def _check_idle(self):
        """Called every 10s. If user is idle for 2+ min while a session timer runs, alert them."""
        if self._idle_dialog_active:
            return True

        if not self._active_session_id:
            return True

        session = self.registry.get(self._active_session_id)
        if not session or session.state not in (STATE_EMBEDDED, STATE_EXTERNAL):
            return True

        if getattr(session, "paused", False):
            return True

        # Cooldown: don't re-alert within 60s of a previous alert
        if time.time() - self._last_idle_alert_time < 60:
            return True

        # Determine idle duration
        idle_ms = self._get_system_idle_ms()
        if idle_ms is not None:
            is_idle = idle_ms > 120_000  # 2 minutes
        else:
            is_idle = time.time() - self._last_activity_time > 120

        if is_idle:
            self._auto_pause_and_alert(session)

        return True

    def _auto_pause_and_alert(self, session):
        """Auto-pause the session timer and show a modal alert dialog."""
        self._idle_dialog_active = True
        self._last_idle_alert_time = time.time()

        # Pause the session timer
        session.paused = True
        self._on_timer_conditions_changed()

        # Refresh sidebar row so the pause indicator appears
        row = self.sidebar._rows.get(session.id)
        if isinstance(row, SessionRow):
            row._update_uptime()

        if self._toast:
            self._toast.show(
                f"'{session.name}' paused — inactive for 2 min",
                kind="warning",
            )

        # Show alert dialog
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text="Session Idle",
        )
        dialog.format_secondary_text(
            f"You have been inactive for 2 minutes in '{session.name}'.\n\n"
            "Do you want to continue timing or keep it stopped?"
        )
        dialog.add_button("Keep Stopped", Gtk.ResponseType.NO)
        continue_btn = dialog.add_button("Continue Working", Gtk.ResponseType.YES)
        continue_btn.get_style_context().add_class("suggested-action")
        dialog.set_default_response(Gtk.ResponseType.YES)

        def on_response(dialog, response):
            self._idle_dialog_active = False
            if response in (Gtk.ResponseType.YES, Gtk.ResponseType.OK):
                session.paused = False
                self._on_timer_conditions_changed()
                r = self.sidebar._rows.get(session.id)
                if isinstance(r, SessionRow):
                    r._update_uptime()
                if self._toast:
                    self._toast.show(
                        f"'{session.name}' timer resumed", kind="info"
                    )
            else:
                if self._toast:
                    self._toast.show(
                        f"'{session.name}' timer stays paused", kind="info"
                    )
            dialog.destroy()

        dialog.connect("response", on_response)
        dialog.show_all()

    # ── Global timer controls ─────────────────────────────────────

    def _on_global_pause_toggle(self):
        self._global_paused = not self._global_paused
        self._on_timer_conditions_changed()
        state = "paused" if self._global_paused else "resumed"
        if self._toast:
            self._toast.show(f"All timers {state}", kind="info")

    def _on_global_reset_timer(self):
        self._flush_global_timer()
        self.settings["general_time_since_reset"] = 0
        self._save_settings()
        self._global_goal_alerted = False
        self._update_header_general_timer()
        if self._toast:
            self._toast.show("General timer reset", kind="info")

    def _on_reset_all_session_timers(self):
        for session in self.registry.get_all():
            self._flush_session_timer(session.id)
            session.time_since_reset = 0
            self.registry.update(session)
            self._goal_alerted.discard(session.id)
        self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())
        if self._toast:
            self._toast.show("All session timers reset", kind="info")

    def _on_general_goal_settings(self):
        dialog = Gtk.Dialog(
            title="General Goal Settings",
            transient_for=self.window,
            modal=True,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Save", Gtk.ResponseType.OK,
        )
        dialog.set_default_size(360, -1)

        content = dialog.get_content_area()
        content.set_spacing(12)
        content.set_margin_start(20)
        content.set_margin_end(20)
        content.set_margin_top(15)
        content.set_margin_bottom(15)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl = Gtk.Label(label="Goal Time:", xalign=0)
        lbl.set_hexpand(True)
        hbox.pack_start(lbl, True, True, 0)
        hours_spin = Gtk.SpinButton.new_with_range(0, 24, 1)
        mins_spin = Gtk.SpinButton.new_with_range(0, 59, 5)
        current = self.settings.get("general_goal_time_seconds", 0)
        hours_spin.set_value(current // 3600)
        mins_spin.set_value((current % 3600) // 60)
        hbox.pack_start(hours_spin, False, False, 0)
        hbox.pack_start(Gtk.Label(label="h"), False, False, 0)
        hbox.pack_start(mins_spin, False, False, 0)
        hbox.pack_start(Gtk.Label(label="m"), False, False, 0)
        content.pack_start(hbox, False, False, 0)

        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_goal = int(hours_spin.get_value() * 3600 + mins_spin.get_value() * 60)
            self.settings["general_goal_time_seconds"] = new_goal
            self._save_settings()
            self._global_goal_alerted = False
            self._update_header_general_timer()
            if self._toast:
                self._toast.show("General goal updated", kind="success")
        dialog.destroy()

    # ── Per-session timer controls ────────────────────────────────

    def _on_pause_session_timer(self, session_id: str):
        session = self.registry.get(session_id)
        if not session:
            return
        session.paused = not getattr(session, "paused", False)
        self._on_timer_conditions_changed()
        state = "paused" if session.paused else "resumed"
        if self._toast:
            self._toast.show(f"'{session.name}' timer {state}", kind="info")

    def _on_resume_session_timer(self, session_id: str):
        session = self.registry.get(session_id)
        if not session:
            return
        session.paused = False
        self._on_timer_conditions_changed()
        if self._toast:
            self._toast.show(f"'{session.name}' timer resumed", kind="info")

    def _on_reset_session_timer(self, session_id: str):
        session = self.registry.get(session_id)
        if not session:
            return
        self._flush_session_timer(session_id)
        session.time_since_reset = 0
        self.registry.update(session)
        self._goal_alerted.discard(session_id)
        row = self.sidebar._rows.get(session_id)
        if isinstance(row, SessionRow):
            row._update_uptime()
        if self._toast:
            self._toast.show(f"Timer reset for '{session.name}'", kind="info")

    def _on_set_session_goal(self, session_id: str):
        session = self.registry.get(session_id)
        if not session:
            return
        dialog = Gtk.Dialog(
            title=f"Goal for '{session.name}'",
            transient_for=self.window,
            modal=True,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Save", Gtk.ResponseType.OK,
        )
        dialog.set_default_size(320, -1)

        content = dialog.get_content_area()
        content.set_spacing(12)
        content.set_margin_start(20)
        content.set_margin_end(20)
        content.set_margin_top(15)
        content.set_margin_bottom(15)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl = Gtk.Label(label="Goal Time:", xalign=0)
        lbl.set_hexpand(True)
        hbox.pack_start(lbl, True, True, 0)
        hours_spin = Gtk.SpinButton.new_with_range(0, 24, 1)
        mins_spin = Gtk.SpinButton.new_with_range(0, 59, 5)
        current = getattr(session, "goal_time_seconds", 0)
        hours_spin.set_value(current // 3600)
        mins_spin.set_value((current % 3600) // 60)
        hbox.pack_start(hours_spin, False, False, 0)
        hbox.pack_start(Gtk.Label(label="h"), False, False, 0)
        hbox.pack_start(mins_spin, False, False, 0)
        hbox.pack_start(Gtk.Label(label="m"), False, False, 0)
        content.pack_start(hbox, False, False, 0)

        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_goal = int(hours_spin.get_value() * 3600 + mins_spin.get_value() * 60)
            session.goal_time_seconds = new_goal
            self.registry.update(session)
            self._goal_alerted.discard(session_id)
            row = self.sidebar._rows.get(session_id)
            if isinstance(row, SessionRow):
                row._update_uptime()
            if self._toast:
                self._toast.show(f"Goal updated for '{session.name}'", kind="success")
        dialog.destroy()

    def _check_general_goal(self):
        goal = self.settings.get("general_goal_time_seconds", 0)
        if goal <= 0:
            return
        if self._global_goal_alerted:
            return
        elapsed = self.settings.get("general_time_since_reset", 0)
        if self._global_start_time:
            elapsed += int(time.time() - self._global_start_time)
        if elapsed >= goal:
            self._global_goal_alerted = True
            goal_mins = goal // 60
            if self._toast:
                self._toast.show(
                    f"🎯 General goal reached! — {goal_mins} min target hit!",
                    kind="success",
                )

    # =========================================
    # Pomodoro callbacks
    # =========================================

    def _on_pomodoro_phase_complete(self, old_phase: str, next_phase: str):
        """Called when a Pomodoro phase finishes."""
        if self._toast:
            self._toast.show(
                f"🍅 {old_phase} complete → {next_phase}",
                kind="info",
            )
            
        # If moving to a new Work cycle, we notify ModeManager to cycle sessions.
        if "Work" in next_phase:
            self.mode_mgr.set_pomodoro_state(is_break=False, cycle=True)

    def _on_pomodoro_state_changed(self, new_state: str):
        from codehub.ui.pomodoro import POMODORO_SHORT_BREAK, POMODORO_LONG_BREAK, POMODORO_WORK, POMODORO_STOPPED
        
        is_break = new_state in (POMODORO_SHORT_BREAK, POMODORO_LONG_BREAK)
        is_work = new_state == POMODORO_WORK
        is_stopped = new_state == POMODORO_STOPPED
        
        if is_break:
            self.mode_mgr.set_pomodoro_state(is_break=True, cycle=False)
        elif is_work or is_stopped:
            self.mode_mgr.set_pomodoro_state(is_break=False, cycle=False)

    def _on_pomodoro_settings(self):
        """Show a dialog to configure Pomodoro timer values."""
        dialog = Gtk.Dialog(
            title="Pomodoro Settings",
            transient_for=self.window,
            modal=True,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Save", Gtk.ResponseType.OK,
        )
        dialog.set_default_size(360, -1)

        content = dialog.get_content_area()
        content.set_spacing(12)
        content.set_margin_start(20)
        content.set_margin_end(20)
        content.set_margin_top(15)
        content.set_margin_bottom(15)

        def add_spin(label_text, key, default, min_val=1, max_val=120):
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            lbl = Gtk.Label(label=label_text, xalign=0)
            lbl.set_hexpand(True)
            hbox.pack_start(lbl, True, True, 0)
            spin = Gtk.SpinButton.new_with_range(min_val, max_val, 1)
            spin.set_value(self.settings.get(key, default))
            hbox.pack_start(spin, False, False, 0)
            content.pack_start(hbox, False, False, 0)
            return spin

        work_spin = add_spin("Work duration (min):", "pomodoro_work", 25)
        short_spin = add_spin("Short break (min):", "pomodoro_short_break", 5)
        long_spin = add_spin("Long break (min):", "pomodoro_long_break", 15)
        cycles_spin = add_spin("Cycles before long break:", "pomodoro_cycles", 4, 1, 20)

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            self.settings["pomodoro_work"] = int(work_spin.get_value())
            self.settings["pomodoro_short_break"] = int(short_spin.get_value())
            self.settings["pomodoro_long_break"] = int(long_spin.get_value())
            self.settings["pomodoro_cycles"] = int(cycles_spin.get_value())
            self._save_settings()
            self.headerbar.pomodoro.update_settings(self.settings)
            if self._toast:
                self._toast.show("Pomodoro settings saved", kind="success")

        dialog.destroy()

    # =========================================
    # Session History viewer
    # =========================================

    def _on_show_history(self):
        """Show the session history dialog."""
        entries = self.session_history.get_all()

        dialog = Gtk.Dialog(
            title="Session History",
            transient_for=self.window,
            modal=True,
            use_header_bar=True,
        )
        dialog.add_buttons("Close", Gtk.ResponseType.CLOSE)
        dialog.set_default_size(700, 500)

        content = dialog.get_content_area()
        content.set_spacing(8)

        if not entries:
            lbl = Gtk.Label(label="No session history yet.")
            lbl.set_margin_top(40)
            content.pack_start(lbl, True, True, 0)
        else:
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            scroll.set_vexpand(True)

            # Build a tree view
            # Session, Editor, Duration, Stopped At, ID, Index
            store = Gtk.ListStore(str, str, str, str, str, int)
            for i, entry in enumerate(entries):
                dur = entry.get("duration_seconds", 0)
                h, m = dur // 3600, (dur % 3600) // 60
                dur_str = f"{h}h {m}m" if h else f"{m}m"
                stopped = entry.get("stopped_at", "")
                if stopped:
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(stopped)
                        stopped = dt.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        pass
                store.append([
                    entry.get("session_name", "Unknown"),
                    entry.get("editor", ""),
                    dur_str,
                    stopped,
                    entry.get("session_id", ""),
                    i,
                ])

            tree = Gtk.TreeView(model=store)
            for i, title in enumerate(["Session", "Editor", "Duration", "Stopped At", "ID"]):
                col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i)
                col.set_resizable(True)
                col.set_sort_column_id(i)
                tree.append_column(col)

            scroll.add(tree)
            content.pack_start(scroll, True, True, 0)

            # Restore button
            restore_btn = Gtk.Button(label="Restore Selected Session")
            restore_btn.get_style_context().add_class("suggested-action")
            def on_restore(btn):
                selection = tree.get_selection()
                model, treeiter = selection.get_selected()
                if treeiter:
                    idx = model[treeiter][5]
                    entry = entries[idx]
                    self._on_restore_session(entry.get("data", {}))
                    dialog.destroy()
            restore_btn.connect("clicked", on_restore)
            content.pack_start(restore_btn, False, False, 4)

            # Double click to restore
            def on_row_activated(tv, path, col):
                model = tv.get_model()
                treeiter = model.get_iter(path)
                idx = model[treeiter][5]
                entry = entries[idx]
                self._on_restore_session(entry.get("data", {}))
                dialog.destroy()
            tree.connect("row-activated", on_row_activated)

            # Clear button
            clear_btn = Gtk.Button(label="Clear All History")
            clear_btn.get_style_context().add_class("destructive-action")
            def on_clear(btn):
                self.session_history.clear()
                store.clear()
            clear_btn.connect("clicked", on_clear)
            content.pack_start(clear_btn, False, False, 4)

        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def _on_restore_session(self, data: dict):
        """Restore a session from historical data."""
        if not data:
            if self._toast:
                self._toast.show("No data available for this history entry", kind="error")
            return

        import uuid
        import copy
        restored_data = copy.deepcopy(data)
        
        # Generate a new ID to avoid collisions
        restored_data["id"] = str(uuid.uuid4())[:8]
        # Append " (Restored)" to the name to distinguish it
        restored_data["name"] = f"{restored_data.get('name', 'Unknown')} (Restored)"
        
        # Reset runtime fields (though to_dict usually omits them, we make sure)
        runtime_fields = ["pid", "xid", "state", "start_time", "spawned_pids"]
        for field in runtime_fields:
            restored_data.pop(field, None)
            
        # Also clean up apps' spawned_pids if they exist
        if "apps" in restored_data:
            for app in restored_data["apps"]:
                app.pop("spawned_pids", None)
                app.pop("pid", None)
                app.pop("xid", None)
                app.pop("state", None)

        session = Session.from_dict(restored_data)
        session.order = self.registry.count()
        
        self.registry.add(session)
        self.sidebar.rebuild(self.registry.get_all(), self.group_registry.get_all())
        self._create_session_workspace(session)
        self.sidebar.select_session(session.id)
        
        if self._toast:
            self._toast.show(f"Session '{session.name}' restored", kind="success")

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

            run_all_item = Gtk.MenuItem(label="▶  Run All Sessions")
            run_all_item.connect("activate", lambda w: self._on_start_all_in_group(group_id))
            menu.append(run_all_item)

            restart_all_item = Gtk.MenuItem(label="↺  Force Restart All")
            restart_all_item.connect("activate", lambda w: self._on_force_restart_all_in_group(group_id))
            menu.append(restart_all_item)

            menu.append(Gtk.SeparatorMenuItem())

            edit_item = Gtk.MenuItem(label="✎  Edit Group")
            edit_item.connect("activate", lambda w: self._on_edit_group(group_id))
            menu.append(edit_item)

            # --- Hide / Unhide ---
            group = self.group_registry.get(group_id)
            if group and group.hidden:
                unhide_item = Gtk.MenuItem(label="👁  Unhide Group")
                unhide_item.connect("activate", lambda w: self._on_unhide_group(group_id))
                menu.append(unhide_item)
            else:
                hide_item = Gtk.MenuItem(label="🙈  Hide Group")
                hide_item.connect("activate", lambda w: self._on_hide_group(group_id))
                menu.append(hide_item)

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

        restart_item = Gtk.MenuItem(label="↻  Force Restart / Process Control")
        restart_item.connect("activate", lambda w: self._on_force_restart_session(session_id))
        menu.append(restart_item)

        embed_item = Gtk.MenuItem(label="🧲  Embed Editor")
        embed_item.connect("activate", lambda w: self._on_embed_editor(session_id))
        menu.append(embed_item)

        kill_proc_item = Gtk.MenuItem(label="☠  Session Process Control")
        kill_proc_item.connect("activate", lambda w: self._on_kill_session_processes(session_id))
        kill_proc_item.get_style_context().add_class("menu-item-danger")
        menu.append(kill_proc_item)

        menu.append(Gtk.SeparatorMenuItem())

        edit_item = Gtk.MenuItem(label="✎  Edit Session")
        edit_item.connect("activate", lambda w: self._on_edit_session(session_id))
        menu.append(edit_item)

        rename_item = Gtk.MenuItem(label="✏  Quick Rename")
        rename_item.connect("activate", lambda w: self._on_quick_rename_session(session_id))
        menu.append(rename_item)

        replace_editor_item = Gtk.MenuItem(label="🔄  Replace Editor")
        replace_editor_item.connect("activate", lambda w: self._on_replace_editor(session_id))
        menu.append(replace_editor_item)

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

        template_item = Gtk.MenuItem(label="💾  Save as Template")
        template_item.connect("activate", lambda w: self._on_save_as_template(session_id))
        menu.append(template_item)

        notes_item = Gtk.MenuItem(label="📋  Notes & Plans")
        notes_item.connect("activate", lambda w: self._on_open_notes(session_id))
        menu.append(notes_item)

        menu.append(Gtk.SeparatorMenuItem())

        # ── Duplicate session ───────────────────────────────────────
        dup_item = Gtk.MenuItem(label="⧉  Duplicate Session")
        dup_item.connect("activate", lambda w: self._on_duplicate_session(session_id))
        menu.append(dup_item)

        # ── Hide / Unhide ───────────────────────────────────────────
        if session.hidden:
            unhide_item = Gtk.MenuItem(label="👁  Unhide Session")
            unhide_item.connect("activate", lambda w: self._on_unhide_session(session_id))
            menu.append(unhide_item)
        else:
            hide_item = Gtk.MenuItem(label="🙈  Hide Session")
            hide_item.connect("activate", lambda w: self._on_hide_session(session_id))
            menu.append(hide_item)

        # ── Timer controls ──────────────────────────────────────────
        menu.append(Gtk.SeparatorMenuItem())

        if getattr(session, "paused", False):
            resume_item = Gtk.MenuItem(label="▶  Resume Timer")
            resume_item.connect("activate", lambda w: self._on_resume_session_timer(session_id))
            menu.append(resume_item)
        else:
            pause_item = Gtk.MenuItem(label="⏸  Pause Timer")
            pause_item.connect("activate", lambda w: self._on_pause_session_timer(session_id))
            menu.append(pause_item)

        reset_item = Gtk.MenuItem(label="⏱  Reset Timer")
        reset_item.connect("activate", lambda w: self._on_reset_session_timer(session_id))
        menu.append(reset_item)

        goal_item = Gtk.MenuItem(label="🎯  Set Goal Time")
        goal_item.connect("activate", lambda w: self._on_set_session_goal(session_id))
        menu.append(goal_item)

        menu.append(Gtk.SeparatorMenuItem())

        remove_item = Gtk.MenuItem(label="✖  Remove Session")
        remove_item.connect("activate", lambda w: self._on_remove_session(session_id))
        menu.append(remove_item)

        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def _on_save_as_template(self, session_id: str):
        """Save the session's app configuration as a template."""
        session = self.registry.get(session_id)
        if not session:
            return

        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Save Session as Template",
        )
        dialog.format_secondary_text("Enter a name for this workspace preset:")

        content = dialog.get_content_area()
        entry = Gtk.Entry()
        entry.set_text(f"{session.name} Template")
        entry.set_margin_top(10)
        entry.set_margin_bottom(10)
        entry.show()
        content.pack_start(entry, False, False, 0)

        response = dialog.run()
        name = entry.get_text().strip()
        dialog.destroy()

        if response == Gtk.ResponseType.OK and name:
            template = SessionTemplate(
                name=name,
                editor=session.editor,
                custom_editor_cmd=session.custom_editor_cmd,
                vscode_args=session.vscode_args.copy(),
                apps=[app.copy() for app in session.apps]
            )
            self.template_registry.add(template)
            print(f"[App] Saved template: {name}")

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

    def _on_edit_active_account(self):
        if not self.active_account:
            return
        updated = self._edit_account_dialog(self.active_account.id, parent=self.window)
        if updated:
            self.active_account = updated
            self.headerbar.set_account_name(updated.name)
            if self._toast:
                self._toast.show("Account updated", kind="success")

    def _on_logout(self):
        if self._confirm_account_exit("Logout from this account?"):
            self._switch_to_account_chooser()

    def _on_switch_account(self):
        if self._confirm_account_exit("Switch accounts?"):
            self._switch_to_account_chooser()

    def _confirm_account_exit(self, text: str) -> bool:
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=text,
        )
        dialog.format_secondary_text(
            "Current account data will be saved. Embedded windows are detached from CodeHub, "
            "but launched applications are not force-killed."
        )
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.YES

    def _switch_to_account_chooser(self):
        self._save_and_cleanup()
        if self.window:
            self.window.destroy()
        self.window = None
        self.headerbar = None
        self.sidebar = None
        self.content = None
        self.paned = None
        self._toast = None
        self._active_session_id = None
        self._workspaces.clear()
        self._notes_dialogs.clear()
        self._plans_dialogs.clear()
        self._tasks_dialogs.clear()
        self._general_notes_dialog = None
        self._general_plans_dialog = None
        self._general_ideas_dialog = None
        self._launch_tokens.clear()
        self._goal_alerted.clear()
        self._global_start_time = 0.0
        self._global_goal_alerted = False
        self._timer_tick_count = 0
        self.active_account = None
        self.active_config_dir = None
        self.registry = None
        self.group_registry = None
        self.template_registry = None
        self.settings = None
        self.app_notes = None
        self.session_history = None
        self.mode_mgr = None

        self.window_discovery = WindowDiscovery()
        self.embedding_mgr = EmbeddingManager()
        self.app_mgr = AppManager(self.embedding_mgr, self.window_discovery)

        GLib.idle_add(self.do_activate)

    def _save_and_cleanup(self):
        """Save settings and clean up resources."""
        if not self.registry or not self.settings:
            return
        active_sessions = []
        for session in self.registry.get_all():
            if session.state in (STATE_STARTING, STATE_DISCOVERING, STATE_EMBEDDING, STATE_EMBEDDED, STATE_EXTERNAL):
                active_sessions.append(session.id)
        self.settings["last_active_sessions"] = active_sessions

        # Flush all running timers so time is not lost on quit
        for session in self.registry.get_all():
            self._flush_session_timer(session.id)
        self._flush_global_timer()

        self._save_settings()

        if self.mode_mgr:
            self.mode_mgr.stop_scheduler()
            self.mode_mgr.on_state_changed = None

        if self._health_check_id:
            GLib.source_remove(self._health_check_id)
            self._health_check_id = None
        if self._timer_tick_id:
            GLib.source_remove(self._timer_tick_id)
            self._timer_tick_id = None
        if self._idle_check_id:
            GLib.source_remove(self._idle_check_id)
            self._idle_check_id = None

        # VS Code / editors survive the app — don't terminate them
        self.app_mgr.cleanup()
        self.embedding_mgr.cleanup()
        self.window_discovery.close()

    def _on_about(self):
        """Show about dialog."""
        about = Gtk.AboutDialog(
            transient_for=self.window,
            modal=True,
        )
        about.set_program_name("CodeHub")
        about.set_version(__version__)
        about.set_comments(
            "A desktop app that embeds editor windows inside\n"
            "a unified session manager using X11 reparenting."
        )
        about.set_license_type(Gtk.License.MIT_X11)
        about.set_website("https://github.com/codehub")
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

    app = CodeHubApp()
    exit_status = app.run(sys.argv)
    sys.exit(exit_status)
