"""Content area — main embedding container with empty state.

Updated to work with SessionWorkspace widgets for multi-app sessions.
"""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango


class ContentArea(Gtk.Box):
    """
    Main content area that holds session workspaces.
    
    Shows an empty state when no session is active,
    and switches between session workspaces when sessions are selected.
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.get_style_context().add_class("content-area")

        # Overlay wraps the entire content so toasts can float over it
        self.overlay = Gtk.Overlay()

        # Stack for switching between empty state and session workspaces
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(200)

        # Empty state
        self._create_empty_state()
        self.stack.add_named(self._empty_state, "empty")
        self.stack.set_visible_child_name("empty")

        self.overlay.add(self.stack)
        self.pack_start(self.overlay, True, True, 0)


        # Track active session
        self._active_session_id = None

        # Callback for "New Session" button
        self.on_new_session = None

    def _create_empty_state(self):
        """Create the empty state widget shown when no session is active."""
        self._empty_state = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8
        )
        self._empty_state.set_halign(Gtk.Align.CENTER)
        self._empty_state.set_valign(Gtk.Align.CENTER)
        self._empty_state.get_style_context().add_class("empty-state")

        # Icon
        icon_label = Gtk.Label()
        icon_label.set_markup(
            '<span font_size="72000" foreground="#292e42">⬡</span>'
        )
        icon_label.get_style_context().add_class("empty-icon")
        self._empty_state.pack_start(icon_label, False, False, 0)

        # Title
        title = Gtk.Label()
        title.set_markup(
            '<span font_size="large" font_weight="600" foreground="#565f89">'
            'No Active Session</span>'
        )
        title.get_style_context().add_class("empty-title")
        self._empty_state.pack_start(title, False, False, 0)

        # Subtitle
        subtitle = Gtk.Label()
        subtitle.set_markup(
            '<span font_size="small" foreground="#3b4261">'
            'Select a session from the sidebar or create a new one</span>'
        )
        subtitle.get_style_context().add_class("empty-subtitle")
        self._empty_state.pack_start(subtitle, False, False, 0)

        # New session button
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        btn_box.set_halign(Gtk.Align.CENTER)
        btn_box.get_style_context().add_class("empty-action")

        new_btn = Gtk.Button(label="＋  New Session")
        new_btn.connect("clicked", self._on_new_session_clicked)
        btn_box.pack_start(new_btn, False, False, 0)

        self._empty_state.pack_start(btn_box, False, False, 16)

    def _on_new_session_clicked(self, button):
        """Handle new session button click."""
        if self.on_new_session:
            self.on_new_session()

    # ------------------------------------------------------------------
    # Session container management (legacy single-container API)
    # ------------------------------------------------------------------

    def add_session_container(self, session_id: str, container: Gtk.Widget):
        """Add a session container (or workspace) to the content stack."""
        current_child = self.stack.get_visible_child_name()
        self.stack.add_named(container, session_id)
        # Sessions loaded before window.show_all() are shown by the window.
        # Sessions created later must be shown here, otherwise selecting the
        # new stack child can leave the previously visible embedded window
        # painted in the content area.
        container.show_all()
        if current_child and current_child != session_id:
            self.stack.set_visible_child_name(current_child)

    def show_session(self, session_id: str):
        """Switch to showing a session's workspace/container."""
        self._active_session_id = session_id
        child = self.stack.get_child_by_name(session_id)
        if child:
            child.show_all()
        self.stack.set_visible_child_name(session_id)

    def show_empty(self):
        """Show the empty state."""
        self._active_session_id = None
        self._empty_state.show_all()
        self.stack.set_visible_child_name("empty")

    def remove_session_container(self, session_id: str):
        """Remove a session container from the stack."""
        child = self.stack.get_child_by_name(session_id)
        if child:
            self.stack.remove(child)
        if self._active_session_id == session_id:
            self.show_empty()

    @property
    def active_session_id(self):
        return self._active_session_id
