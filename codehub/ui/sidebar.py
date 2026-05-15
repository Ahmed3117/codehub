"""Sidebar — Session list sidebar with groups and drag-and-drop reordering."""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango
from typing import List, Optional, Callable

from codehub.session_registry import Session
from codehub.group_registry import Group
from codehub.utils.constants import (
    SIDEBAR_WIDTH,
    STATE_IDLE, STATE_STARTING, STATE_DISCOVERING,
    STATE_EMBEDDING, STATE_EMBEDDED, STATE_EXTERNAL, STATE_FAILED, STATE_CLOSED,
    EDITORS,
)


# Single DnD target for all row types
_DND_TARGET_NAME = "application/x-codehub-row"
_DND_TARGET = Gtk.TargetEntry.new(_DND_TARGET_NAME, Gtk.TargetFlags.SAME_APP, 0)


# ──────────────────────────────────────────────────────────────────────
# SessionRow
# ──────────────────────────────────────────────────────────────────────

class SessionRow(Gtk.ListBoxRow):
    """A single session item in the sidebar list."""

    def __init__(self, session: Session, indent: bool = False):
        super().__init__()
        self.session = session
        self.row_type = "session"
        self.get_style_context().add_class("session-row")
        if indent:
            self.get_style_context().add_class("session-row-indented")

        # Main horizontal box
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        hbox.get_style_context().add_class("session-item")

        # Indent spacer for grouped sessions
        if indent:
            indent_spacer = Gtk.Box()
            indent_spacer.set_size_request(10, -1)
            hbox.pack_start(indent_spacer, False, False, 0)

        # Drag handle — DnD source lives here so it doesn't block row selection
        handle_lbl = Gtk.Label(label="⠿")
        handle_lbl.get_style_context().add_class("drag-handle")
        handle_lbl.set_tooltip_text("Drag to reorder")
        self.drag_handle = Gtk.EventBox()
        self.drag_handle.add(handle_lbl)
        self.drag_handle.set_size_request(14, -1)
        hbox.pack_start(self.drag_handle, False, False, 0)

        # Color indicator bar
        self.indicator = Gtk.DrawingArea()
        self.indicator.set_size_request(3, -1)
        self.indicator.get_style_context().add_class("session-indicator")
        self.indicator.connect("draw", self._draw_indicator)
        hbox.pack_start(self.indicator, False, False, 8)

        # Text content
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        vbox.set_hexpand(True)

        self.name_label = Gtk.Label(xalign=0)
        self.name_label.set_markup(
            f'<span font_weight="600" font_size="small">'
            f'{GLib.markup_escape_text(session.name)}</span>'
        )
        self.name_label.get_style_context().add_class("session-name")
        self.name_label.set_ellipsize(Pango.EllipsizeMode.END)
        vbox.pack_start(self.name_label, False, False, 0)

        path_display = self._abbreviate_path(session.project_path)
        self.path_label = Gtk.Label(xalign=0)
        self.path_label.set_text(path_display)
        self.path_label.get_style_context().add_class("session-path")
        self.path_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        vbox.pack_start(self.path_label, False, False, 0)

        editor_display = self._editor_display_name(session)
        self.editor_label = Gtk.Label(xalign=0)
        self.editor_label.set_markup(f'<span font_size="9pt" foreground="#7aa2f7" font_weight="bold">{GLib.markup_escape_text(editor_display.upper())}</span>')
        self.editor_label.get_style_context().add_class("session-editor")
        vbox.pack_start(self.editor_label, False, False, 0)

        # Status Box
        self.status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        self.status_label = Gtk.Label(xalign=0)
        self.status_label.get_style_context().add_class("session-status")
        self.status_box.pack_start(self.status_label, False, False, 0)
        
        self.uptime_badge = Gtk.Label()
        self.uptime_badge.get_style_context().add_class("dim-label")
        self.uptime_badge.set_markup("<small></small>")
        self.status_box.pack_start(self.uptime_badge, False, False, 0)

        vbox.pack_start(self.status_box, False, False, 4)

        # Apps Icons Box
        self.apps_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        vbox.pack_start(self.apps_box, False, False, 4)

        # Tags chip row
        self.tags_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        vbox.pack_start(self.tags_box, False, False, 2)

        hbox.pack_start(vbox, True, True, 0)

        # Play/Stop button
        self.action_btn = Gtk.Button()
        self.action_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.action_btn.set_valign(Gtk.Align.CENTER)
        self.action_btn.set_size_request(28, 28)
        self.action_btn.get_style_context().add_class("session-action-btn")
        hbox.pack_end(self.action_btn, False, False, 4)

        # Tasks button
        self.tasks_btn = Gtk.Button()
        tasks_icon = Gtk.Label(label="✓")
        self.tasks_btn.add(tasks_icon)
        self.tasks_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.tasks_btn.set_valign(Gtk.Align.CENTER)
        self.tasks_btn.set_size_request(26, 26)
        self.tasks_btn.get_style_context().add_class("session-tasks-btn")
        self.tasks_btn.set_tooltip_text("Tasks")

        # Plans button
        self.plans_btn = Gtk.Button()
        plans_icon = Gtk.Label(label="📋")
        self.plans_btn.add(plans_icon)
        self.plans_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.plans_btn.set_valign(Gtk.Align.CENTER)
        self.plans_btn.set_size_request(26, 26)
        self.plans_btn.get_style_context().add_class("session-plans-btn")
        self.plans_btn.set_tooltip_text("Plans")

        # Notes badge — shows count of active (working + waiting) items
        self.notes_badge = Gtk.Label()
        self.notes_badge.get_style_context().add_class("notes-badge")
        self.notes_badge.set_no_show_all(True)
        self.notes_badge.set_valign(Gtk.Align.CENTER)

        # Notes button
        self.notes_btn = Gtk.Button(label="📝")
        self.notes_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.notes_btn.set_valign(Gtk.Align.CENTER)
        self.notes_btn.set_size_request(26, 26)
        self.notes_btn.get_style_context().add_class("session-notes-btn")
        self.notes_btn.set_tooltip_text("Notes")

        # Details button
        self.details_btn = Gtk.Button(label="ℹ")
        self.details_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.details_btn.set_valign(Gtk.Align.CENTER)
        self.details_btn.set_size_request(26, 26)
        self.details_btn.get_style_context().add_class("session-details-btn")
        self.details_btn.set_tooltip_text("View Session Details")

        # Action Box (Hidden by default, shown on hover via CSS)
        self.action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.action_box.get_style_context().add_class("session-action-box")
        self.action_box.pack_start(self.tasks_btn, False, False, 0)
        self.action_box.pack_start(self.plans_btn, False, False, 0)
        self.action_box.pack_start(self.notes_badge, False, False, 4)
        self.action_box.pack_start(self.notes_btn, False, False, 0)
        self.action_box.pack_start(self.details_btn, False, False, 0)
        hbox.pack_end(self.action_box, False, False, 0)

        self.add(hbox)
        
        self._uptime_timer_id = None
        self.connect("destroy", self._on_destroy)

        self._compact = False

        self.update_status(session.state)
        self.update_notes_badge()
        self._render_tags(session)

        # Visual feedback for hidden state
        if getattr(session, "hidden", False):
            self.set_opacity(0.6)

        # Callbacks wired by the Sidebar
        self.on_start: Optional[Callable] = None
        self.on_stop: Optional[Callable] = None
        self.on_show_details: Optional[Callable] = None

        self.action_btn.connect("clicked", self._on_action_clicked)
        self.details_btn.connect("clicked", self._on_details_clicked)

    def set_compact_mode(self, compact: bool):
        self._compact = compact
        self.path_label.set_visible(not compact)
        self.editor_label.set_visible(not compact)
        self.status_box.set_visible(not compact)
        self.action_btn.set_visible(not compact)
        self.action_box.set_visible(not compact)
        if compact:
            self.apps_box.hide()
            self.tags_box.hide()
        else:
            self._render_app_icons()
            self._render_tags(self.session)

    def _on_details_clicked(self, button):
        """Show a popover with detailed session information."""
        if self.on_show_details:
            self.on_show_details(self.session.id, button)
            return

        popover = Gtk.Popover(relative_to=button)
        popover.set_position(Gtk.PositionType.BOTTOM)
        popover.get_style_context().add_class("details-popover")
        
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        vbox.set_margin_start(16)
        vbox.set_margin_end(16)
        vbox.set_margin_top(16)
        vbox.set_margin_bottom(16)
        
        title = Gtk.Label(xalign=0)
        title.get_style_context().add_class("details-title")
        title.set_markup(f"SESSION DETAILS")
        vbox.pack_start(title, False, False, 0)
        
        # Grid for basic details
        grid = Gtk.Grid(column_spacing=16, row_spacing=8)
        
        details = [
            ("ID", self.session.id),
            ("Name", self.session.name),
            ("Path", self.session.project_path),
            ("Editor", self._editor_display_name(self.session)),
            ("State", self.session.state.upper()),
        ]
        
        if self.session.pid:
            details.append(("PID", str(self.session.pid)))
        if self.session.xid:
            details.append(("XID", hex(self.session.xid)))
            
        for i, (key, val) in enumerate(details):
            lbl_key = Gtk.Label(label=key.upper(), xalign=0)
            lbl_key.get_style_context().add_class("details-label")
            
            lbl_val = Gtk.Label(label=val, xalign=0)
            lbl_val.get_style_context().add_class("details-value")
            lbl_val.set_selectable(True)
            lbl_val.set_ellipsize(Pango.EllipsizeMode.END)
            lbl_val.set_max_width_chars(30)
            
            grid.attach(lbl_key, 0, i, 1, 1)
            grid.attach(lbl_val, 1, i, 1, 1)
            
        vbox.pack_start(grid, False, False, 4)
            
        if self.session.apps:
            vbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
            apps_title = Gtk.Label(label="CONNECTED APPLICATIONS", xalign=0)
            apps_title.get_style_context().add_class("details-label")
            vbox.pack_start(apps_title, False, False, 0)
            
            apps_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            for app in self.session.apps:
                app_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
                app_row.get_style_context().add_class("details-app-row")
                
                icon_lbl = Gtk.Label(label=app.get("icon", "🔧"))
                icon_lbl.get_style_context().add_class("details-app-icon")
                app_row.pack_start(icon_lbl, False, False, 0)
                
                name_lbl = Gtk.Label(label=app.get("display_name", "Unknown"), xalign=0)
                name_lbl.get_style_context().add_class("details-app-name")
                app_row.pack_start(name_lbl, True, True, 0)
                
                status_lbl = Gtk.Label(label=app.get("state", "idle").upper())
                status_lbl.get_style_context().add_class("details-app-status")
                app_row.pack_end(status_lbl, False, False, 0)
                
                apps_vbox.pack_start(app_row, False, False, 0)
            vbox.pack_start(apps_vbox, False, False, 0)
        
        vbox.show_all()
        popover.add(vbox)
        popover.popup()

    # ── drawing & helpers ──────────────────────────────────────────

    def _on_destroy(self, widget):
        if getattr(self, "_uptime_timer_id", None):
            GLib.source_remove(self._uptime_timer_id)
            self._uptime_timer_id = None

    def _on_action_clicked(self, button):
        if self.session.state in (STATE_IDLE, STATE_CLOSED, STATE_FAILED):
            if self.on_start:
                self.on_start(self.session.id)
        elif self.session.state in (
                STATE_EMBEDDED, STATE_EXTERNAL, STATE_STARTING, STATE_DISCOVERING):
            if self.on_stop:
                self.on_stop(self.session.id)

    def _draw_indicator(self, widget, cr):
        alloc = widget.get_allocation()
        color = Gdk.RGBA()
        color.parse(self.session.color)
        if self.session.state == STATE_IDLE:
            cr.set_source_rgba(color.red, color.green, color.blue, 0.3)
        elif self.session.state in (STATE_EMBEDDED, STATE_EXTERNAL):
            cr.set_source_rgba(color.red, color.green, color.blue, 1.0)
        else:
            cr.set_source_rgba(color.red, color.green, color.blue, 0.6)
        radius = 2
        cr.move_to(radius, 0)
        cr.line_to(alloc.width, 0)
        cr.line_to(alloc.width, alloc.height)
        cr.line_to(radius, alloc.height)
        cr.arc(radius, alloc.height - radius, radius, 3.14159 / 2, 3.14159)
        cr.arc(radius, radius, radius, 3.14159, 3.14159 * 3 / 2)
        cr.close_path()
        cr.fill()

    @staticmethod
    def _abbreviate_path(path: str) -> str:
        import os
        home = os.path.expanduser("~")
        if path.startswith(home):
            return "~" + path[len(home):]
        return path

    @staticmethod
    def _editor_display_name(session: Session) -> str:
        """Return a human-readable editor name for display in the row."""
        if not session.editor or session.editor == "none":
            return ""
        if session.editor == "custom":
            return session.custom_editor_cmd or "Custom"
        editor_info = EDITORS.get(session.editor, {})
        return editor_info.get("name", session.editor.title())

    def update_status(self, state: str):
        self.session.state = state
        status_map = {
            STATE_IDLE:       ("● Idle",         "status-idle"),
            STATE_STARTING:   ("◐ Starting…",    "status-starting"),
            STATE_DISCOVERING:("◑ Discovering…", "status-discovering"),
            STATE_EMBEDDING:  ("◓ Embedding…",   "status-starting"),
            STATE_EMBEDDED:   ("● Embedded",     "status-embedded"),
            STATE_EXTERNAL:   ("◉ External",     "status-external"),
            STATE_FAILED:     ("✖ Failed",       "status-failed"),
            STATE_CLOSED:     ("○ Closed",       "status-idle"),
        }
        text, css_class = status_map.get(state, ("● Unknown", "status-idle"))
        ctx = self.status_label.get_style_context()
        for _, cls in status_map.values():
            ctx.remove_class(cls)
        ctx.add_class(css_class)
        self.status_label.set_text(text.upper())
        self.indicator.queue_draw()
        
        self._render_app_icons()

        is_running = state in (STATE_EMBEDDED, STATE_EXTERNAL, STATE_STARTING, STATE_DISCOVERING, STATE_EMBEDDING)
        if is_running and self._uptime_timer_id is None:
            self._uptime_timer_id = GLib.timeout_add_seconds(1, self._update_uptime)
        elif not is_running and self._uptime_timer_id is not None:
            GLib.source_remove(self._uptime_timer_id)
            self._uptime_timer_id = None
            
        self._update_uptime()

        if state in (STATE_IDLE, STATE_CLOSED, STATE_FAILED):
            self.action_btn.set_label("▶")
            self.action_btn.set_tooltip_text("Start Session")
            bc = self.action_btn.get_style_context()
            bc.remove_class("btn-stop")
            bc.add_class("btn-play")
        elif state in (STATE_STARTING, STATE_DISCOVERING, STATE_EMBEDDING):
            self.action_btn.set_label("◻")
            self.action_btn.set_tooltip_text("Stop Session")
            bc = self.action_btn.get_style_context()
            bc.remove_class("btn-play")
            bc.add_class("btn-stop")
        elif state in (STATE_EMBEDDED, STATE_EXTERNAL):
            self.action_btn.set_label("■")
            self.action_btn.set_tooltip_text("Stop Session")
            bc = self.action_btn.get_style_context()
            bc.remove_class("btn-play")
            bc.add_class("btn-stop")

    def update_notes_badge(self):
        """Show/hide the active items count badge on the row.

        'Active' means status is 'working' or 'waiting' (i.e. not done).
        The badge is hidden entirely when there are no active items so it
        doesn't take up visual space on clean sessions.
        """
        active_notes = sum(1 for n in self.session.notes if n.get("status") != "done")
        active_plans = sum(1 for n in self.session.plans if n.get("status") != "done")
        active_tasks = sum(1 for t in self.session.tasks if t.get("status") != "done")
        total_active = active_notes + active_plans + active_tasks
        
        if total_active:
            self.notes_badge.set_text(str(total_active))
            self.notes_badge.show()
        else:
            self.notes_badge.hide()

    def _render_app_icons(self):
        for child in self.apps_box.get_children():
            self.apps_box.remove(child)

        if self._compact or self.session.state in (STATE_IDLE, STATE_CLOSED, STATE_FAILED):
            self.apps_box.hide()
            return
            
        self.apps_box.show()

        # Editor icon (skip if no editor)
        if self.session.editor and self.session.editor != "none":
            editor_info = EDITORS.get(self.session.editor, {})
            icon = editor_info.get("icon", "📝")
            lbl = Gtk.Label(label=icon)
            lbl.set_tooltip_text(editor_info.get("name", "Editor"))
            self.apps_box.pack_start(lbl, False, False, 0)

        for app_dict in self.session.apps:
            from codehub.utils.constants import APPS
            app_type = app_dict.get("app_type", "custom")
            app_info = APPS.get(app_type, {})
            app_icon = app_dict.get("icon") or app_info.get("icon", "🔧")
            name = app_dict.get("display_name", app_type)
            lbl = Gtk.Label(label=app_icon)
            lbl.set_tooltip_text(name)
            self.apps_box.pack_start(lbl, False, False, 0)
            
        self.apps_box.show_all()

    def _update_uptime(self):
        import time
        start_time = getattr(self.session, "start_time", 0.0)
        total_time = getattr(self.session, "total_time_seconds", 0)
        time_since_reset = getattr(self.session, "time_since_reset", 0)
        paused = getattr(self.session, "paused", False)
        goal = getattr(self.session, "goal_time_seconds", 0)

        is_running = self.session.state in (STATE_EMBEDDED, STATE_EXTERNAL, STATE_STARTING, STATE_DISCOVERING, STATE_EMBEDDING)
        timer_running = is_running and bool(start_time) and not paused

        # Display time_since_reset as the primary metric (plus current tick if timer is running)
        display_time = time_since_reset
        if start_time and not paused:
            display_time += int(time.time() - start_time)

        if display_time > 0 or total_time > 0:
            hrs = display_time // 3600
            mins = (display_time % 3600) // 60
            secs = display_time % 60
            if hrs > 0:
                text = f"{hrs}h {mins:02d}m"
            elif mins > 0:
                text = f"{mins}m {secs:02d}s"
            else:
                text = f"{secs}s"
        else:
            text = ""

        parts = []
        if paused:
            parts.append("⏸")
        if text:
            parts.append(f"🕒 {text}")
        if goal > 0:
            goal_str = self._fmt_duration(goal)
            if display_time > 0:
                pct = min(100, int(display_time / goal * 100))
                parts.append(f"/ {goal_str} ({pct}%)")
            else:
                parts.append(f"/ {goal_str}")

        color = "" if timer_running else ' alpha="50%"'
        markup = f"<span{color}><small>{'  '.join(parts)}</small></span>" if parts else ""
        self.uptime_badge.set_markup(markup)
        self.uptime_badge.set_tooltip_text(f"Total: {self._fmt_duration(total_time)}  |  Since reset: {self._fmt_duration(display_time)}")
        return True

    @staticmethod
    def _fmt_duration(seconds: int) -> str:
        hrs = seconds // 3600
        mins = (seconds % 3600) // 60
        secs = seconds % 60
        if hrs > 0:
            return f"{hrs}h {mins:02d}m"
        elif mins > 0:
            return f"{mins}m {secs:02d}s"
        return f"{secs}s"

    def _render_tags(self, session: "Session"):
        """Render tag chip labels in the tags_box."""
        for child in self.tags_box.get_children():
            self.tags_box.remove(child)
        tags = getattr(session, "tags", [])
        if self._compact or not tags:
            self.tags_box.hide()
            return
        self.tags_box.show()
        for tag in tags[:4]:  # cap at 4 chips to avoid overflow
            chip = Gtk.Label(label=f"#{tag}")
            chip.get_style_context().add_class("tag-chip")
            self.tags_box.pack_start(chip, False, False, 0)
        self.tags_box.show_all()

    def update_session(self, session: Session):
        self.session = session
        self.name_label.set_markup(
            f'<span font_weight="600" font_size="small">'
            f'{GLib.markup_escape_text(session.name)}</span>'
        )
        self.path_label.set_text(self._abbreviate_path(session.project_path))
        self.update_status(session.state)
        self.update_notes_badge()
        self._render_tags(session)

    def set_enabled(self, enabled: bool):
        self.set_sensitive(enabled)
        if not enabled:
            self.set_opacity(0.4)
        else:
            self.set_opacity(1.0 if not getattr(self.session, "hidden", False) else 0.6)


