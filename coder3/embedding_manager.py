"""Embedding manager — reparents VS Code windows into GTK Socket containers."""

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

import subprocess
import time


class EmbeddingManager:
    """
    Manages the embedding of VS Code windows into GTK Socket widgets.
    
    Primary method: GTK 3's Gtk.Socket.add_id() for X11 window reparenting.
    Fallback: xdotool-based reparenting into the host container's XID.
    """

    def __init__(self):
        self._sockets: dict[str, Gtk.Socket] = {}  # session_id -> socket
        self._xids: dict[str, int] = {}  # session_id -> embedded XID
        self._containers: dict[str, Gtk.Box] = {}  # session_id -> container
        self._method: dict[str, str] = {}  # session_id -> "socket" | "xdotool"

    def create_container(self, session_id: str) -> Gtk.Box:
        """Create a container box for a session's embedded window."""
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        container.set_hexpand(True)
        container.set_vexpand(True)
        container.get_style_context().add_class("embed-container")
        self._containers[session_id] = container
        return container

    def embed_window(self, session_id: str, xid: int, container: Gtk.Box = None) -> bool:
        """
        Attempt to embed a VS Code window (by XID) into the container.
        
        Tries Gtk.Socket first, falls back to xdotool reparenting.
        Returns True if embedding succeeded.
        """
        if container is None:
            container = self._containers.get(session_id)
        if container is None:
            print(f"[EmbeddingManager] No container for session {session_id}")
            return False

        # Remove window decorations first
        self._undecorate_window(xid)
        
        # Give the WM a moment to process decoration removal
        time.sleep(0.2)

        # Try Gtk.Socket method first
        success = self._embed_via_socket(session_id, xid, container)
        if success:
            self._method[session_id] = "socket"
            return True

        # Fallback: xdotool reparenting
        print(f"[EmbeddingManager] Socket embed failed, trying xdotool fallback...")
        success = self._embed_via_xdotool(session_id, xid, container)
        if success:
            self._method[session_id] = "xdotool"
            return True

        return False

    def _embed_via_socket(self, session_id: str, xid: int, container: Gtk.Box) -> bool:
        """Try embedding via Gtk.Socket.add_id() — the cleanest method."""
        try:
            # Clean up any existing socket for this session
            self._remove_socket(session_id)

            # Create new socket
            socket = Gtk.Socket()
            socket.set_hexpand(True)
            socket.set_vexpand(True)
            
            # Connect signals
            socket.connect("plug-added", self._on_plug_added, session_id)
            socket.connect("plug-removed", self._on_plug_removed, session_id)
            
            # Add socket to container
            container.pack_start(socket, True, True, 0)
            container.show_all()

            # The socket must be realized (have an X window) before we can add to it
            socket.realize()

            # Now reparent the VS Code window into our socket
            socket.add_id(xid)

            self._sockets[session_id] = socket
            self._xids[session_id] = xid
            
            print(f"[EmbeddingManager] Socket embed succeeded: XID {xid} → session {session_id}")
            return True

        except Exception as e:
            print(f"[EmbeddingManager] Socket embed failed for XID {xid}: {e}")
            self._remove_socket(session_id)
            return False

    def _embed_via_xdotool(self, session_id: str, xid: int, container: Gtk.Box) -> bool:
        """
        Fallback: reparent using xdotool.
        
        This reparents the VS Code window into the GTK container's X11 window.
        Less clean than Socket, but can work when Socket fails.
        """
        try:
            # We need the container to be realized to get its window
            container.realize()
            container.show_all()
            
            # Process pending GTK events
            while Gtk.events_pending():
                Gtk.main_iteration()
            
            gdk_window = container.get_window()
            if gdk_window is None:
                print("[EmbeddingManager] Container has no GDK window for xdotool fallback")
                return False

            container_xid = gdk_window.get_xid()
            
            # Use xdotool to reparent
            result = subprocess.run(
                ["xdotool", "windowreparent", str(xid), str(container_xid)],
                capture_output=True, text=True, timeout=5
            )
            
            if result.returncode != 0:
                print(f"[EmbeddingManager] xdotool reparent failed: {result.stderr}")
                return False

            # Resize to fill the container
            alloc = container.get_allocation()
            subprocess.run(
                ["xdotool", "windowsize", str(xid), str(alloc.width), str(alloc.height)],
                capture_output=True, timeout=3
            )
            subprocess.run(
                ["xdotool", "windowmove", "--relative", str(xid), "0", "0"],
                capture_output=True, timeout=3
            )

            self._xids[session_id] = xid
            
            # Set up resize tracking for xdotool mode
            container.connect("size-allocate", self._on_container_resize_xdotool, session_id)
            
            print(f"[EmbeddingManager] xdotool reparent succeeded: XID {xid} → container {container_xid}")
            return True

        except Exception as e:
            print(f"[EmbeddingManager] xdotool fallback failed: {e}")
            return False

    def _on_container_resize_xdotool(self, container, allocation, session_id):
        """Handle container resize for xdotool-embedded windows."""
        xid = self._xids.get(session_id)
        if xid:
            try:
                subprocess.run(
                    ["xdotool", "windowsize", str(xid),
                     str(allocation.width), str(allocation.height)],
                    capture_output=True, timeout=1
                )
            except Exception:
                pass

    def _undecorate_window(self, xid: int):
        """Remove window decorations and taskbar entry."""
        try:
            # Remove decorations via Motif hints
            subprocess.run(
                ["xprop", "-id", str(xid),
                 "-f", "_MOTIF_WM_HINTS", "32c",
                 "-set", "_MOTIF_WM_HINTS", "2, 0, 0, 0, 0"],
                capture_output=True, timeout=3
            )
            # Remove from taskbar
            subprocess.run(
                ["xprop", "-id", str(xid),
                 "-f", "_NET_WM_STATE", "32a",
                 "-set", "_NET_WM_STATE", "_NET_WM_STATE_SKIP_TASKBAR"],
                capture_output=True, timeout=3
            )
        except Exception as e:
            print(f"[EmbeddingManager] Could not undecorate window {xid}: {e}")

    def unembed_window(self, session_id: str):
        """Remove an embedded window and clean up."""
        self._remove_socket(session_id)
        self._xids.pop(session_id, None)
        self._method.pop(session_id, None)

    def _remove_socket(self, session_id: str):
        """Remove a socket widget from its container."""
        socket = self._sockets.pop(session_id, None)
        if socket:
            parent = socket.get_parent()
            if parent:
                parent.remove(socket)
            socket.destroy()

    def show_session(self, session_id: str):
        """Show the container for a session."""
        container = self._containers.get(session_id)
        if container:
            container.show_all()

    def hide_session(self, session_id: str):
        """Hide the container for a session."""
        container = self._containers.get(session_id)
        if container:
            container.hide()

    def is_embedded(self, session_id: str) -> bool:
        """Check if a session has an embedded window."""
        return session_id in self._xids

    def get_container(self, session_id: str) -> Gtk.Box:
        """Get the container for a session."""
        return self._containers.get(session_id)

    def focus_xid(self, xid: int):
        """Raise and focus an arbitrary X11 window by XID."""
        try:
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", str(xid)],
                capture_output=True, timeout=2
            )
        except Exception:
            try:
                subprocess.run(["xdotool", "windowraise", str(xid)], capture_output=True, timeout=1)
                subprocess.run(["xdotool", "windowfocus", str(xid)], capture_output=True, timeout=1)
            except Exception as e:
                print(f"[EmbeddingManager] Could not focus window {xid}: {e}")

    def focus_embedded(self, session_id: str):
        """Give keyboard focus to the embedded VS Code window."""
        socket = self._sockets.get(session_id)
        if socket:
            try:
                socket.set_can_focus(True)
                socket.grab_focus()
            except Exception as e:
                print(f"[EmbeddingManager] Could not focus socket for {session_id}: {e}")

        xid = self._xids.get(session_id)
        if xid:
            self.focus_xid(xid)

    def remove_session(self, session_id: str):
        """Fully clean up a session's embedding resources."""
        self.unembed_window(session_id)
        container = self._containers.pop(session_id, None)
        if container:
            parent = container.get_parent()
            if parent:
                parent.remove(container)
            container.destroy()

    def _on_plug_added(self, socket, session_id):
        """Called when a window is successfully plugged into the socket."""
        print(f"[EmbeddingManager] Plug added for session {session_id}")
        
        # Ensure the socket can receive and hold focus
        socket.set_can_focus(True)
        socket.grab_focus()
        
        # Jiggle the window to force Electron to recalculate its screen coordinates.
        # This is critical for popup menus to appear in the right place.
        xid = self._xids.get(session_id)
        if xid:
            GLib.timeout_add(500, self._force_coordinate_refresh, xid)

    def _force_coordinate_refresh(self, xid: int):
        """Move the window 1px and back to force position updates."""
        try:
            subprocess.run(["xdotool", "windowmove", "--relative", str(xid), "1", "1"], capture_output=True)
            subprocess.run(["xdotool", "windowmove", "--relative", str(xid), "0", "0"], capture_output=True)
            print(f"[EmbeddingManager] Forced coordinate refresh for XID {xid}")
        except Exception:
            pass
        return False  # Don't repeat GLib timeout

    def _on_plug_removed(self, socket, session_id):
        """Called when a window is unplugged from the socket."""
        print(f"[EmbeddingManager] Plug removed for session {session_id}")
        # Return True to prevent the socket from being destroyed
        return True

    def cleanup(self):
        """Clean up all embedding resources."""
        for session_id in list(self._sockets.keys()):
            self.unembed_window(session_id)
        for session_id in list(self._containers.keys()):
            container = self._containers.pop(session_id)
            container.destroy()
