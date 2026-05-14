"""Add App dialog — lets the user add an application to a session workspace."""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from codehub.session_app import SessionApp
from codehub.utils.constants import APPS, EDITORS


class AddAppDialog(Gtk.Dialog):
    """Dialog for adding a new application to a session workspace."""

    def __init__(self, parent, session_id: str):
        super().__init__(
            title="Add Application",
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        add_btn = self.add_button("Add", Gtk.ResponseType.OK)
        add_btn.get_style_context().add_class("suggested-action")

        self.set_default_size(460, -1)
        self.set_resizable(False)

        self._session_id = session_id

        content = self.get_content_area()
        content.get_style_context().add_class("dialog-content")
        content.set_spacing(16)

        # ── App selection ────────────────────────────────────────────
        app_label = Gtk.Label(label="Application", xalign=0)
        app_label.set_margin_bottom(4)
        content.pack_start(app_label, False, False, 0)

        # Merge APPS and EDITORS for selection
        self._all_apps = APPS.copy()
        for k, v in EDITORS.items():
            if k not in self._all_apps:
                self._all_apps[k] = v

        self._app_keys = [k for k in self._all_apps.keys() if k != "custom"]
        self._app_keys.sort() # Sort alphabetically
        self._app_keys.append("custom")

        self.app_combo = Gtk.ComboBoxText()
        self.app_combo.get_style_context().add_class("app-select-combo")
        for key in self._app_keys:
            info = self._all_apps[key]
            icon = info.get("icon", "🔧")
            self.app_combo.append(key, f"{icon}  {info['name']}")

        self.app_combo.set_active(0)
        self.app_combo.connect("changed", self._on_app_changed)
        content.pack_start(self.app_combo, False, False, 0)

        # Separator
        content.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 8)

        # ── Custom command row (shown only for "custom") ─────────────
        self._custom_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._custom_row.get_style_context().add_class("custom-row-box")

        title_lbl = Gtk.Label(label="Custom Application Configuration".upper(), xalign=0)
        title_lbl.get_style_context().add_class("custom-row-title")
        self._custom_row.pack_start(title_lbl, False, False, 0)

        cmd_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        cmd_label = Gtk.Label(label="Command or Executable Path", xalign=0)
        cmd_vbox.pack_start(cmd_label, False, False, 0)

        self.custom_cmd_entry = Gtk.Entry()
        self.custom_cmd_entry.set_placeholder_text("e.g. /usr/bin/my-app  or  my-tool")
        cmd_vbox.pack_start(self.custom_cmd_entry, False, False, 0)
        self._custom_row.pack_start(cmd_vbox, False, False, 0)

        # Browse buttons row
        browse_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        app_browse_btn = Gtk.Button(label="📦  Browse Apps")
        app_browse_btn.set_tooltip_text("Select from installed system applications")
        app_browse_btn.connect("clicked", self._on_browse_system_apps)
        browse_hbox.pack_start(app_browse_btn, True, True, 0)

        self.file_chooser = Gtk.FileChooserButton(title="Select Executable", action=Gtk.FileChooserAction.OPEN)
        self.file_chooser.connect("file-set", self._on_file_set)
        browse_hbox.pack_start(self.file_chooser, True, True, 0)
        
        self._custom_row.pack_start(browse_hbox, False, False, 4)

        wm_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        wm_label = Gtk.Label(label="Window Class (WM_CLASS)", xalign=0)
        wm_vbox.pack_start(wm_label, False, False, 0)

        self.custom_wm_entry = Gtk.Entry()
        self.custom_wm_entry.set_placeholder_text("Optional: e.g. my-app")
        wm_vbox.pack_start(self.custom_wm_entry, False, False, 0)
        self._custom_row.pack_start(wm_vbox, False, False, 0)

        content.pack_start(self._custom_row, False, False, 0)
        self._custom_row.set_visible(False)
        self._custom_row.set_no_show_all(True)

        # ── Display name override ────────────────────────────────────
        name_label = Gtk.Label(label="Display Name (optional)", xalign=0)
        name_label.set_margin_top(8)
        name_label.set_margin_bottom(4)
        content.pack_start(name_label, False, False, 0)

        self.name_entry = Gtk.Entry()
        self.name_entry.set_placeholder_text("e.g. My Custom Terminal")
        content.pack_start(self.name_entry, False, False, 0)

        self.show_all()
        self._custom_row.hide()

    def _on_app_changed(self, combo):
        active = combo.get_active_id()
        if active == "custom":
            self._custom_row.show_all()
        else:
            self._custom_row.hide()

    def _on_browse_system_apps(self, button):
        """Open a system app chooser dialog to pick an installed application."""
        dialog = Gtk.AppChooserDialog(
            transient_for=self.get_toplevel(),
            content_type="application/octet-stream",
        )
        dialog.set_heading("Select an application to add to this session")
        # Show all installed apps, not just those associated with a content type
        widget = dialog.get_widget()
        widget.set_show_all(True)
        widget.set_show_default(False)
        widget.set_show_recommended(True)
        widget.set_show_fallback(True)
        widget.set_show_other(True)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            app_info = dialog.get_app_info()
            if app_info:
                cmd = app_info.get_commandline() or ""
                # Clean desktop-entry field codes (%u, %U, %f, %F, %i, %c, %k, etc.)
                import re
                cmd = re.sub(r'\s+%[a-zA-Z]', '', cmd).strip()
                self.custom_cmd_entry.set_text(cmd)
                name = app_info.get_name() or ""
                if name and not self.name_entry.get_text():
                    self.name_entry.set_text(name)
                if name and not self.custom_wm_entry.get_text():
                    self.custom_wm_entry.set_text(name.lower().replace(" ", "-"))
        dialog.destroy()

    def _on_file_set(self, chooser):
        filename = chooser.get_filename()
        if filename:
            self.custom_cmd_entry.set_text(filename)
            import os
            name = os.path.basename(filename)
            if not self.name_entry.get_text():
                self.name_entry.set_text(name)
            if not self.custom_wm_entry.get_text():
                self.custom_wm_entry.set_text(name.lower())

    def get_session_app(self) -> SessionApp:
        """Build and return a SessionApp from dialog inputs."""
        app_type = self.app_combo.get_active_id() or "custom"
        app_info = self._all_apps.get(app_type, self._all_apps["custom"])

        custom_cmd = ""
        custom_wm = ""
        if app_type == "custom":
            custom_cmd = self.custom_cmd_entry.get_text().strip()
            custom_wm = self.custom_wm_entry.get_text().strip()

        display_name = self.name_entry.get_text().strip()
        if not display_name:
            if app_type == "custom" and custom_cmd:
                import os
                display_name = os.path.basename(custom_cmd.split()[0])
            else:
                display_name = app_info["name"]

        return SessionApp(
            session_id=self._session_id,
            app_type=app_type,
            custom_command=custom_cmd,
            custom_wm_class=custom_wm,
            display_name=display_name,
            icon=app_info.get("icon", "🔧"),
        )

    def validate(self) -> tuple[bool, str]:
        """Validate the dialog inputs."""
        app_type = self.app_combo.get_active_id()
        if app_type == "custom":
            cmd = self.custom_cmd_entry.get_text().strip()
            if not cmd:
                return False, "Custom command is required."
        return True, ""


