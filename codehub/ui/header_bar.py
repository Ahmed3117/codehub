"""Header bar — application title bar with action buttons."""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from codehub.ui.pomodoro import PomodoroTimer


def _fmt_time(seconds: int) -> str:
    hrs = seconds // 3600
    mins = (seconds % 3600) // 60
    if hrs > 0:
        return f"{hrs}h {mins:02d}m"
    return f"{mins}m"


class GeneralTimerWidget(Gtk.Box):
    """Compact general timer widget for the header bar."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.get_style_context().add_class("general-timer-widget")

        self._time_label = Gtk.Label()
        self._time_label.get_style_context().add_class("general-timer-time")
        self.pack_start(self._time_label, False, False, 0)

        self._goal_label = Gtk.Label()
        self._goal_label.get_style_context().add_class("general-timer-goal")
        self.pack_start(self._goal_label, False, False, 0)

        self._pause_btn = Gtk.Button(label="⏸")
        self._pause_btn.set_relief(Gtk.ReliefStyle.NONE)
        self._pause_btn.set_tooltip_text("Pause all timers")
        self._pause_btn.get_style_context().add_class("general-timer-btn")
        self.pack_start(self._pause_btn, False, False, 0)

        self._reset_btn = Gtk.Button(label="↺")
        self._reset_btn.set_relief(Gtk.ReliefStyle.NONE)
        self._reset_btn.set_tooltip_text("Reset general timer")
        self._reset_btn.get_style_context().add_class("general-timer-btn")
        self.pack_start(self._reset_btn, False, False, 0)

        self.on_pause = None
        self.on_reset = None

        self._pause_btn.connect("clicked", self._on_pause_clicked)
        self._reset_btn.connect("clicked", self._on_reset_clicked)

        self.update_display(0, 0, False)

    def update_display(self, elapsed: int, goal: int, paused: bool):
        self._time_label.set_text(f"🕒 {_fmt_time(elapsed)}")
        if goal > 0:
            pct = min(100, int(elapsed / goal * 100))
            self._goal_label.set_markup(f"<small>({pct}%)</small>")
            self._goal_label.show()
        else:
            self._goal_label.hide()
        self._pause_btn.set_label("▶" if paused else "⏸")
        self._pause_btn.set_tooltip_text("Resume all timers" if paused else "Pause all timers")

    def _on_pause_clicked(self, btn):
        if self.on_pause:
            self.on_pause()

    def _on_reset_clicked(self, btn):
        if self.on_reset:
            self.on_reset()


class HeaderBar(Gtk.HeaderBar):
    """Custom header bar with session actions."""

    def __init__(self):
        super().__init__()

        self.set_show_close_button(True)
        self.set_title("CodeHub")
        self.set_subtitle("Workspace Manager")
        self.get_style_context().add_class("titlebar")

        # ── Left side ────────────────────────────────────────────────
        # Sidebar toggle button (hamburger)
        self.sidebar_toggle_btn = Gtk.Button()
        toggle_icon = Gtk.Image.new_from_icon_name("view-sidebar-start-symbolic",
                                                    Gtk.IconSize.BUTTON)
        # Fallback label if icon is unavailable
        toggle_icon.set_from_icon_name("sidebar-show-symbolic", Gtk.IconSize.BUTTON)
        self.sidebar_toggle_btn.set_image(toggle_icon)
        self.sidebar_toggle_btn.set_tooltip_text("Toggle Sidebar (Ctrl+B)")
        self.sidebar_toggle_btn.get_style_context().add_class("sidebar-toggle-btn")
        self.pack_start(self.sidebar_toggle_btn)

        # Add session button
        self.add_btn = Gtk.Button()
        add_icon = Gtk.Image.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        self.add_btn.set_image(add_icon)
        self.add_btn.set_tooltip_text("New Session (Ctrl+N)")
        self.add_btn.get_style_context().add_class("suggested-action")
        self.pack_start(self.add_btn)

        self.kill_editor_btn = Gtk.Button(label="Process Control")
        self.kill_editor_btn.set_tooltip_text("View PIDs and kill or restart sessions, editors, and apps")
        self.kill_editor_btn.get_style_context().add_class("destructive-action")
        self.pack_start(self.kill_editor_btn)

        # ── General Timer ───────────────────────────────────────────
        self.general_timer = GeneralTimerWidget()
        self.pack_start(self.general_timer)

        # ── Pomodoro Timer (centre-ish) ────────────────────────────
        self.pomodoro = PomodoroTimer()
        self.pack_start(self.pomodoro)

        # ── Modes ───────────────────────────────────────────────────
        self.modes_btn = Gtk.Button(label="⚙️ Mode: Normal")
        self.modes_btn.set_tooltip_text("Configure Focus and Managed Modes")
        self.modes_btn.get_style_context().add_class("suggested-action")
        self.pack_start(self.modes_btn)

        # ── Right side ───────────────────────────────────────────────
        self.account_menu_btn = Gtk.MenuButton()
        self.account_label = Gtk.Label(label="Account")
        self.account_menu_btn.add(self.account_label)
        self.account_menu_btn.set_tooltip_text("Account")

        account_menu = Gtk.Menu()

        switch_account_item = Gtk.MenuItem(label="Switch Account")
        switch_account_item.connect("activate", self._on_switch_account)
        account_menu.append(switch_account_item)

        edit_account_item = Gtk.MenuItem(label="Edit Account")
        edit_account_item.connect("activate", self._on_edit_account)
        account_menu.append(edit_account_item)

        logout_item = Gtk.MenuItem(label="Logout")
        logout_item.connect("activate", self._on_logout)
        account_menu.append(logout_item)

        account_menu.show_all()
        self.account_menu_btn.set_popup(account_menu)
        self.pack_end(self.account_menu_btn)

        menu_btn = Gtk.MenuButton()
        menu_icon = Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON)
        menu_btn.set_image(menu_icon)
        menu_btn.set_tooltip_text("Menu")

        menu = Gtk.Menu()

        scan_item = Gtk.MenuItem(label="Scan for Projects")
        scan_item.connect("activate", self._on_scan_projects)
        menu.append(scan_item)

        history_item = Gtk.MenuItem(label="📊  Session History")
        history_item.connect("activate", self._on_history)
        menu.append(history_item)

        pomodoro_settings_item = Gtk.MenuItem(label="🍅  Pomodoro Settings…")
        pomodoro_settings_item.connect("activate", self._on_pomodoro_settings)
        menu.append(pomodoro_settings_item)

        menu.append(Gtk.SeparatorMenuItem())

        export_item = Gtk.MenuItem(label="📦  Export Backup…")
        export_item.connect("activate", self._on_export_backup)
        menu.append(export_item)

        import_item = Gtk.MenuItem(label="📥  Import Backup…")
        import_item.connect("activate", self._on_import_backup)
        menu.append(import_item)

        general_goal_item = Gtk.MenuItem(label="🎯  General Goal Settings…")
        general_goal_item.connect("activate", self._on_general_goal_settings)
        menu.append(general_goal_item)

        menu.append(Gtk.SeparatorMenuItem())

        reset_all_item = Gtk.MenuItem(label="⏱  Reset All Session Timers")
        reset_all_item.connect("activate", self._on_reset_all_session_timers)
        menu.append(reset_all_item)

        menu.append(Gtk.SeparatorMenuItem())

        about_item = Gtk.MenuItem(label="About CodeHub")
        about_item.connect("activate", self._on_about)
        menu.append(about_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", self._on_quit)
        menu.append(quit_item)

        menu.show_all()
        menu_btn.set_popup(menu)
        self.pack_end(menu_btn)


        # General Notes button — opens the app-level notes window
        self.general_notes_btn = Gtk.Button()
        notes_icon = Gtk.Image.new_from_icon_name(
            "accessories-text-editor-symbolic", Gtk.IconSize.BUTTON
        )
        self.general_notes_btn.set_image(notes_icon)
        self.general_notes_btn.set_tooltip_text("General Notes (Ctrl+Shift+N)")
        self.general_notes_btn.get_style_context().add_class("general-notes-btn")
        self.general_notes_btn.connect("clicked", self._on_general_notes)
        self.pack_end(self.general_notes_btn)

        # General Plans button
        self.general_plans_btn = Gtk.Button()
        plans_icon = Gtk.Image.new_from_icon_name(
            "format-justify-left-symbolic", Gtk.IconSize.BUTTON
        )
        self.general_plans_btn.set_image(plans_icon)
        self.general_plans_btn.set_tooltip_text("General Plans")
        self.general_plans_btn.get_style_context().add_class("general-plans-btn")
        self.general_plans_btn.connect("clicked", self._on_general_plans)
        self.pack_end(self.general_plans_btn)

        # General Ideas button
        self.general_ideas_btn = Gtk.Button()
        ideas_icon = Gtk.Image.new_from_icon_name(
            "weather-clear-symbolic", Gtk.IconSize.BUTTON
        )
        self.general_ideas_btn.set_image(ideas_icon)
        self.general_ideas_btn.set_tooltip_text("Ideas")
        self.general_ideas_btn.get_style_context().add_class("general-ideas-btn")
        self.general_ideas_btn.connect("clicked", self._on_general_ideas)
        self.pack_end(self.general_ideas_btn)

        # Callbacks
        self.on_about = None
        self.on_quit = None
        self.on_sidebar_toggle = None
        self.on_kill_editor_processes = None
        self.on_general_notes = None
        self.on_general_plans = None
        self.on_general_ideas = None
        self.on_modes_settings = None
        self.on_scan_projects = None
        self.on_export_backup = None
        self.on_import_backup = None
        self.on_history = None
        self.on_pomodoro_settings = None
        self.on_general_timer_pause = None
        self.on_general_timer_reset = None
        self.on_general_goal_settings = None
        self.on_reset_all_session_timers = None
        self.on_switch_account = None
        self.on_edit_account = None
        self.on_logout = None


        self.sidebar_toggle_btn.connect("clicked", self._on_sidebar_toggle)
        self.kill_editor_btn.connect("clicked", self._on_kill_editor_processes)
        self.modes_btn.connect("clicked", self._on_modes_settings_clicked)
        self.general_timer.on_pause = self._on_general_timer_pause
        self.general_timer.on_reset = self._on_general_timer_reset

    def _on_scan_projects(self, widget):
        if self.on_scan_projects:
            self.on_scan_projects()

    def update_general_timer(self, elapsed: int = 0, goal: int = 0, paused: bool = False):
        self.general_timer.update_display(elapsed, goal, paused)

    def set_account_name(self, name: str):
        self.account_label.set_text(name or "Account")

    def _on_general_timer_pause(self):
        if self.on_general_timer_pause:
            self.on_general_timer_pause()

    def _on_general_timer_reset(self):
        if self.on_general_timer_reset:
            self.on_general_timer_reset()

    def set_session_info(self, name: str, state: str = ""):
        """Update subtitle with active session info."""
        if name:
            subtitle = f"● {name}"
            if state:
                subtitle += f"  —  {state}"
            self.set_subtitle(subtitle)
        else:
            self.set_subtitle("Workspace Manager")

    def _on_about(self, item):
        if self.on_about:
            self.on_about()

    def _on_quit(self, item):
        if self.on_quit:
            self.on_quit()

    def _on_sidebar_toggle(self, button):
        if self.on_sidebar_toggle:
            self.on_sidebar_toggle()

    def _on_kill_editor_processes(self, button):
        if self.on_kill_editor_processes:
            self.on_kill_editor_processes()

    def _on_general_notes(self, button):
        if self.on_general_notes:
            self.on_general_notes()

    def _on_general_plans(self, button):
        if self.on_general_plans:
            self.on_general_plans()

    def _on_general_ideas(self, button):
        if self.on_general_ideas:
            self.on_general_ideas()

    def _on_modes_settings_clicked(self, button):
        if self.on_modes_settings:
            self.on_modes_settings()

    def _on_export_backup(self, item):
        if self.on_export_backup:
            self.on_export_backup()

    def _on_import_backup(self, item):
        if self.on_import_backup:
            self.on_import_backup()

    def _on_history(self, item):
        if self.on_history:
            self.on_history()

    def _on_pomodoro_settings(self, item):
        if self.on_pomodoro_settings:
            self.on_pomodoro_settings()

    def _on_general_goal_settings(self, item):
        if self.on_general_goal_settings:
            self.on_general_goal_settings()

    def _on_reset_all_session_timers(self, item):
        if self.on_reset_all_session_timers:
            self.on_reset_all_session_timers()

    def _on_switch_account(self, item):
        if self.on_switch_account:
            self.on_switch_account()

    def _on_edit_account(self, item):
        if self.on_edit_account:
            self.on_edit_account()

    def _on_logout(self, item):
        if self.on_logout:
            self.on_logout()
