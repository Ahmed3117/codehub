import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib
import typing

if typing.TYPE_CHECKING:
    from codehub.app import CodeHubApp


class CommandRow(Gtk.ListBoxRow):
    def __init__(self, label: str, icon: str, action: typing.Callable, match_text: str):
        super().__init__()
        self.action = action
        self.match_text = match_text.lower()
        self.label_text = label

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        icon_lbl = Gtk.Label(label=icon)
        icon_lbl.get_style_context().add_class("dim-label")
        box.pack_start(icon_lbl, False, False, 0)

        self.name_lbl = Gtk.Label(label=label, xalign=0)
        box.pack_start(self.name_lbl, True, True, 0)

        self.add(box)


class CommandPalette(Gtk.Window):
    """A VSCode-style fuzzy search popup for commands and navigation."""

    def __init__(self, app: 'CodeHubApp'):
        super().__init__(
            title="Command Palette",
            transient_for=app.window,
            modal=True,
            type_hint=Gdk.WindowTypeHint.DIALOG,
        )
        self.app = app
        self.set_default_size(600, 400)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self.set_decorated(False)

        # Style the window to look like a floating palette
        ctx = self.get_style_context()
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            window {
                background-color: @theme_bg_color;
                border: 1px solid @borders;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.5);
            }
            list row:selected {
                background-color: @theme_selected_bg_color;
                color: @theme_selected_fg_color;
                border-radius: 4px;
            }
        """)
        ctx.add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(vbox)

        # Search Entry
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        search_box.set_margin_start(8)
        search_box.set_margin_end(8)
        search_box.set_margin_top(8)
        search_box.set_margin_bottom(8)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_hexpand(True)
        self.search_entry.set_placeholder_text("Search sessions, apps, and commands...")
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("activate", self._on_entry_activate)
        search_box.pack_start(self.search_entry, True, True, 0)

        vbox.pack_start(search_box, False, False, 0)

        # Separator
        vbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        # ListBox inside ScrolledWindow
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-activated", self._on_row_activated)
        self.listbox.set_filter_func(self._filter_func)
        self.listbox.set_margin_start(4)
        self.listbox.set_margin_end(4)
        self.listbox.set_margin_top(4)
        self.listbox.set_margin_bottom(4)

        scroll.add(self.listbox)
        vbox.pack_start(scroll, True, True, 0)

        self.connect("key-press-event", self._on_key_press)
        self.connect("focus-out-event", self._on_focus_out)

        self._populate_commands()
        self.show_all()
        
        # Select first row initially
        self._select_first_visible()

    def _populate_commands(self):
        from codehub.utils.constants import STATE_IDLE, STATE_CLOSED, STATE_FAILED
        
        # 1. Active Session Apps
        active_id = self.app._active_session_id
        if active_id:
            workspace = self.app._workspaces.get(active_id)
            if workspace:
                for app_id, tab in workspace._tabs.items():
                    name = tab.name_label.get_text()
                    self._add_row(f"Go to Tab: {name}", "💻", 
                                  lambda aid=app_id: workspace.select_app(aid), 
                                  f"go switch tab app {name}")

        # 2. Sessions
        for session in self.app.registry.get_all():
            sid = session.id
            is_running = session.state not in (STATE_IDLE, STATE_CLOSED, STATE_FAILED)
            
            # Switch to session
            self._add_row(f"Session: {session.name}", "📁",
                          lambda i=sid: self.app.sidebar.select_session(i),
                          f"switch goto session {session.name}")
            
            if is_running:
                # Stop session
                self._add_row(f"Stop: {session.name}", "⏹",
                              lambda i=sid: self.app._on_stop_session(i),
                              f"stop kill close session {session.name}")
            else:
                # Start session
                self._add_row(f"Start: {session.name}", "▶",
                              lambda i=sid: self.app._on_start_session(i),
                              f"start run open session {session.name}")

        # 3. Global Actions
        self._add_row("New Session", "➕", self.app._on_new_session, "new create session add")
        self._add_row("Toggle Sidebar", "🗂", self.app._on_toggle_sidebar, "toggle hide show sidebar")
        self._add_row("General Notes & Plans", "📋", self.app._on_open_general_notes, "general notes plans")
        self._add_row("Quit CodeHub", "🚪", self.app._on_quit, "quit exit close app")

    def _add_row(self, label, icon, action, match_text):
        row = CommandRow(label, icon, action, match_text)
        self.listbox.add(row)

    def _filter_func(self, row: CommandRow) -> bool:
        search_text = self.search_entry.get_text().lower().strip()
        if not search_text:
            return True
        # Simple substring match (can be improved to fuzzy search later)
        parts = search_text.split()
        return all(p in row.match_text for p in parts)

    def _on_search_changed(self, entry):
        self.listbox.invalidate_filter()
        self._select_first_visible()

    def _select_first_visible(self):
        # Allow GTK to apply the filter first
        GLib.idle_add(self._do_select_first)
        
    def _do_select_first(self):
        for row in self.listbox.get_children():
            if row.get_child_visible():
                self.listbox.select_row(row)
                break
        return False

    def _on_entry_activate(self, entry):
        row = self.listbox.get_selected_row()
        if row:
            self.listbox.emit("row-activated", row)

    def _on_row_activated(self, listbox, row: CommandRow):
        self.destroy()
        # Execute the action after window closes
        GLib.idle_add(row.action)

    def _on_key_press(self, widget, event):
        # Escape closes the palette
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
            
        # Up/Down arrows to navigate listbox while focus is in search entry
        if event.keyval in (Gdk.KEY_Up, Gdk.KEY_Down) and self.search_entry.has_focus():
            self.listbox.grab_focus()
            return False
            
        return False

    def _on_focus_out(self, widget, event):
        # Close if we lose focus (e.g. user clicks outside)
        # We need a small delay to ensure it wasn't just focus moving to a child widget
        GLib.timeout_add(100, self._check_focus)
        return False
        
    def _check_focus(self):
        if not self.is_active() and not self.has_toplevel_focus():
            self.destroy()
        return False
