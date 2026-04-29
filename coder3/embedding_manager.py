"""Embedding manager — reparents editor windows into GTK Socket containers.

Supports compound slot keys (``session_id:app_id``) so a single session can
host multiple embedded windows (editor + Postman + Chrome + …).  Legacy
callers that pass only a ``session_id`` continue to work — the key is used
as-is.
"""

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

    All internal dictionaries are keyed by *slot_key* which is typically
    ``session_id:app_id`` for multi-app workspaces, or just ``session_id``
    for backward compatibility with single-editor callers.
    """

    def __init__(self):
        self._sockets: dict[str, Gtk.Socket] = {}      # slot_key → socket
        self._xids: dict[str, int] = {}                # slot_key → embedded XID
        self._containers: dict[str, Gtk.Box] = {}      # slot_key → container
        self._method: dict[str, str] = {}              # slot_key → "socket" | "xdotool"

        # Async embed tracking
        self._plug_added_flags: dict[str, bool] = {}   # slot_key → plug-added fired?
        self._pending_embed: dict[str, tuple] = {}     # slot_key → (on_success, on_failure, xid, container)
        self._verify_timeout_ids: dict[str, int] = {}  # slot_key → GLib source id

        # Resize debounce: pending GLib timeout id per slot
        self._resize_timeout_ids: dict[str, int] = {}

        # Plug-removed callbacks: called when a slot's window exits unexpectedly
        self._plug_removed_callbacks: dict[str, callable] = {}

        # Slots being intentionally unembedded — suppresses the plug-removed callback
        self._unembedding: set[str] = set()

    # =========================================================
    # Container management
    # =========================================================

    def create_container(self, slot_key: str) -> Gtk.Box:
        """Create a container box for an embedded window.

        Args:
            slot_key: The key for this embed slot.  For single-editor mode
                      this is just the session_id.  For multi-app mode it
                      is ``session_id:app_id``.
        """
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        container.set_hexpand(True)
        container.set_vexpand(True)
        container.get_style_context().add_class("embed-container")
        self._containers[slot_key] = container
        return container

    # =========================================================
    # Public embed API (async)
    # =========================================================

    def embed_window(self, slot_key: str, xid: int, container: Gtk.Box = None,
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
            container = self._containers.get(slot_key)
        if container is None:
            print(f"[EmbeddingManager] No container for slot {slot_key}")
            if on_failure:
                GLib.idle_add(on_failure)
            return

        # Remove window decorations — fast xprop calls, safe on main thread
        self._undecorate_window(xid)

        # Give the WM time to process the decoration-removal hint before we
        # attempt to reparent.  Use a GLib timeout rather than time.sleep so
        # we never block the GTK main loop.
        GLib.timeout_add(200, self._begin_embed,
                         slot_key, xid, container, on_success, on_failure)

    # =========================================================
    # Internal embed pipeline
    # =========================================================

    def _begin_embed(self, slot_key: str, xid: int, container: Gtk.Box,
                     on_success, on_failure):
        """Step 2 of async pipeline: attempt Socket embed after WM delay."""
        try:
            self._remove_socket(slot_key)

            socket = Gtk.Socket()
            socket.set_hexpand(True)
            socket.set_vexpand(True)
            socket.connect("plug-added", self._on_plug_added, slot_key)
            socket.connect("plug-removed", self._on_plug_removed, slot_key)

            container.pack_start(socket, True, True, 0)
            container.show_all()
            socket.realize()

            # Reset the confirmation flag and store callbacks
            self._plug_added_flags[slot_key] = False
            self._pending_embed[slot_key] = (on_success, on_failure, xid, container)

            # Safety check: prevent embedding invalid or root windows 
            # to avoid gdk_window_reparent assertion crashes in GTK.
            if xid <= 1000:
                raise ValueError("XID looks suspiciously like a system/root window")

            # Request XEMBED reparenting
            socket.add_id(xid)

            self._sockets[slot_key] = socket
            self._xids[slot_key] = xid

            # Schedule a verification check — if plug-added hasn't fired by
            # then, the XEMBED embed silently failed and we try xdotool next.
            timeout_id = GLib.timeout_add(
                1500, self._verify_socket_embed, slot_key)
            self._verify_timeout_ids[slot_key] = timeout_id

        except Exception as e:
            print(f"[EmbeddingManager] Socket setup failed for XID {xid}: {e}")
            self._remove_socket(slot_key)
            self._plug_added_flags.pop(slot_key, None)
            self._pending_embed.pop(slot_key, None)
            # Proceed directly to xdotool fallback
            self._try_xdotool_then_callback(
                slot_key, xid, container, on_success, on_failure)

        return False  # Don't repeat GLib timeout

    def _verify_socket_embed(self, slot_key: str):
        """
        Called 1500 ms after socket.add_id().

        If plug-added already fired, on_success was already called from
        _on_plug_added and _pending_embed was cleared — nothing to do.
        Otherwise the XEMBED embed failed silently; try xdotool.
        """
        self._verify_timeout_ids.pop(slot_key, None)

        callbacks = self._pending_embed.pop(slot_key, None)
        if callbacks is None:
            # plug-added already fired and handled — we're done
            return False

        plug_ok = self._plug_added_flags.pop(slot_key, False)
        on_success, on_failure, xid, container = callbacks

        if plug_ok:
            # Rare: plug-added fired but _on_plug_added didn't clear
            # _pending_embed in time (shouldn't happen, but handle it).
            self._method[slot_key] = "socket"
            print(f"[EmbeddingManager] Socket embed confirmed (late): XID {xid}")
            if on_success:
                on_success()
        else:
            print(f"[EmbeddingManager] No plug-added after 1500 ms, "
                  f"trying xdotool fallback: XID {xid}")
            self._remove_socket(slot_key)
            self._xids.pop(slot_key, None)
            self._try_xdotool_then_callback(
                slot_key, xid, container, on_success, on_failure)

        return False  # Don't repeat GLib timeout

    def _try_xdotool_then_callback(self, slot_key: str, xid: int,
                                    container: Gtk.Box,
                                    on_success, on_failure):
        """Attempt xdotool reparenting; call the appropriate callback."""
        if xid and container and self._embed_via_xdotool(slot_key, xid, container):
            self._method[slot_key] = "xdotool"
            print(f"[EmbeddingManager] xdotool fallback succeeded for {slot_key}")
            if on_success:
                on_success()
        else:
            print(f"[EmbeddingManager] All embed methods failed for {slot_key}")
            if on_failure:
                on_failure()

    # =========================================================
    # XEMBED (Gtk.Socket) helpers
    # =========================================================

    def _on_plug_added(self, socket, slot_key):
        """Called when a window is successfully plugged into the socket."""
        try:
            print(f"[EmbeddingManager] Plug added for slot {slot_key}")
            self._plug_added_flags[slot_key] = True

            # Cancel the verification timeout — we already know it succeeded
            timeout_id = self._verify_timeout_ids.pop(slot_key, None)
            if timeout_id:
                GLib.source_remove(timeout_id)

            # Retrieve and clear stored callbacks
            callbacks = self._pending_embed.pop(slot_key, None)
            if callbacks:
                on_success = callbacks[0]
                self._method[slot_key] = "socket"
                if on_success:
                    # Defer to next GTK iteration so the socket finishes drawing first
                    GLib.idle_add(on_success)

            socket.set_can_focus(True)
            socket.grab_focus()

            xid = self._xids.get(slot_key)
            if xid:
                GLib.timeout_add(500, self._force_coordinate_refresh, xid)
        except Exception as e:
            print(f"[EmbeddingManager] Error in plug-added handler for {slot_key}: {e}")

    def _on_plug_removed(self, socket, slot_key):
        """Called when a window is unplugged from the socket."""
        print(f"[EmbeddingManager] Plug removed for slot {slot_key}")
        # Only notify the app when this is *not* an intentional unembed (e.g.
        # the editor window was closed by the user or crashed).
        if slot_key not in self._unembedding:
            callback = self._plug_removed_callbacks.get(slot_key)
            if callback:
                try:
                    GLib.idle_add(callback, slot_key)
                except Exception as e:
                    print(f"[EmbeddingManager] plug-removed callback error for {slot_key}: {e}")
        # Return True to prevent the socket from being destroyed
        return True

    # =========================================================
    # xdotool reparenting fallback
    # =========================================================

    def _embed_via_xdotool(self, slot_key: str, xid: int,
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

            self._xids[slot_key] = xid

            # Track container resize so we can keep the window filling it
            container.connect("size-allocate",
                              self._on_container_resize_xdotool, slot_key)

            print(f"[EmbeddingManager] xdotool reparent succeeded: "
                  f"XID {xid} → container {container_xid}")
            return True

        except Exception as e:
            print(f"[EmbeddingManager] xdotool fallback failed: {e}")
            return False

    def _on_container_resize_xdotool(self, container, allocation, slot_key):
        """Debounced resize handler for xdotool-embedded windows.

        GTK fires size-allocate many times per second during window dragging.
        We cancel the previous pending resize and reschedule 80 ms out so only
        the final size triggers an actual xdotool call.  The resize itself runs
        as a fire-and-forget Popen so it never blocks the GTK main loop.
        """
        old_id = self._resize_timeout_ids.pop(slot_key, None)
        if old_id:
            GLib.source_remove(old_id)

        xid = self._xids.get(slot_key)
        if not xid:
            return

        width = allocation.width
        height = allocation.height

        def do_resize():
            self._resize_timeout_ids.pop(slot_key, None)
            current_xid = self._xids.get(slot_key)
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

        self._resize_timeout_ids[slot_key] = GLib.timeout_add(80, do_resize)

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

    def focus_embedded(self, slot_key: str):
        """Give keyboard focus to the embedded window."""
        socket = self._sockets.get(slot_key)
        if socket:
            try:
                socket.set_can_focus(True)
                socket.grab_focus()
            except Exception as e:
                print(f"[EmbeddingManager] Could not focus socket for {slot_key}: {e}")

        xid = self._xids.get(slot_key)
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
    # Window show / hide for session isolation
    # =========================================================

    def hide_external_window(self, xid: int):
        """Minimize / unmap an external (non-embedded) window so it is not visible."""
        try:
            subprocess.Popen(
                ["xdotool", "windowminimize", str(xid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"[EmbeddingManager] Could not hide window {xid}: {e}")

    def show_external_window(self, xid: int):
        """Restore / map an external (non-embedded) window."""
        try:
            subprocess.Popen(
                ["xdotool", "windowactivate", str(xid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"[EmbeddingManager] Could not show window {xid}: {e}")

    # =========================================================
    # Session lifecycle
    # =========================================================

    def set_plug_removed_callback(self, slot_key: str, callback):
        """Register a callback invoked when a slot's embedded window exits unexpectedly.

        The callback receives ``slot_key`` as its only argument and is called
        on the GTK main thread via ``GLib.idle_add``.
        """
        self._plug_removed_callbacks[slot_key] = callback

    def show_session(self, slot_key: str):
        """Show the container for a slot."""
        container = self._containers.get(slot_key)
        if container:
            container.show_all()

    def hide_session(self, slot_key: str):
        """Hide the container for a slot."""
        container = self._containers.get(slot_key)
        if container:
            container.hide()

    def is_embedded(self, slot_key: str) -> bool:
        """Check if a slot has an embedded window."""
        return slot_key in self._xids

    def get_container(self, slot_key: str) -> Gtk.Box:
        """Get the container for a slot."""
        return self._containers.get(slot_key)

    def get_xid(self, slot_key: str) -> int:
        """Get the embedded XID for a slot, or None."""
        return self._xids.get(slot_key)

    def unembed_window(self, slot_key: str):
        """Remove an embedded window and clean up."""
        # Signal that this is intentional so _on_plug_removed doesn't fire the
        # crash callback.
        self._unembedding.add(slot_key)
        try:
            # Cancel any in-flight verification timeout
            timeout_id = self._verify_timeout_ids.pop(slot_key, None)
            if timeout_id:
                GLib.source_remove(timeout_id)
            self._pending_embed.pop(slot_key, None)
            self._plug_added_flags.pop(slot_key, None)

            # Cancel any pending resize
            resize_id = self._resize_timeout_ids.pop(slot_key, None)
            if resize_id:
                GLib.source_remove(resize_id)

            self._remove_socket(slot_key)
            self._xids.pop(slot_key, None)
            self._method.pop(slot_key, None)
        finally:
            self._unembedding.discard(slot_key)

        # Drop the crash callback once cleanly unembedded
        self._plug_removed_callbacks.pop(slot_key, None)

    def _remove_socket(self, slot_key: str):
        """Remove a socket widget from its container."""
        socket = self._sockets.pop(slot_key, None)
        if socket:
            parent = socket.get_parent()
            if parent:
                parent.remove(socket)
            socket.destroy()

    def remove_session(self, slot_key: str):
        """Fully clean up a slot's embedding resources."""
        self.unembed_window(slot_key)
        container = self._containers.pop(slot_key, None)
        if container:
            parent = container.get_parent()
            if parent:
                parent.remove(container)
            container.destroy()

    def get_all_slot_keys(self) -> list[str]:
        """Return all currently tracked slot keys (with containers)."""
        return list(self._containers.keys())

    def get_slot_keys_for_session(self, session_id: str) -> list[str]:
        """Return all slot keys that belong to a given session."""
        return [k for k in self._containers if k == session_id or k.startswith(f"{session_id}:")]

    def cleanup(self):
        """Clean up all embedding resources."""
        for slot_key in list(self._sockets.keys()):
            self.unembed_window(slot_key)
        for slot_key in list(self._containers.keys()):
            container = self._containers.pop(slot_key)
            container.destroy()