# ──────────────────────────────────────────────────────────────────────
# GroupRow
# ──────────────────────────────────────────────────────────────────────

class GroupRow(Gtk.ListBoxRow):
    """A group-header row in the sidebar."""

    def __init__(self, group: Group, session_count: int = 0):
        super().__init__()
        self.group = group
        self.row_type = "group"
        self.get_style_context().add_class("group-row")

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        hbox.get_style_context().add_class("group-item")

        # Drag handle
        handle_lbl = Gtk.Label(label="⠿")
        handle_lbl.get_style_context().add_class("drag-handle")
        handle_lbl.set_tooltip_text("Drag to reorder")
        self.drag_handle = Gtk.EventBox()
        self.drag_handle.add(handle_lbl)
        self.drag_handle.set_size_request(18, -1)
        hbox.pack_start(self.drag_handle, False, False, 0)

        # Color indicator
        self.indicator = Gtk.DrawingArea()
        self.indicator.set_size_request(4, -1)
        self.indicator.get_style_context().add_class("group-indicator")
        self.indicator.connect("draw", self._draw_indicator)
        hbox.pack_start(self.indicator, False, False, 8)

        # Text
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.set_hexpand(True)

        self.name_label = Gtk.Label(xalign=0)
        self.name_label.set_markup(
            f'<span font_weight="700" font_size="small">'
            f'{GLib.markup_escape_text(group.name.upper())}</span>'
        )
        self.name_label.get_style_context().add_class("group-name")
        vbox.pack_start(self.name_label, False, False, 0)

        self.count_label = Gtk.Label(xalign=0)
        self.count_label.get_style_context().add_class("group-count")
        self.update_count(session_count)
        hbox.pack_start(vbox, True, True, 0)

        # Visual feedback for hidden state
        if getattr(group, "hidden", False):
            self.set_opacity(0.6)

        # Collapse / expand toggle
        self.toggle_btn = Gtk.Button()
        self.toggle_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.toggle_btn.set_valign(Gtk.Align.CENTER)
        self.toggle_btn.set_size_request(28, 28)
        self.toggle_btn.get_style_context().add_class("group-toggle-btn")
        self._refresh_toggle_icon()
        hbox.pack_end(self.toggle_btn, False, False, 4)

        self.add(hbox)
        self.toggle_btn.connect("clicked", self._on_toggle_clicked)

        # Callback set by Sidebar
        self.on_toggle: Optional[Callable] = None

    def _draw_indicator(self, widget, cr):
        alloc = widget.get_allocation()
        color = Gdk.RGBA()
        color.parse(self.group.color)
        cr.set_source_rgba(color.red, color.green, color.blue, 0.85)
        radius = 2
        cr.move_to(radius, 0)
        cr.line_to(alloc.width, 0)
        cr.line_to(alloc.width, alloc.height)
        cr.line_to(radius, alloc.height)
        cr.arc(radius, alloc.height - radius, radius, 3.14159 / 2, 3.14159)
        cr.arc(radius, radius, radius, 3.14159, 3.14159 * 3 / 2)
        cr.close_path()
        cr.fill()

    def _set_count_text(self, count: int):
        self.count_label.set_text(f"{count} session{'s' if count != 1 else ''}")

    def _refresh_toggle_icon(self):
        if self.group.collapsed:
            self.toggle_btn.set_label("▶")
            self.toggle_btn.set_tooltip_text("Expand group")
        else:
            self.toggle_btn.set_label("▼")
            self.toggle_btn.set_tooltip_text("Collapse group")

    def _on_toggle_clicked(self, _button):
        self.group.collapsed = not self.group.collapsed
        self._refresh_toggle_icon()
        if self.on_toggle:
            self.on_toggle(self.group.id, self.group.collapsed)

    def update_group(self, group: Group):
        self.group = group
        self.name_label.set_markup(
            f'<span font_weight="700" font_size="small">'
            f'{GLib.markup_escape_text(group.name.upper())}</span>'
        )
        self.indicator.queue_draw()
        self._refresh_toggle_icon()

    def update_count(self, count: int):
        self._set_count_text(count)


