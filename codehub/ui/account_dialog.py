"""Account chooser and account management dialogs."""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


RESPONSE_CREATE = 101
RESPONSE_EDIT = 102
RESPONSE_DELETE = 103


class AccountChooserDialog(Gtk.Dialog):
    """Dialog for selecting an account and entering its password."""

    def __init__(self, parent, accounts, last_account_id=None):
        super().__init__(
            title="Choose Account",
            transient_for=parent,
            modal=True,
            use_header_bar=True,
        )
        self.accounts = list(accounts)
        self.set_default_size(380, -1)
        self.add_buttons(
            "Create Account", RESPONSE_CREATE,
            "Edit", RESPONSE_EDIT,
            "Delete", RESPONSE_DELETE,
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Login", Gtk.ResponseType.OK,
        )
        self.set_default_response(Gtk.ResponseType.OK)

        content = self.get_content_area()
        content.set_spacing(10)
        content.set_margin_start(18)
        content.set_margin_end(18)
        content.set_margin_top(14)
        content.set_margin_bottom(14)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        content.pack_start(grid, True, True, 0)

        grid.attach(Gtk.Label(label="Account", xalign=0), 0, 0, 1, 1)
        self.account_combo = Gtk.ComboBoxText()
        for account in self.accounts:
            self.account_combo.append(account.id, account.name)
        self.account_combo.set_hexpand(True)
        grid.attach(self.account_combo, 1, 0, 1, 1)

        active_id = last_account_id if any(a.id == last_account_id for a in self.accounts) else None
        if active_id:
            self.account_combo.set_active_id(active_id)
        elif self.accounts:
            self.account_combo.set_active(0)

        grid.attach(Gtk.Label(label="Password", xalign=0), 0, 1, 1, 1)
        self.password_entry = Gtk.Entry()
        self.password_entry.set_visibility(False)
        self.password_entry.set_activates_default(True)
        grid.attach(self.password_entry, 1, 1, 1, 1)

        self.error_label = Gtk.Label(xalign=0)
        self.error_label.get_style_context().add_class("error-label")
        self.error_label.set_no_show_all(True)
        content.pack_start(self.error_label, False, False, 0)

        self.show_all()
        self.error_label.hide()

    def get_selected_account_id(self):
        return self.account_combo.get_active_id()

    def get_password(self):
        return self.password_entry.get_text()

    def set_error(self, message: str):
        self.error_label.set_text(message)
        self.error_label.show()


class AccountFormDialog(Gtk.Dialog):
    """Create or update an account."""

    def __init__(self, parent, title="Account", account=None, require_password=True):
        super().__init__(
            title=title,
            transient_for=parent,
            modal=True,
            use_header_bar=True,
        )
        self.require_password = require_password
        self.set_default_size(380, -1)
        self.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        content = self.get_content_area()
        content.set_spacing(10)
        content.set_margin_start(18)
        content.set_margin_end(18)
        content.set_margin_top(14)
        content.set_margin_bottom(14)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        content.pack_start(grid, True, True, 0)

        grid.attach(Gtk.Label(label="Name", xalign=0), 0, 0, 1, 1)
        self.name_entry = Gtk.Entry()
        self.name_entry.set_text(account.name if account else "")
        self.name_entry.set_activates_default(True)
        grid.attach(self.name_entry, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="Password", xalign=0), 0, 1, 1, 1)
        self.password_entry = Gtk.Entry()
        self.password_entry.set_visibility(False)
        self.password_entry.set_activates_default(True)
        if not require_password:
            self.password_entry.set_placeholder_text("Leave empty to keep current password")
        grid.attach(self.password_entry, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="Confirm", xalign=0), 0, 2, 1, 1)
        self.confirm_entry = Gtk.Entry()
        self.confirm_entry.set_visibility(False)
        self.confirm_entry.set_activates_default(True)
        grid.attach(self.confirm_entry, 1, 2, 1, 1)

        self.error_label = Gtk.Label(xalign=0)
        self.error_label.get_style_context().add_class("error-label")
        self.error_label.set_no_show_all(True)
        content.pack_start(self.error_label, False, False, 0)

        self.show_all()
        self.error_label.hide()

    def get_values(self):
        password = self.password_entry.get_text()
        confirm = self.confirm_entry.get_text()
        if password != confirm:
            raise ValueError("Passwords do not match.")
        if self.require_password or password:
            if not password:
                raise ValueError("Password is required.")
        return self.name_entry.get_text().strip(), password or None

    def set_error(self, message: str):
        self.error_label.set_text(message)
        self.error_label.show()


class AccountDeleteDialog(Gtk.Dialog):
    """Confirm account deletion with password."""

    def __init__(self, parent, account_name: str):
        super().__init__(
            title="Delete Account",
            transient_for=parent,
            modal=True,
            use_header_bar=True,
        )
        self.set_default_size(420, -1)
        self.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Delete", Gtk.ResponseType.OK)

        delete_btn = self.get_widget_for_response(Gtk.ResponseType.OK)
        if delete_btn:
            delete_btn.get_style_context().add_class("destructive-action")

        content = self.get_content_area()
        content.set_spacing(10)
        content.set_margin_start(18)
        content.set_margin_end(18)
        content.set_margin_top(14)
        content.set_margin_bottom(14)

        warning = Gtk.Label(
            label=(
                f"Delete '{account_name}' and all of its sessions, plans, tasks, "
                "notes, groups, settings, and modes?"
            ),
            xalign=0,
        )
        warning.set_line_wrap(True)
        content.pack_start(warning, False, False, 0)

        self.password_entry = Gtk.Entry()
        self.password_entry.set_visibility(False)
        self.password_entry.set_placeholder_text("Account password")
        self.password_entry.set_activates_default(True)
        content.pack_start(self.password_entry, False, False, 0)

        self.error_label = Gtk.Label(xalign=0)
        self.error_label.get_style_context().add_class("error-label")
        self.error_label.set_no_show_all(True)
        content.pack_start(self.error_label, False, False, 0)

        self.show_all()
        self.error_label.hide()

    def get_password(self):
        return self.password_entry.get_text()

    def set_error(self, message: str):
        self.error_label.set_text(message)
        self.error_label.show()
