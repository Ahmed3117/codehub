import os
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Gdk, Pango, Vte, GLib


class IntegratedTerminal(Gtk.Box):
    """A native embedded terminal using VTE."""

    def __init__(self, cwd: str = None, env_vars: dict = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_hexpand(True)
        self.set_vexpand(True)
        
        self.cwd = cwd or os.path.expanduser("~")
        self.env_vars = env_vars or {}

        self.terminal = Vte.Terminal()
        self.terminal.set_hexpand(True)
        self.terminal.set_vexpand(True)
        self.terminal.set_mouse_autohide(True)
        self.terminal.set_scrollback_lines(10000)
        
        # Apply a simple theme
        bg = Gdk.RGBA()
        bg.parse("#1e1e1e")
        fg = Gdk.RGBA()
        fg.parse("#cccccc")
        self.terminal.set_colors(fg, bg, None)
        
        # Font
        font_desc = Pango.FontDescription.from_string("Monospace 11")
        self.terminal.set_font(font_desc)

        self.terminal.connect("child-exited", self._on_child_exited)
        
        # Add clipboard support (keybindings and context menu)
        self.terminal.connect("key-press-event", self._on_key_press)
        self.terminal.connect("button-press-event", self._on_button_press)
        
        # Start shell
        self._spawn_shell()

        # Wrap in a scrolled window or box
        self.pack_start(self.terminal, True, True, 0)
        self.show_all()

    def _spawn_shell(self):
        shell = os.environ.get("SHELL", "/bin/bash")
        
        env = os.environ.copy()
        env.update(self.env_vars)
        envv = [f"{k}={v}" for k, v in env.items()]
        
        try:
            self.terminal.spawn_async(
                Vte.PtyFlags.DEFAULT,
                self.cwd,
                [shell],
                envv,
                GLib.SpawnFlags.DEFAULT,
                None, None,
                -1,
                None,
                None
            )
        except Exception as e:
            print(f"[IntegratedTerminal] Failed to spawn shell: {e}")

    def _on_child_exited(self, terminal, status):
        # Respawn if user types exit
        self._spawn_shell()

    def _on_key_press(self, widget, event):
        modifiers = Gtk.accelerator_get_default_mod_mask()
        state = event.state & modifiers
        
        # Ctrl + Shift + C/V
        if state == (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK):
            if event.keyval in (Gdk.KEY_C, Gdk.KEY_c):
                self.terminal.copy_clipboard_format(Vte.Format.TEXT)
                return True
            elif event.keyval in (Gdk.KEY_V, Gdk.KEY_v):
                self.terminal.paste_clipboard()
                return True
                
        # Shift + Insert for Paste, Ctrl + Insert for Copy
        if state == Gdk.ModifierType.SHIFT_MASK and event.keyval == Gdk.KEY_Insert:
            self.terminal.paste_clipboard()
            return True
        if state == Gdk.ModifierType.CONTROL_MASK and event.keyval == Gdk.KEY_Insert:
            self.terminal.copy_clipboard_format(Vte.Format.TEXT)
            return True
            
        return False

    def _on_button_press(self, widget, event):
        if event.button == 3:  # Right click
            menu = Gtk.Menu()
            
            copy_item = Gtk.MenuItem(label="Copy")
            copy_item.connect("activate", lambda w: self.terminal.copy_clipboard_format(Vte.Format.TEXT))
            menu.append(copy_item)
            
            paste_item = Gtk.MenuItem(label="Paste")
            paste_item.connect("activate", lambda w: self.terminal.paste_clipboard())
            menu.append(paste_item)
            
            menu.show_all()
            menu.popup_at_pointer(event)
            return True
        return False
