"""Embedding manager — reparents editor windows into GTK Socket containers."""

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

import subprocess


class EmbeddingManager:
    """
    Manages the embedding of editor windows into GTK Socket widgets.

    Primary method: GTK 3's Gtk.Socket / XEMBED protocol.
    Fallback: xdotool-based raw X11 reparenting.

    embed_window() is fully asynchronous: it schedules work via GLib and calls
    on_success() or on_failure() on the GTK main thread when the outcome is known.
    """

    def __init__(self):
        self._sockets: dict[str, Gtk.Socket] = {}      # session_id → socket
        self._xids: dict[str, int] = {}                # session_id → embedded XID
        self._containers: dict[str, Gtk.Box] = {}      # session_id → container
        self._method: dict[str, str] = {}              # session_id → "socket" | "xdotool"

        # Async embed tracking
        self._plug_added_flags: dict[str, bool] = {}   # session_id → plug-added fired?
        self._pending_embed: dict[str, tuple] = {}     # session_id → (on_success, on_failure, xid, container)
        self._verify_timeout_ids: dict[str, int] = {}  # session_id → GLib source id

        # Resize debounce: pending GLib timeout id per session
        self._resize_timeout_ids: dict[str, int] = {}

        # Plug-removed callbacks: called when a session's window exits unexpectedly
        self._plug_removed_callbacks: dict[str, callable] = {}

        # Sessions being intentionally unembedded — suppresses the plug-removed callback
        self._unembedding: set[str] = set()

    # =========================================================
    # Container management
    # =========================================================

    def create_container(self, session_id: str) -> Gtk.Box:
        """Create a container box for a session's embedded window."""
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        container.set_hexpand(True)
        container.set_vexpand(True)
        container.get_style_context().add_class("embed-container")
        self._containers[session_id] = container
        return container

    # =========================================================
    # Public embed API (async)
    # =========================================================

    def embed_window(self, session_id: str, xid: int, container: Gtk.Box = None,
                     *, on_success=None, on_failure=None):
        """
        Asynchronously embed an X11 window (by XID) into the container.

        Strategy:
          1. Remove decorations (synchronous, fast xprop calls).
          2. Wait 200 ms for the WM to process decoration removal.
          3. Attempt GTK Socket / XEMBED embedding.
          4. Wait up to 1500 ms for the plug-added signal to confirm success.
          5. If plug-added never fires, fall back to xdotool raw reparenting.
          6. Call on_success() or on_failure() on the GTK main thread.

        The caller must NOT check a return value — outcome is delivered via callbacks.
        """
        if container is None:
            container = self._containers.get(session_id)
        if container is None:
            print(f"[EmbeddingManager] No container for session {session_id}")
            if on_failure:
                GLib.idle_add(on_failure)
            return

        # Remove window decorations — fast xprop calls, safe on main thread
        self._undecorate_window(xid)

        # Give the WM time to process the decoration-removal hint before we
        # attempt to reparent.  Use a GLib timeout rather than time.sleep so
        # we never block the GTK main loop.
        GLib.timeout_add(200, self._begin_embed,
                         session_id, xid, container, on_success, on_failure)

    # =========================================================
    # Internal embed pipeline
    # =========================================================

    def _begin_embed(self, session_id: str, xid: int, container: Gtk.Box,
                     on_success, on_failure):
        """Step 2 of async pipeline: attempt Socket embed after WM delay."""
        try:
            self._remove_socket(session_id)

            socket = Gtk.Socket()
            socket.set_hexpand(True)
            socket.set_vexpand(True)
            socket.connect("plug-added", self._on_plug_added, session_id)
            socket.connect("plug-removed", self._on_plug_removed, session_id)

            container.pack_start(socket, True, True, 0)
            container.show_all()
            socket.realize()

            # Reset the confirmation flag and store callbacks
            self._plug_added_flags[session_id] = False
            self._pending_embed[session_id] = (on_success, on_failure, xid, container)

            # Safety check: prevent embedding invalid or root windows 
            # to avoid gdk_window_reparent assertion crashes in GTK.
            if xid <= 1000:
                raise ValueError("XID looks suspiciously like a system/root window")

            # Request XEMBED reparenting
            socket.add_id(xid)

            self._sockets[session_id] = socket
            self._xids[session_id] = xid

            # Schedule a verification check — if plug-added hasn't fired by
            # then, the XEMBED embed silently failed and we try xdotool next.
            timeout_id = GLib.timeout_add(
                1500, self._verify_socket_embed, session_id)
            self._verify_timeout_ids[session_id] = timeout_id

        except Exception as e:
            print(f"[EmbeddingManager] Socket setup failed for XID {xid}: {e}")
            self._remove_socket(session_id)
            self._plug_added_flags.pop(session_id, None)
            self._pending_embed.pop(session_id, None)
            # Proceed directly to xdotool fallback
            self._try_xdotool_then_callback(
                session_id, xid, container, on_success, on_failure)

        return False  # Don't repeat GLib timeout
    def _verify_socket_embed(self, session_id: str):
        """
        Called 1500 ms after socket.add_id().

        If plug-added already fired, on_success was already called from
        _on_plug_added and _pending_embed was cleared — nothing to do.
        Otherwise the XEMBED embed failed silently; try xdotool.
        """
        self._verify_timeout_ids.pop(session_id, None)

        callbacks = self._pending_embed.pop(session_id, None)
        if callbacks is None:
            # plug-added already fired and handled — we're done
            return False

        plug_ok = self._plug_added_flags.pop(session_id, False)
        on_success, on_failure, xid, container = callbacks

        if plug_ok:
            # Rare: plug-added fired but _on_plug_added didn't clear
            # _pending_embed in time (shouldn't happen, but handle it).
            self._method[session_id] = "socket"
            print(f"[EmbeddingManager] Socket embed confirmed (late): XID {xid}")
            if on_success:
                on_success()
        else:
            print(f"[EmbeddingManager] No plug-added after 1500 ms, "
                  f"trying xdotool fallback: XID {xid}")
            self._remove_socket(session_id)
            self._xids.pop(session_id, None)
            self._try_xdotool_then_callback(
                session_id, xid, container, on_success, on_failure)

        return False  # Don't repeat GLib timeout

    def _try_xdotool_then_callback(self, session_id: str, xid: int,
                                    container: Gtk.Box,
                                    on_success, on_failure):
        """Attempt xdotool reparenting; call the appropriate callback."""
        if xid and container and self._embed_via_xdotool(session_id, xid, container):
            self._method[session_id] = "xdotool"
            print(f"[EmbeddingManager] xdotool fallback succeeded for {session_id}")
            if on_success:
                on_success()
        else:
            print(f"[EmbeddingManager] All embed methods failed for {session_id}")
            if on_failure:
                on_failure()

    # =========================================================
    # XEMBED (Gtk.Socket) helpers
    # =========================================================

    def _on_plug_added(self, socket, session_id):
        """Called when a window is successfully plugged into the socket."""
        try:
            print(f"[EmbeddingManager] Plug added for session {session_id}")
            self._plug_added_flags[session_id] = True

            # Cancel the verification timeout — we already know it succeeded
            timeout_id = self._verify_timeout_ids.pop(session_id, None)
            if timeout_id:
                GLib.source_remove(timeout_id)

            # Retrieve and clear stored callbacks
            callbacks = self._pending_embed.pop(session_id, None)
            if callbacks:
                on_success = callbacks[0]
                self._method[session_id] = "socket"
                if on_success:
                    # Defer to next GTK iteration so the socket finishes drawing first
                    GLib.idle_add(on_success)

            socket.set_can_focus(True)
            socket.grab_focus()

            xid = self._xids.get(session_id)
            if xid:
                GLib.timeout_add(500, self._force_coordinate_refresh, xid)
        except Exception as e:
            print(f"[EmbeddingManager] Error in plug-added handler for {session_id}: {e}")

    def _on_plug_removed(self, socket, session_id):
        """Called when a window is unplugged from the socket."""
        print(f"[EmbeddingManager] Plug removed for session {session_id}")
        # Only notify the app when this is *not* an intentional unembed (e.g.
        # the editor window was closed by the user or crashed).
        if session_id not in self._unembedding:
            callback = self._plug_removed_callbacks.get(session_id)
            if callback:
                try:
                    GLib.idle_add(callback, session_id)
                except Exception as e:
                    print(f"[EmbeddingManager] plug-removed callback error for {session_id}: {e}")
        # Return True to prevent the socket from being destroyed
        return True

    # =========================================================
    # xdotool reparenting fallback
    # =========================================================

    def _embed_via_xdotool(self, session_id: str, xid: int,
                            container: Gtk.Box) -> bool:
        """
        Fallback: reparent using xdotool.

        This does a raw X11 reparent into the GTK container's X11 window,
        bypassing XEMBED.  Works for apps that don't speak the XEMBED protocol
        (terminals, file managers, etc.) at the cost of no automatic resizing
        and potential rendering quirks.
        """
        try:
            container.realize()
            container.show_all()

            # Process pending GTK events so the container is fully realized
            while Gtk.events_pending():
                Gtk.main_iteration()

            gdk_window = container.get_window()
            if gdk_window is None:
                print("[EmbeddingManager] Container has no GDK window for xdotool fallback")
                return False

            container_xid = gdk_window.get_xid()

            result = subprocess.run(
                ["xdotool", "windowreparent", str(xid), str(container_xid)],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode != 0:
                print(f"[EmbeddingManager] xdotool reparent failed: {result.stderr}")
                return False

            # Resize to fill the container
            alloc = container.get_allocation()
            subprocess.run(
                ["xdotool", "windowsize", str(xid),
                 str(alloc.width), str(alloc.height)],
                capture_output=True, timeout=2
            )
            subprocess.run(
                ["xdotool", "windowmove", "--relative", str(xid), "0", "0"],
                capture_output=True, timeout=2
            )

            self._xids[session_id] = xid

            # Track container resize so we can keep the window filling it
            container.connect("size-allocate",
                              self._on_container_resize_xdotool, session_id)

            print(f"[EmbeddingManager] xdotool reparent succeeded: "
                  f"XID {xid} → container {container_xid}")
            return True

        except Exception as e:
            print(f"[EmbeddingManager] xdotool fallback failed: {e}")
            return False

    def _on_container_resize_xdotool(self, container, allocation, session_id):
        """Debounced resize handler for xdotool-embedded windows.

        GTK fires size-allocate many times per second during window dragging.
        We cancel the previous pending resize and reschedule 80 ms out so only
        the final size triggers an actual xdotool call.  The resize itself runs
        as a fire-and-forget Popen so it never blocks the GTK main loop.
        """
        old_id = self._resize_timeout_ids.pop(session_id, None)
        if old_id:
            GLib.source_remove(old_id)

        xid = self._xids.get(session_id)
        if not xid:
            return

        width = allocation.width
        height = allocation.height

        def do_resize():
            self._resize_timeout_ids.pop(session_id, None)
            current_xid = self._xids.get(session_id)
            if current_xid:
                try:
                    subprocess.Popen(
                        ["xdotool", "windowsize", str(current_xid),
                         str(width), str(height)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
            return False  # Don't repeat

        self._resize_timeout_ids[session_id] = GLib.timeout_add(80, do_resize)

    # =========================================================
    # Decoration removal
    # =========================================================

    def _undecorate_window(self, xid: int):
        """Remove window decorations and taskbar entry."""
        try:
            subprocess.run(
                ["xprop", "-id", str(xid),
                 "-f", "_MOTIF_WM_HINTS", "32c",
                 "-set", "_MOTIF_WM_HINTS", "2, 0, 0, 0, 0"],
                capture_output=True, timeout=3
            )
            subprocess.run(
                ["xprop", "-id", str(xid),
                 "-f", "_NET_WM_STATE", "32a",
                 "-set", "_NET_WM_STATE", "_NET_WM_STATE_SKIP_TASKBAR"],
                capture_output=True, timeout=3
            )
        except Exception as e:
            print(f"[EmbeddingManager] Could not undecorate window {xid}: {e}")

    # =========================================================
    # Focus helpers
    # =========================================================

    def focus_xid(self, xid: int):
        """Raise and focus an arbitrary X11 window by XID.

        Runs fire-and-forget (Popen) so it never blocks the GTK main loop.
        The ``--sync`` flag that was here before caused the main thread to wait
        for WM confirmation on every session switch, making the UI stutter.
        """
        try:
            subprocess.Popen(
                ["xdotool", "windowactivate", str(xid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"[EmbeddingManager] Could not focus window {xid}: {e}")

    def focus_embedded(self, session_id: str):
        """Give keyboard focus to the embedded window."""
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

    def _force_coordinate_refresh(self, xid: int):
        """Move the window 1 px and back to force position updates in Electron."""
        try:
            subprocess.run(["xdotool", "windowmove", "--relative", str(xid), "1", "1"],
                           capture_output=True)
            subprocess.run(["xdotool", "windowmove", "--relative", str(xid), "0", "0"],
                           capture_output=True)
            print(f"[EmbeddingManager] Forced coordinate refresh for XID {xid}")
        except Exception:
            pass
        return False  # Don't repeat GLib timeout

    # =========================================================
    # Session lifecycle
    # =========================================================

    def set_plug_removed_callback(self, session_id: str, callback):
        """Register a callback invoked when a session's embedded window exits unexpectedly.

        The callback receives ``session_id`` as its only argument and is called
        on the GTK main thread via ``GLib.idle_add``.
        """
        self._plug_removed_callbacks[session_id] = callback

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

    def unembed_window(self, session_id: str):
        """Remove an embedded window and clean up."""
        # Signal that this is intentional so _on_plug_removed doesn't fire the
        # crash callback.
        self._unembedding.add(session_id)
        try:
            # Cancel any in-flight verification timeout
            timeout_id = self._verify_timeout_ids.pop(session_id, None)
            if timeout_id:
                GLib.source_remove(timeout_id)
            self._pending_embed.pop(session_id, None)
            self._plug_added_flags.pop(session_id, None)

            # Cancel any pending resize
            resize_id = self._resize_timeout_ids.pop(session_id, None)
            if resize_id:
                GLib.source_remove(resize_id)

            self._remove_socket(session_id)
            self._xids.pop(session_id, None)
            self._method.pop(session_id, None)
        finally:
            self._unembedding.discard(session_id)

        # Drop the crash callback once cleanly unembedded
        self._plug_removed_callbacks.pop(session_id, None)

    def _remove_socket(self, session_id: str):
        """Remove a socket widget from its container."""
        socket = self._sockets.pop(session_id, None)
        if socket:
            parent = socket.get_parent()
            if parent:
                parent.remove(socket)
            socket.destroy()

    def remove_session(self, session_id: str):
        """Fully clean up a session's embedding resources."""
        self.unembed_window(session_id)
        container = self._containers.pop(session_id, None)
        if container:
            parent = container.get_parent()
            if parent:
                parent.remove(container)
            container.destroy()

    def cleanup(self):
        """Clean up all embedding resources."""
        for session_id in list(self._sockets.keys()):
            self.unembed_window(session_id)
        for session_id in list(self._containers.keys()):
            container = self._containers.pop(session_id)
            container.destroy()