# ──────────────────────────────────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────────────────────────────────

class Sidebar(Gtk.Box):
    """Session sidebar with groups, sessions, and drag-and-drop reordering."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_size_request(SIDEBAR_WIDTH, -1)
        self.get_style_context().add_class("sidebar")

        # ── Header ────────────────────────────────────────────────────
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.get_style_context().add_class("sidebar-header")

        title = Gtk.Label(label="SESSIONS")
        title.get_style_context().add_class("sidebar-title")
        title.set_xalign(0)
        header.pack_start(title, True, True, 0)

        self.count_label = Gtk.Label(label="0")
        self.count_label.get_style_context().add_class("sidebar-count")
        header.pack_end(self.count_label, False, False, 4)

        self.compact_btn = Gtk.ToggleButton(label="☰")
        self.compact_btn.set_tooltip_text("Compact Mode (icons only)")
        self.compact_btn.set_relief(Gtk.ReliefStyle.NONE)
        header.pack_end(self.compact_btn, False, False, 2)

        self.pack_start(header, False, False, 0)

        # ── Search / Filter bar ───────────────────────────────────────
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        search_box.get_style_context().add_class("sidebar-search-bar")

        search_icon = Gtk.Label(label="🔍")
        search_icon.get_style_context().add_class("search-icon")
        search_box.pack_start(search_icon, False, False, 0)

        self.search_entry = Gtk.Entry()
        self.search_entry.set_placeholder_text("Search sessions…")
        self.search_entry.get_style_context().add_class("sidebar-search-entry")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("changed", self._on_search_changed)
        search_box.pack_start(self.search_entry, True, True, 0)

        clear_btn = Gtk.Button(label="✕")
        clear_btn.get_style_context().add_class("search-clear-btn")
        clear_btn.set_relief(Gtk.ReliefStyle.NONE)
        clear_btn.set_tooltip_text("Clear search")
        clear_btn.connect("clicked", lambda _: self.search_entry.set_text(""))
        search_box.pack_start(clear_btn, False, False, 0)

        self.search_box = search_box
        self.pack_start(search_box, False, False, 0)

        # ── Action bar ───────────────────────────────────────────────
        # Normal action bar (full labels) — hidden in compact mode
        self.action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.action_bar.get_style_context().add_class("sidebar-action-bar")

        self.start_all_btn = Gtk.Button(label="▶ All")
        self.start_all_btn.set_tooltip_text("Start all idle sessions")
        self.start_all_btn.get_style_context().add_class("sidebar-action-btn")
        self.action_bar.pack_start(self.start_all_btn, True, True, 0)

        self.stop_all_btn = Gtk.Button(label="■ All")
        self.stop_all_btn.set_tooltip_text("Stop all running sessions")
        self.stop_all_btn.get_style_context().add_class("sidebar-action-btn")
        self.action_bar.pack_start(self.stop_all_btn, True, True, 0)

        self.new_group_btn = Gtk.Button(label="＋ Group")
        self.new_group_btn.set_tooltip_text("Create a new group")
        self.new_group_btn.get_style_context().add_class("sidebar-action-btn")
        self.action_bar.pack_start(self.new_group_btn, True, True, 0)

        self.show_hidden_btn = Gtk.ToggleButton(label="👁 Hidden")
        self.show_hidden_btn.set_tooltip_text("Show hidden sessions")
        self.show_hidden_btn.get_style_context().add_class("sidebar-action-btn")
        self.action_bar.pack_start(self.show_hidden_btn, True, True, 0)

        self.active_only_btn = Gtk.ToggleButton(label="🟢 Active")
        self.active_only_btn.set_tooltip_text("Show only active/running sessions")
        self.active_only_btn.get_style_context().add_class("sidebar-action-btn")
        self.action_bar.pack_start(self.active_only_btn, True, True, 0)

        self.pack_start(self.action_bar, False, False, 0)

        # ── Compact action bar (icon-only vertical strip) ─────────────
        # Shown in compact mode instead of the normal action bar
        self.compact_bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.compact_bar.get_style_context().add_class("sidebar-compact-bar")
        self.compact_bar.set_no_show_all(True)
        self.compact_bar.hide()

        def _make_icon_btn(icon, tooltip, toggle=False):
            btn = Gtk.ToggleButton() if toggle else Gtk.Button()
            btn.set_label(icon)
            btn.set_tooltip_text(tooltip)
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.get_style_context().add_class("compact-icon-btn")
            return btn

        self._ci_start  = _make_icon_btn("▶", "Start all idle sessions")
        self._ci_stop   = _make_icon_btn("■", "Stop all running sessions")
        self._ci_group  = _make_icon_btn("＋", "Create a new group")
        self._ci_hidden = _make_icon_btn("👁", "Show hidden sessions", toggle=True)
        self._ci_active = _make_icon_btn("🟢", "Show only active sessions", toggle=True)

        for w in (self._ci_start, self._ci_stop, self._ci_group,
                  self._ci_hidden, self._ci_active):
            self.compact_bar.pack_start(w, False, False, 0)

        self.pack_start(self.compact_bar, False, False, 0)

        # ── Scrolled ListBox ──────────────────────────────────────────
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.get_style_context().add_class("session-list")

        # Set up ListBox as DnD drop destination
        self.listbox.drag_dest_set(
            Gtk.DestDefaults.MOTION | Gtk.DestDefaults.HIGHLIGHT,
            [_DND_TARGET],
            Gdk.DragAction.MOVE,
        )
        self.listbox.connect("drag-motion", self._on_drag_motion)
        self.listbox.connect("drag-drop", self._on_drag_drop)
        self.listbox.connect("drag-leave", self._on_drag_leave)

        # Filter function
        self.listbox.set_filter_func(self._filter_row)

        scrolled.add(self.listbox)
        self.pack_start(scrolled, True, True, 0)

        # ── Internal state ────────────────────────────────────────────
        # id → row   (both GroupRow and SessionRow)
        self._rows: dict[str, Gtk.ListBoxRow] = {}
        self._drag_row: Optional[Gtk.ListBoxRow] = None
        self._drag_highlight_row: Optional[Gtk.ListBoxRow] = None
        self._filter_text: str = ""

        # ── Public callbacks (set by app) ─────────────────────────────
        self.on_start_session: Optional[Callable] = None
        self.on_stop_session: Optional[Callable] = None
        self.on_start_all: Optional[Callable] = None
        self.on_stop_all: Optional[Callable] = None
        self.on_new_group: Optional[Callable] = None
        self.on_edit_group: Optional[Callable] = None
        self.on_remove_group: Optional[Callable] = None
        # Called with (group_id, collapsed)
        self.on_group_toggle: Optional[Callable] = None
        # Called with list of (row_type, item_id, new_order) tuples
        self.on_reorder: Optional[Callable] = None
        self.on_open_notes: Optional[Callable] = None
        self.on_open_plans: Optional[Callable] = None
        self.on_open_tasks: Optional[Callable] = None
        self.on_show_details: Optional[Callable] = None

        # Wire action bar (both normal and compact icon buttons share the same callbacks)
        self.start_all_btn.connect("clicked", lambda _: self.on_start_all and self.on_start_all())
        self.stop_all_btn.connect("clicked",  lambda _: self.on_stop_all  and self.on_stop_all())
        self.new_group_btn.connect("clicked", lambda _: self.on_new_group and self.on_new_group())
        
        self._ci_start.connect("clicked",  lambda _: self.on_start_all and self.on_start_all())
        self._ci_stop.connect("clicked",   lambda _: self.on_stop_all  and self.on_stop_all())
        self._ci_group.connect("clicked",  lambda _: self.on_new_group and self.on_new_group())

        # Keep compact icon toggles in sync with normal toggles
        self.show_hidden_btn.connect("toggled", self._sync_hidden_from_normal)
        self._ci_hidden.connect("toggled", self._sync_hidden_from_compact)
        self.active_only_btn.connect("toggled", self._sync_active_from_normal)
        self._ci_active.connect("toggled", self._sync_active_from_compact)

        self.compact_btn.connect("toggled", self._on_compact_toggled)

    def _sync_hidden_from_normal(self, btn):
        if self._ci_hidden.get_active() != btn.get_active():
            self._ci_hidden.set_active(btn.get_active())
        self.listbox.invalidate_filter()

    def _sync_hidden_from_compact(self, btn):
        if self.show_hidden_btn.get_active() != btn.get_active():
            self.show_hidden_btn.set_active(btn.get_active())

    def _sync_active_from_normal(self, btn):
        if self._ci_active.get_active() != btn.get_active():
            self._ci_active.set_active(btn.get_active())
        self.listbox.invalidate_filter()

    def _sync_active_from_compact(self, btn):
        if self.active_only_btn.get_active() != btn.get_active():
            self.active_only_btn.set_active(btn.get_active())

    def _on_compact_toggled(self, btn):
        compact = btn.get_active()
        for row in self.listbox.get_children():
            if isinstance(row, SessionRow):
                row.set_compact_mode(compact)
        if compact:
            self.set_size_request(52, -1)
            self.search_box.hide()
            self.action_bar.hide()
            self.compact_bar.show_all()
        else:
            self.set_size_request(SIDEBAR_WIDTH, -1)
            self.search_box.show()
            self.action_bar.show()
            self.compact_bar.hide()

    # ── Search / filter ───────────────────────────────────────────────

    def _on_search_changed(self, entry):
        self._filter_text = entry.get_text().strip().lower()
        self.listbox.invalidate_filter()
        self._update_count()

    def _filter_row(self, row: Gtk.ListBoxRow) -> bool:
        """Return True to show the row, False to hide it."""
        show_hidden = self.show_hidden_btn.get_active()
        active_only = self.active_only_btn.get_active()

        if isinstance(row, SessionRow):
            s = row.session

            # In active-only mode: hide inactive sessions
            if active_only:
                if s.state in (STATE_IDLE, STATE_CLOSED, STATE_FAILED):
                    return False
                # Active sessions belonging to a collapsed group still show
                # (they appear ungrouped / flat when group header is hidden)
            else:
                # Normal mode: respect group collapse
                if s.group_id:
                    grow = self._rows.get(s.group_id)
                    if isinstance(grow, GroupRow) and grow.group.collapsed:
                        return False

            # Hide hidden sessions unless toggled on
            if getattr(s, "hidden", False) and not show_hidden:
                return False

            if not self._filter_text:
                return True

            needle = self._filter_text
            haystack = " ".join([
                s.name.lower(),
                s.project_path.lower(),
                s.editor.lower(),
            ] + [t.lower() for t in getattr(s, "tags", [])])
            return needle in haystack

        if isinstance(row, GroupRow):
            g = row.group
            # In active-only mode, hide all group headers (sessions appear flat)
            if active_only:
                return False
            # Hide hidden groups
            if getattr(g, "hidden", False) and not show_hidden:
                return False
            return True

        return True



    # ──────────────────────────────────────────────────────────────────
    # Public API — full rebuild
    # ──────────────────────────────────────────────────────────────────

    def rebuild(self, sessions: List[Session], groups: List[Group]):
        """
        Clear and repopulate the listbox from scratch.

        Layout:
          Top-level items (groups + ungrouped sessions) sorted by (order, name).
          Grouped sessions are nested immediately below their group header.
        """
        self.clear()

        # --- Bucket sessions ---
        ungrouped: List[Session] = []
        by_group: dict[str, List[Session]] = {}
        for s in sessions:
            if s.group_id:
                by_group.setdefault(s.group_id, []).append(s)
            else:
                ungrouped.append(s)

        # Sort within each group
        for gid in by_group:
            by_group[gid].sort(key=lambda s: (s.order, s.name.lower()))
        ungrouped.sort(key=lambda s: (s.order, s.name.lower()))

        # --- Build top-level items list ---
        top: list = []
        for g in groups:
            top.append(("group", g))
        for s in ungrouped:
            top.append(("session", s))
        top.sort(key=lambda item: (item[1].order, item[1].name.lower()))

        # --- Populate listbox ---
        for item_type, item in top:
            if item_type == "group":
                group = item
                gsessions = by_group.get(group.id, [])
                grow = self._add_group_row(group, len(gsessions))
                for s in gsessions:
                    srow = self._add_session_row(s, indent=True)
                    if group.collapsed:
                        srow.set_no_show_all(True)
                        srow.hide()
            else:
                self._add_session_row(item, indent=False)

        self.show_all()
        self.listbox.invalidate_filter()
        self._update_count()

    # ──────────────────────────────────────────────────────────────────
    # Internal row construction helpers
    # ──────────────────────────────────────────────────────────────────

    def _add_session_row(self, session: Session, indent: bool) -> SessionRow:
        row = SessionRow(session, indent=indent)
        row.set_compact_mode(self.compact_btn.get_active())
        self._wire_session_row(row)
        self.listbox.add(row)
        self._rows[session.id] = row
        return row

    def _add_group_row(self, group: Group, session_count: int) -> GroupRow:
        row = GroupRow(group, session_count)
        self._wire_group_row(row)
        self.listbox.add(row)
        self._rows[group.id] = row
        return row

    def _wire_session_row(self, row: SessionRow):
        row.on_start = self.on_start_session
        row.on_stop = self.on_stop_session
        row.on_show_details = self.on_show_details
        row.notes_btn.connect("clicked", lambda _: self.on_open_notes and self.on_open_notes(row.session.id))
        row.plans_btn.connect("clicked", lambda _: self.on_open_plans and self.on_open_plans(row.session.id))
        row.tasks_btn.connect("clicked", lambda _: self.on_open_tasks and self.on_open_tasks(row.session.id))
        self._setup_drag_source(row.drag_handle, row)

    def _wire_group_row(self, row: GroupRow):
        row.on_toggle = self._on_group_toggle
        self._setup_drag_source(row.drag_handle, row)

    def _setup_drag_source(self, handle: Gtk.EventBox, row: Gtk.ListBoxRow):
        """Attach DnD drag-source to a handle EventBox."""
        handle.drag_source_set(
            Gdk.ModifierType.BUTTON1_MASK,
            [_DND_TARGET],
            Gdk.DragAction.MOVE,
        )
        handle.connect("drag-begin",    lambda w, ctx: self._on_drag_begin(row, ctx))
        handle.connect("drag-data-get", lambda w, ctx, sel, i, t: self._on_drag_data_get(row, sel))
        handle.connect("drag-end",      lambda w, ctx: self._on_drag_end())

    # ──────────────────────────────────────────────────────────────────
    # Public API — incremental updates
    # ──────────────────────────────────────────────────────────────────

    def add_session(self, session: Session) -> SessionRow:
        """Append a session row (used after dialog creation)."""
        indent = bool(session.group_id)
        row = self._add_session_row(session, indent=indent)
        # If session belongs to a collapsed group, hide it
        if session.group_id:
            g_row = self._rows.get(session.group_id)
            if isinstance(g_row, GroupRow) and g_row.group.collapsed:
                row.hide()
            # Update group's count label
            self._refresh_group_count(session.group_id)
        self._update_count()
        row.show_all() if not (session.group_id and self._is_group_collapsed(session.group_id)) else None
        return row

    def remove_session(self, session_id: str):
        row = self._rows.pop(session_id, None)
        if row:
            group_id = None
            if isinstance(row, SessionRow):
                group_id = row.session.group_id
            self.listbox.remove(row)
            if group_id:
                self._refresh_group_count(group_id)
            self._update_count()

    def update_session(self, session: Session):
        row = self._rows.get(session.id)
        if isinstance(row, SessionRow):
            row.update_session(session)

    def update_status(self, session_id: str, state: str):
        row = self._rows.get(session_id)
        if isinstance(row, SessionRow) and row.get_parent():
            row.update_status(state)

    def add_group(self, group: Group, session_count: int = 0) -> GroupRow:
        row = self._add_group_row(group, session_count)
        row.show_all()
        return row

    def remove_group(self, group_id: str):
        row = self._rows.pop(group_id, None)
        if row:
            self.listbox.remove(row)

    def update_group(self, group: Group, session_count: Optional[int] = None):
        row = self._rows.get(group.id)
        if isinstance(row, GroupRow):
            row.update_group(group)
            if session_count is not None:
                row.update_count(session_count)

    def set_group_sessions_visible(self, group_id: str, visible: bool):
        """Request a filter update to show/hide session rows in group."""
        self.listbox.invalidate_filter()

    def select_session(self, session_id: str):
        row = self._rows.get(session_id)
        if row:
            self.listbox.select_row(row)

    def get_selected_session_id(self) -> Optional[str]:
        row = self.listbox.get_selected_row()
        if isinstance(row, SessionRow):
            return row.session.id
        return None

    def get_row(self, item_id: str) -> Optional[Gtk.ListBoxRow]:
        return self._rows.get(item_id)

    def clear(self):
        for child in list(self.listbox.get_children()):
            self.listbox.remove(child)
        self._rows.clear()
        self._update_count()

    def set_session_enabled(self, session_id: str, enabled: bool):
        row = self._rows.get(session_id)
        if isinstance(row, SessionRow):
            row.set_enabled(enabled)

    # ──────────────────────────────────────────────────────────────────
    # Group toggle
    # ──────────────────────────────────────────────────────────────────

    def _on_group_toggle(self, group_id: str, collapsed: bool):
        self.set_group_sessions_visible(group_id, not collapsed)
        if self.on_group_toggle:
            self.on_group_toggle(group_id, collapsed)

    def _is_group_collapsed(self, group_id: str) -> bool:
        row = self._rows.get(group_id)
        return isinstance(row, GroupRow) and row.group.collapsed

    def _refresh_group_count(self, group_id: str):
        count = sum(
            1 for r in self._rows.values()
            if isinstance(r, SessionRow) and r.session.group_id == group_id
        )
        row = self._rows.get(group_id)
        if isinstance(row, GroupRow):
            row.update_count(count)

    # ──────────────────────────────────────────────────────────────────
    # Drag-and-drop
    # ──────────────────────────────────────────────────────────────────

    def _on_drag_begin(self, row: Gtk.ListBoxRow, ctx):
        self._drag_row = row
        row.get_style_context().add_class("row-dragging")
        # Use a simple generic drag icon
        Gtk.drag_set_icon_name(ctx, "emblem-symbolic", 0, 0)

    def _on_drag_data_get(self, row: Gtk.ListBoxRow, selection):
        row_type = getattr(row, "row_type", "session")
        row_id = (row.session.id if row_type == "session" else row.group.id)
        payload = f"{row_type}:{row_id}".encode("utf-8")
        selection.set(selection.get_target(), 8, payload)

    def _on_drag_end(self):
        if self._drag_row:
            self._drag_row.get_style_context().remove_class("row-dragging")
        self._drag_row = None
        self._clear_dnd_highlight()

    def _on_drag_motion(self, widget, ctx, x, y, timestamp):
        target_row = widget.get_row_at_y(y)

        if self._drag_highlight_row and self._drag_highlight_row is not target_row:
            self._clear_dnd_highlight()

        if target_row and target_row is not self._drag_row:
            alloc = target_row.get_allocation()
            sc = target_row.get_style_context()
            if y < alloc.y + alloc.height // 2:
                sc.remove_class("dnd-drop-below")
                sc.add_class("dnd-drop-above")
            else:
                sc.remove_class("dnd-drop-above")
                sc.add_class("dnd-drop-below")
            self._drag_highlight_row = target_row

        Gdk.drag_status(ctx, Gdk.DragAction.MOVE, timestamp)
        return True

    def _on_drag_leave(self, widget, ctx, timestamp):
        self._clear_dnd_highlight()

    def _clear_dnd_highlight(self):
        if self._drag_highlight_row:
            sc = self._drag_highlight_row.get_style_context()
            sc.remove_class("dnd-drop-above")
            sc.remove_class("dnd-drop-below")
            self._drag_highlight_row = None

    def _on_drag_drop(self, widget, ctx, x, y, timestamp):
        """Handle an internal same-app drop without requesting selection data."""
        success = self._perform_drop(widget, y)
        self._clear_dnd_highlight()
        Gtk.drag_finish(ctx, success, success, timestamp)
        return True

    def _perform_drop(self, widget, y: int) -> bool:
        """Validate a drop, reorder rows, and notify the app."""
        if not self._drag_row:
            return False

        children = widget.get_children()
        target_row = widget.get_row_at_y(y)
        if target_row is None or target_row is self._drag_row:
            return False

        drag_rows = self._get_drag_rows(children)
        if target_row in drag_rows:
            return False

        alloc = target_row.get_allocation()
        drop_above = y < alloc.y + alloc.height // 2

        src_type = getattr(self._drag_row, "row_type", "session")
        tgt_type = getattr(target_row, "row_type", "session")

        src_group_id = (self._drag_row.session.group_id
                        if src_type == "session" else None)
        tgt_group_id = (target_row.session.group_id
                        if tgt_type == "session" else None)

        # ---- Validate the drop ----
        # Groups may move among any top-level position.
        # Ungrouped sessions stay ungrouped (same level, not inside a group).
        # Sessions in a group stay within that group.
        valid = False
        if src_type == "group":
            # Groups may only move among top-level items.
            valid = tgt_group_id is None
        elif src_type == "session":
            if src_group_id is None:
                # Ungrouped: can drop near other ungrouped or top-level items
                valid = tgt_group_id is None
            else:
                # In a group: can only reorder within the same group
                valid = (tgt_group_id == src_group_id or
                         (tgt_type == "group" and target_row.group.id == src_group_id))

        if not valid:
            return False

        target_index = children.index(target_row)
        source_indexes = [children.index(row) for row in drag_rows]

        if src_type == "group":
            if tgt_type == "group" and not drop_above:
                new_index = self._get_group_end_index(children, target_row.group.id) + 1
            else:
                new_index = target_index if drop_above else target_index + 1
        elif src_group_id is not None and tgt_type == "group":
            # Dropping on a group header means move to the top of that group,
            # directly beneath the header.
            new_index = target_index + 1
        else:
            new_index = target_index if drop_above else target_index + 1

        new_index -= sum(1 for idx in source_indexes if idx < new_index)

        # ---- Perform the move ----
        for row in drag_rows:
            widget.remove(row)
        for offset, row in enumerate(drag_rows):
            widget.insert(row, new_index + offset)

        widget.select_row(self._drag_row)

        self._emit_reorder()
        return True

    def _get_drag_rows(self, children: list[Gtk.ListBoxRow]) -> list[Gtk.ListBoxRow]:
        """Return the row or contiguous block being moved."""
        if getattr(self._drag_row, "row_type", "session") != "group":
            return [self._drag_row]

        group_id = self._drag_row.group.id
        return [
            child for child in children
            if child is self._drag_row or
            (isinstance(child, SessionRow) and child.session.group_id == group_id)
        ]

    @staticmethod
    def _get_group_end_index(children: list[Gtk.ListBoxRow], group_id: str) -> int:
        """Return the final list index occupied by a group block."""
        end_index = -1
        for index, child in enumerate(children):
            if getattr(child, "row_type", "session") == "group" and child.group.id == group_id:
                end_index = index
            elif isinstance(child, SessionRow) and child.session.group_id == group_id:
                end_index = index
        return end_index

    def _emit_reorder(self):
        """Compute order values from current listbox positions and fire on_reorder."""
        if not self.on_reorder:
            return

        children = self.listbox.get_children()
        order_updates: list[tuple] = []

        top_order = 0
        group_session_order: dict[str, int] = {}

        for child in children:
            if not child.get_visible():
                continue
            rt = getattr(child, "row_type", "session")
            if rt == "group":
                order_updates.append(("group", child.group.id, top_order))
                group_session_order[child.group.id] = 0
                top_order += 1
            elif rt == "session":
                gid = child.session.group_id
                if gid is None:
                    order_updates.append(("session", child.session.id, top_order))
                    top_order += 1
                else:
                    idx = group_session_order.get(gid, 0)
                    order_updates.append(("session", child.session.id, idx))
                    group_session_order[gid] = idx + 1

        self.on_reorder(order_updates)

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    def _update_count(self):
        count = sum(1 for r in self._rows.values() if isinstance(r, SessionRow))
        self.count_label.set_text(str(count))
