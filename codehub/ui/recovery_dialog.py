import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango

class RecoveryDialog(Gtk.Dialog):
    """Dialog to select an unmanaged window to attempt re-embedding."""

    def __init__(self, parent, target_name: str, candidates: list[tuple[int, str]]):
        super().__init__(
            title="🧲 Attempt Re-embed",
            transient_for=parent,
            modal=True,
            use_header_bar=True
        )
        self.set_default_size(500, 350)
        self.selected_xid = None

        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "☠ Kill & Restart", Gtk.ResponseType.CLOSE,
            "Attach Window", Gtk.ResponseType.OK
        )
        
        # Style the attach button
        attach_btn = self.get_widget_for_response(Gtk.ResponseType.OK)
        attach_btn.get_style_context().add_class("suggested-action")

        content = self.get_content_area()
        content.set_spacing(15)
        content.set_margin_start(20)
        content.set_margin_end(20)
        content.set_margin_top(20)
        content.set_margin_bottom(20)

        lbl = Gtk.Label(xalign=0)
        lbl.set_markup(f"Select a window to attach to <b>{target_name}</b>:")
        content.pack_start(lbl, False, False, 0)

        # Scrolled list of windows
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_shadow_type(Gtk.ShadowType.IN)
        scrolled.set_vexpand(True)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        
        for xid, title in candidates:
            row = Gtk.ListBoxRow()
            row.xid = xid
            
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            hbox.set_margin_start(10)
            hbox.set_margin_end(10)
            hbox.set_margin_top(8)
            hbox.set_margin_bottom(8)
            
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            
            title_lbl = Gtk.Label(label=title or "(No Title)", xalign=0)
            title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            title_lbl.get_style_context().add_class("session-name")
            vbox.pack_start(title_lbl, False, False, 0)
            
            xid_lbl = Gtk.Label(label=f"XID: {xid}", xalign=0)
            xid_lbl.get_style_context().add_class("session-path")
            xid_lbl.set_opacity(0.7)
            vbox.pack_start(xid_lbl, False, False, 0)
            
            hbox.pack_start(vbox, True, True, 0)
            
            row.add(hbox)
            self.listbox.add(row)

        if candidates:
            self.listbox.select_row(self.listbox.get_row_at_index(0))

        scrolled.add(self.listbox)
        content.pack_start(scrolled, True, True, 0)

        info_lbl = Gtk.Label(xalign=0)
        info_lbl.set_markup("<small><i>Note: Only windows matching the expected WM_CLASS are shown.</i></small>")
        info_lbl.set_opacity(0.6)
        content.pack_start(info_lbl, False, False, 0)

        self.show_all()

    def get_selected_xid(self) -> int:
        row = self.listbox.get_selected_row()
        return row.xid if row else None