class RenameAppDialog(Gtk.Dialog):
    """Small dialog for renaming an existing workspace app tab."""

    def __init__(self, parent, current_name: str):
        super().__init__(
            title="Rename App",
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        save_btn = self.add_button("Save", Gtk.ResponseType.OK)
        save_btn.get_style_context().add_class("suggested-action")
        self.set_default_size(340, -1)
        self.set_resizable(False)
        self.set_default_response(Gtk.ResponseType.OK)

        content = self.get_content_area()
        content.set_spacing(10)
        content.set_margin_start(18)
        content.set_margin_end(18)
        content.set_margin_top(14)
        content.set_margin_bottom(14)

        label = Gtk.Label(label="Display Name", xalign=0)
        content.pack_start(label, False, False, 0)

        self.name_entry = Gtk.Entry()
        self.name_entry.set_text(current_name or "")
        self.name_entry.set_activates_default(True)
        self.name_entry.select_region(0, -1)
        content.pack_start(self.name_entry, False, False, 0)

        self.error_label = Gtk.Label(xalign=0)
        self.error_label.get_style_context().add_class("error-label")
        self.error_label.set_no_show_all(True)
        content.pack_start(self.error_label, False, False, 0)

        self.show_all()
        self.error_label.hide()

    def get_name(self) -> str:
        name = self.name_entry.get_text().strip()
        if not name:
            raise ValueError("Name is required.")
        if len(name) > 40:
            raise ValueError("Name must be 40 characters or less.")
        return name

    def set_error(self, message: str):
        self.error_label.set_text(message)
        self.error_label.show()
