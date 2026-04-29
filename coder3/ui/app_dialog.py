"""Add App dialog — lets the user add an application to a session workspace."""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from coder3.session_app import SessionApp
from coder3.utils.constants import APPS


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

        self._app_keys = [k for k in APPS.keys() if k != "custom"]
        self._app_keys.append("custom")

        self.app_combo = Gtk.ComboBoxText()
        for key in self._app_keys:
            info = APPS[key]
            icon = info.get("icon", "🔧")
            self.app_combo.append(key, f"{icon}  {info['name']}")

        self.app_combo.set_active(0)
        self.app_combo.connect("changed", self._on_app_changed)
        content.pack_start(self.app_combo, False, False, 0)

        # ── Custom command row (shown only for "custom") ─────────────
        self._custom_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        cmd_label = Gtk.Label(label="Custom Command", xalign=0)
        cmd_label.set_margin_bottom(4)
        self._custom_row.pack_start(cmd_label, False, False, 0)

        self.custom_cmd_entry = Gtk.Entry()
        self.custom_cmd_entry.set_placeholder_text("e.g. /usr/bin/my-app  or  my-tool")
        self._custom_row.pack_start(self.custom_cmd_entry, False, False, 0)

        wm_label = Gtk.Label(label="WM_CLASS (for window discovery, optional)", xalign=0)
        wm_label.set_margin_top(4)
        wm_label.set_margin_bottom(4)
        self._custom_row.pack_start(wm_label, False, False, 0)

        self.custom_wm_entry = Gtk.Entry()
        self.custom_wm_entry.set_placeholder_text("e.g. my-app (run xprop to find)")
        self._custom_row.pack_start(self.custom_wm_entry, False, False, 0)

        content.pack_start(self._custom_row, False, False, 0)
        self._custom_row.set_visible(False)
        self._custom_row.set_no_show_all(True)

        # ── Display name override ────────────────────────────────────
        name_label = Gtk.Label(label="Display Name (optional)", xalign=0)
        name_label.set_margin_top(8)
        name_label.set_margin_bottom(4)
        content.pack_start(name_label, False, False, 0)

        self.name_entry = Gtk.Entry()
        self.name_entry.set_placeholder_text("Leave empty to use default name")
        content.pack_start(self.name_entry, False, False, 0)

        self.show_all()
        self._custom_row.hide()

    def _on_app_changed(self, combo):
        active = combo.get_active_id()
        if active == "custom":
            self._custom_row.show_all()
        else:
            self._custom_row.hide()

    def get_session_app(self) -> SessionApp:
        """Build and return a SessionApp from dialog inputs."""
        app_type = self.app_combo.get_active_id() or "custom"
        app_info = APPS.get(app_type, APPS["custom"])

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
