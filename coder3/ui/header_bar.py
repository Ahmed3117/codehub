"""Header bar — application title bar with action buttons."""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib


class HeaderBar(Gtk.HeaderBar):
    """Custom header bar with session actions."""

    def __init__(self):
        super().__init__()

        self.set_show_close_button(True)
        self.set_title("Coder3")
        self.set_subtitle("VS Code Session Manager")
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

        self.kill_editor_btn = Gtk.Button(label="Kill Editor")
        self.kill_editor_btn.set_tooltip_text("Kill all processes for a selected editor")
        self.kill_editor_btn.get_style_context().add_class("destructive-action")
        self.pack_start(self.kill_editor_btn)

        # ── Right side ───────────────────────────────────────────────
        menu_btn = Gtk.MenuButton()
        menu_icon = Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON)
        menu_btn.set_image(menu_icon)
        menu_btn.set_tooltip_text("Menu")

        menu = Gtk.Menu()

        about_item = Gtk.MenuItem(label="About Coder3")
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

        # Callbacks
        self.on_about = None
        self.on_quit = None
        self.on_sidebar_toggle = None
        self.on_kill_editor_processes = None
        self.on_general_notes = None

        self.sidebar_toggle_btn.connect("clicked", self._on_sidebar_toggle)
        self.kill_editor_btn.connect("clicked", self._on_kill_editor_processes)

    def set_session_info(self, name: str, state: str = ""):
        """Update subtitle with active session info."""
        if name:
            subtitle = f"● {name}"
            if state:
                subtitle += f"  —  {state}"
            self.set_subtitle(subtitle)
        else:
            self.set_subtitle("VS Code Session Manager")

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
