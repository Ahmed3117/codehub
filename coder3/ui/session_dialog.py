"""Session dialog — Add/Edit session dialog."""

import os

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from coder3.session_registry import Session
from coder3.group_registry import Group
from coder3.utils.constants import STATE_IDLE, EDITORS


# Preset accent colors for sessions
ACCENT_COLORS = [
    "#7aa2f7",  # Blue
    "#9ece6a",  # Green
    "#f7768e",  # Red/Pink
    "#e0af68",  # Yellow/Orange
    "#7dcfff",  # Cyan
    "#bb9af7",  # Purple
    "#ff9e64",  # Orange
    "#73daca",  # Teal
    "#2ac3de",  # Light blue
    "#c0caf5",  # Light gray
]


class SessionDialog(Gtk.Dialog):
    """Dialog for creating or editing a session."""

    def __init__(self, parent, session=None, groups=None):
        """
        Args:
            parent: Parent window
            session: Existing session to edit, or None for new session
            groups: List of Group objects available for assignment (may be empty/None)
        """
        is_edit = session is not None
        title = "Edit Session" if is_edit else "New Session"

        super().__init__(
            title=title,
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        save_btn = self.add_button("Save" if is_edit else "Create", Gtk.ResponseType.OK)
        save_btn.get_style_context().add_class("suggested-action")

        self.set_default_size(520, -1)
        self.set_resizable(False)

        # Build form
        content = self.get_content_area()
        content.get_style_context().add_class("dialog-content")
        content.set_spacing(16)

        # ── Session name ─────────────────────────────────────────────
        name_label = Gtk.Label(label="Session Name", xalign=0)
        name_label.set_margin_bottom(4)
        content.pack_start(name_label, False, False, 0)

        self.name_entry = Gtk.Entry()
        self.name_entry.set_placeholder_text("My Project")
        if session:
            self.name_entry.set_text(session.name)
        self.name_entry.connect("activate", lambda w: self.response(Gtk.ResponseType.OK))
        content.pack_start(self.name_entry, False, False, 0)

        # ── Project path ─────────────────────────────────────────────
        path_label = Gtk.Label(label="Project Path", xalign=0)
        path_label.set_margin_top(8)
        path_label.set_margin_bottom(4)
        content.pack_start(path_label, False, False, 0)

        path_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.path_entry = Gtk.Entry()
        self.path_entry.set_placeholder_text("/path/to/project")
        self.path_entry.set_hexpand(True)
        if session:
            self.path_entry.set_text(session.project_path)
        path_box.pack_start(self.path_entry, True, True, 0)

        browse_btn = Gtk.Button(label="Browse")
        browse_btn.connect("clicked", self._on_browse)
        path_box.pack_start(browse_btn, False, False, 0)
        content.pack_start(path_box, False, False, 0)

        # ── Editor selection ─────────────────────────────────────────
        editor_label = Gtk.Label(label="Editor", xalign=0)
        editor_label.set_margin_top(8)
        editor_label.set_margin_bottom(4)
        content.pack_start(editor_label, False, False, 0)

        self._editor_keys = list(EDITORS.keys())  # preserve insertion order

        self.editor_combo = Gtk.ComboBoxText()
        for key in self._editor_keys:
            self.editor_combo.append(key, EDITORS[key]["name"])

        current_editor = session.editor if session else "vscode"
        self.editor_combo.set_active_id(current_editor)
        self.editor_combo.connect("changed", self._on_editor_changed)
        content.pack_start(self.editor_combo, False, False, 0)

        # Custom command row (shown only when editor == "custom")
        self._custom_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        custom_cmd_label = Gtk.Label(label="Custom Editor Command", xalign=0)
        custom_cmd_label.set_margin_bottom(4)
        self._custom_row.pack_start(custom_cmd_label, False, False, 0)

        self.custom_cmd_entry = Gtk.Entry()
        self.custom_cmd_entry.set_placeholder_text("e.g.  /usr/bin/gedit  or  xed")
        if session and session.custom_editor_cmd:
            self.custom_cmd_entry.set_text(session.custom_editor_cmd)
        self._custom_row.pack_start(self.custom_cmd_entry, False, False, 0)

        content.pack_start(self._custom_row, False, False, 0)
        self._custom_row.set_visible(current_editor == "custom")
        self._custom_row.set_no_show_all(True)
        if current_editor == "custom":
            self._custom_row.show_all()

        # ── Group assignment ─────────────────────────────────────────
        self._groups = groups or []
        if self._groups:
            group_label = Gtk.Label(label="Group", xalign=0)
            group_label.set_margin_top(8)
            group_label.set_margin_bottom(4)
            content.pack_start(group_label, False, False, 0)

            self.group_combo = Gtk.ComboBoxText()
            self.group_combo.append("__none__", "No Group")
            for g in self._groups:
                self.group_combo.append(g.id, g.name)

            current_gid = session.group_id if session else None
            self.group_combo.set_active_id(current_gid if current_gid else "__none__")
            content.pack_start(self.group_combo, False, False, 0)
        else:
            self.group_combo = None

        # ── Accent color ─────────────────────────────────────────────
        color_label = Gtk.Label(label="Accent Color", xalign=0)
        color_label.set_margin_top(8)
        color_label.set_margin_bottom(4)
        content.pack_start(color_label, False, False, 0)

        color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.selected_color = session.color if session else ACCENT_COLORS[0]
        self._color_buttons = []

        for color in ACCENT_COLORS:
            btn = Gtk.Button()
            btn.set_size_request(32, 32)
            btn.get_style_context().add_class("color-btn")
            if color == self.selected_color:
                btn.get_style_context().add_class("color-btn-selected")

            css = Gtk.CssProvider()
            css.load_from_data(f"""
                .color-{color.replace('#', '')} {{
                    background-color: {color};
                }}
            """.encode())
            btn.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            btn.get_style_context().add_class(f"color-{color.replace('#', '')}")
            btn.connect("clicked", self._on_color_selected, color)
            color_box.pack_start(btn, False, False, 0)
            self._color_buttons.append((btn, color))

        content.pack_start(color_box, False, False, 0)

        # ── Extra VS Code arguments ───────────────────────────────────
        args_label = Gtk.Label(label="Extra Editor Arguments (optional)", xalign=0)
        args_label.set_margin_top(8)
        args_label.set_margin_bottom(4)
        content.pack_start(args_label, False, False, 0)

        self.args_entry = Gtk.Entry()
        self.args_entry.set_placeholder_text("e.g. --disable-extensions --profile=myprofile")
        if session and session.vscode_args:
            self.args_entry.set_text(" ".join(session.vscode_args))
        content.pack_start(self.args_entry, False, False, 0)

        self._session = session
        self.show_all()
        # Keep custom row hidden after show_all if not needed
        if current_editor != "custom":
            self._custom_row.hide()

    def _on_editor_changed(self, combo):
        active = combo.get_active_id()
        if active == "custom":
            self._custom_row.show_all()
        else:
            self._custom_row.hide()

    def _on_browse(self, button):
        dialog = Gtk.FileChooserDialog(
            title="Select Project Folder",
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Select", Gtk.ResponseType.OK)

        current = self.path_entry.get_text().strip()
        if current and os.path.isdir(current):
            dialog.set_current_folder(current)
        else:
            dialog.set_current_folder(os.path.expanduser("~"))

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.path_entry.set_text(dialog.get_filename())
        dialog.destroy()

    def _on_color_selected(self, button, color):
        self.selected_color = color
        for btn, col in self._color_buttons:
            if col == color:
                btn.get_style_context().add_class("color-btn-selected")
            else:
                btn.get_style_context().remove_class("color-btn-selected")

    def get_session(self) -> Session:
        """Build and return the session from dialog inputs."""
        name = self.name_entry.get_text().strip()
        path = self.path_entry.get_text().strip()
        args_text = self.args_entry.get_text().strip()
        args = args_text.split() if args_text else []
        editor = self.editor_combo.get_active_id() or "vscode"
        custom_cmd = self.custom_cmd_entry.get_text().strip() if editor == "custom" else ""

        # Group
        group_id = None
        if self.group_combo:
            gid = self.group_combo.get_active_id()
            group_id = gid if gid and gid != "__none__" else None

        if self._session:
            # Edit mode
            self._session.name = name or "Untitled"
            self._session.project_path = path
            self._session.vscode_args = args
            self._session.color = self.selected_color
            self._session.editor = editor
            self._session.custom_editor_cmd = custom_cmd
            self._session.group_id = group_id
            return self._session
        else:
            import datetime
            return Session(
                name=name or "Untitled",
                project_path=path,
                vscode_args=args,
                color=self.selected_color,
                state=STATE_IDLE,
                editor=editor,
                custom_editor_cmd=custom_cmd,
                group_id=group_id,
                created_at=datetime.datetime.now().isoformat(),
            )

    def validate(self) -> tuple[bool, str]:
        name = self.name_entry.get_text().strip()
        path = self.path_entry.get_text().strip()
        editor = self.editor_combo.get_active_id() or "vscode"

        if not name:
            return False, "Session name is required."
        if not path:
            return False, "Project path is required."
        if not os.path.isdir(path):
            return False, f"Project path does not exist:\n{path}"
        if editor == "custom" and not self.custom_cmd_entry.get_text().strip():
            return False, "Custom editor command is required when 'Custom' is selected."

        return True, ""


# ──────────────────────────────────────────────────────────────────────
# GroupDialog
# ──────────────────────────────────────────────────────────────────────

class GroupDialog(Gtk.Dialog):
    """Dialog for creating or editing a session group."""

    def __init__(self, parent, group: Group = None):
        is_edit = group is not None
        title = "Edit Group" if is_edit else "New Group"

        super().__init__(
            title=title,
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        save_btn = self.add_button("Save" if is_edit else "Create", Gtk.ResponseType.OK)
        save_btn.get_style_context().add_class("suggested-action")

        self.set_default_size(400, -1)
        self.set_resizable(False)

        content = self.get_content_area()
        content.get_style_context().add_class("dialog-content")
        content.set_spacing(16)

        # ── Group name ────────────────────────────────────────────────
        name_label = Gtk.Label(label="Group Name", xalign=0)
        name_label.set_margin_bottom(4)
        content.pack_start(name_label, False, False, 0)

        self.name_entry = Gtk.Entry()
        self.name_entry.set_placeholder_text("My Group")
        if group:
            self.name_entry.set_text(group.name)
        self.name_entry.connect("activate", lambda w: self.response(Gtk.ResponseType.OK))
        content.pack_start(self.name_entry, False, False, 0)

        # ── Accent color ──────────────────────────────────────────────
        color_label = Gtk.Label(label="Accent Color", xalign=0)
        color_label.set_margin_top(8)
        color_label.set_margin_bottom(4)
        content.pack_start(color_label, False, False, 0)

        color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.selected_color = group.color if group else ACCENT_COLORS[0]
        self._color_buttons = []

        for color in ACCENT_COLORS:
            btn = Gtk.Button()
            btn.set_size_request(32, 32)
            btn.get_style_context().add_class("color-btn")
            if color == self.selected_color:
                btn.get_style_context().add_class("color-btn-selected")

            css = Gtk.CssProvider()
            css.load_from_data(f"""
                .grp-color-{color.replace('#', '')} {{
                    background-color: {color};
                }}
            """.encode())
            btn.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            btn.get_style_context().add_class(f"grp-color-{color.replace('#', '')}")
            btn.connect("clicked", self._on_color_selected, color)
            color_box.pack_start(btn, False, False, 0)
            self._color_buttons.append((btn, color))

        content.pack_start(color_box, False, False, 0)

        self._group = group
        self.show_all()

    # ── helpers ───────────────────────────────────────────────────────

    def _on_color_selected(self, button, color):
        self.selected_color = color
        for btn, col in self._color_buttons:
            if col == color:
                btn.get_style_context().add_class("color-btn-selected")
            else:
                btn.get_style_context().remove_class("color-btn-selected")

    def get_group(self) -> Group:
        """Return the Group object with values from the dialog."""
        name = self.name_entry.get_text().strip()
        if self._group:
            self._group.name = name or "Untitled Group"
            self._group.color = self.selected_color
            return self._group
        else:
            return Group(
                name=name or "Untitled Group",
                color=self.selected_color,
            )

    def validate(self) -> tuple[bool, str]:
        name = self.name_entry.get_text().strip()
        if not name:
            return False, "Group name is required."
        return True, ""
