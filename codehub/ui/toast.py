"""Toast Notification overlay — non-blocking in-app event feedback.

Usage::

    manager = ToastManager(parent_overlay)
    manager.show("Session started", kind="success")
    manager.show("App crashed", kind="error")
    manager.show("Backup saved", kind="info")

``parent_overlay`` must be a Gtk.Overlay that wraps the main content area.
The manager stacks toasts in the bottom-right corner and auto-dismisses them.
"""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Gdk

# Toast kinds and their icon + CSS class
_KINDS = {
    "success": ("✔", "toast-success"),
    "error":   ("✖", "toast-error"),
    "warning": ("⚠", "toast-warning"),
    "info":    ("ℹ", "toast-info"),
    "crash":   ("💥", "toast-crash"),
}

_DURATION_MS = {
    "success": 3500,
    "info":    4000,
    "warning": 5000,
    "error":   6000,
    "crash":   7000,
}


class Toast(Gtk.Box):
    """A single toast notification widget."""

    def __init__(self, message: str, kind: str = "info",
                 on_dismiss=None, action_label: str = None,
                 on_action=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.get_style_context().add_class("toast")
        self.get_style_context().add_class(_KINDS.get(kind, ("ℹ", "toast-info"))[1])

        # Opacity for fade-out
        self._on_dismiss = on_dismiss
        self._timer_id = None
        self._fading = False

        icon_text, _ = _KINDS.get(kind, ("ℹ", "toast-info"))
        icon = Gtk.Label(label=icon_text)
        icon.get_style_context().add_class("toast-icon")
        self.pack_start(icon, False, False, 0)

        msg_label = Gtk.Label(label=message)
        msg_label.set_xalign(0)
        msg_label.set_line_wrap(True)
        msg_label.set_max_width_chars(40)
        msg_label.get_style_context().add_class("toast-msg")
        self.pack_start(msg_label, True, True, 0)

        if action_label and on_action:
            action_btn = Gtk.Button(label=action_label)
            action_btn.get_style_context().add_class("toast-action-btn")
            action_btn.set_relief(Gtk.ReliefStyle.NONE)
            action_btn.connect("clicked", lambda _: (on_action(), self.dismiss()))
            self.pack_start(action_btn, False, False, 0)

        close_btn = Gtk.Button(label="✕")
        close_btn.get_style_context().add_class("toast-close-btn")
        close_btn.set_relief(Gtk.ReliefStyle.NONE)
        close_btn.set_tooltip_text("Dismiss")
        close_btn.connect("clicked", lambda _: self.dismiss())
        self.pack_end(close_btn, False, False, 0)

        self.set_halign(Gtk.Align.END)
        self.set_valign(Gtk.Align.END)
        self.set_margin_bottom(8)
        self.set_margin_end(12)

        duration = _DURATION_MS.get(kind, 4000)
        self._timer_id = GLib.timeout_add(duration, self._auto_dismiss)

    def dismiss(self):
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = None
        if self._on_dismiss:
            self._on_dismiss(self)

    def _auto_dismiss(self):
        self._timer_id = None
        self.dismiss()
        return False


class ToastManager:
    """Stacks and manages multiple Toast widgets in an overlay's bottom-right."""

    def __init__(self, overlay: Gtk.Overlay):
        self._overlay = overlay
        self._stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._stack.set_halign(Gtk.Align.END)
        self._stack.set_valign(Gtk.Align.END)
        self._stack.set_margin_bottom(12)
        self._stack.set_margin_end(12)
        self._stack.get_style_context().add_class("toast-stack")
        # Overlay stacks do not steal pointer events
        self._stack.set_no_show_all(False)
        overlay.add_overlay(self._stack)
        overlay.set_overlay_pass_through(self._stack, True)
        self._stack.show()

    def show(self, message: str, kind: str = "info",
             action_label: str = None, on_action=None):
        """Display a toast. Thread-safe: can be called from GLib.idle_add."""
        def _create():
            toast = Toast(
                message, kind=kind,
                on_dismiss=self._remove,
                action_label=action_label,
                on_action=on_action,
            )
            self._stack.pack_end(toast, False, False, 0)
            toast.show_all()
            return False

        GLib.idle_add(_create)

    def _remove(self, toast: Toast):
        def _destroy():
            try:
                self._stack.remove(toast)
                toast.destroy()
            except Exception:
                pass
            return False
        GLib.idle_add(_destroy)
