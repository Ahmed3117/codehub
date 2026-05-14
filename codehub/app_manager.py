"""App manager — launches and manages workspace apps within sessions.

Each session can have multiple apps beyond its editor.  The AppManager
orchestrates their lifecycle: launch → discover window → EMBED into
the session workspace container → manage.

Apps are embedded using the same pipeline as editors:
  1. XEMBED via Gtk.Socket (works for Electron/GTK apps)
  2. Fallback to xdotool reparenting (works for most X11 apps)
"""

import os
import subprocess
import threading
import time
from typing import Optional, Callable

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from codehub.session_app import SessionApp
from codehub.window_discovery import WindowDiscovery
from codehub.embedding_manager import EmbeddingManager
from codehub.utils.constants import (
    APPS, EDITORS, get_app_info,
    STATE_IDLE, STATE_STARTING, STATE_DISCOVERING,
    STATE_EMBEDDING, STATE_EMBEDDED, STATE_EXTERNAL,
    STATE_CLOSED, STATE_FAILED,
)


class AppManager:
    """Manages workspace apps across all sessions.

    Internally it uses *slot keys* of the form ``session_id:app_id`` to
    interact with :class:`EmbeddingManager` and to track processes.  The
    editor itself is handled by the main app.py code (unchanged); this
    manager handles the **additional** apps.
    """

    def __init__(self, embedding_mgr: EmbeddingManager,
                 window_discovery: WindowDiscovery):
        self._embedding_mgr = embedding_mgr
        self._window_discovery = window_discovery

        # slot_key → subprocess.Popen  (launched process handle)
        self._processes: dict[str, subprocess.Popen] = {}
        # slot_key → SessionApp  (runtime reference)
        self._apps: dict[str, SessionApp] = {}
        # session_id → [SessionApp, …]  (fast lookup)
        self._session_apps: dict[str, list[SessionApp]] = {}
        # XIDs currently managed by any session — used to prevent window
        # stealing when a single-instance app is opened in multiple sessions.
        self._managed_xids: set[int] = set()

        # Callbacks for UI notifications
        self.on_app_state_changed: Optional[Callable] = None  # (session_id, app_id, new_state)
        self.on_app_died: Optional[Callable] = None           # (session_id, app_id)

    # ------------------------------------------------------------------
    # App registration
    # ------------------------------------------------------------------

    def register_app(self, app: SessionApp):
        """Register a SessionApp with the manager (call after creating it)."""
        self._apps[app.slot_key] = app
        apps = self._session_apps.setdefault(app.session_id, [])
        if app not in apps:
            apps.append(app)

    def unregister_app(self, app: SessionApp):
        """Remove a SessionApp from tracking."""
        self._apps.pop(app.slot_key, None)
        apps = self._session_apps.get(app.session_id, [])
        if app in apps:
            apps.remove(app)

    def get_apps(self, session_id: str) -> list[SessionApp]:
        """Return all tracked apps for a session."""
        return list(self._session_apps.get(session_id, []))

    def get_app(self, slot_key: str) -> Optional[SessionApp]:
        """Get a single app by its slot_key."""
        return self._apps.get(slot_key)

    # ------------------------------------------------------------------
    # Launch
    # ------------------------------------------------------------------

    def launch_app(self, app: SessionApp, project_path: str = "", env_vars: dict = None, force_external: bool = False) -> bool:
        """Launch an app and begin window discovery + embedding.

        Returns True if the process was started successfully.
        """
        if app.state in (STATE_STARTING, STATE_DISCOVERING, STATE_EMBEDDING,
                         STATE_EMBEDDED, STATE_EXTERNAL):
            return True  # Already running

        # Look in both APPS and EDITORS
        app_info = get_app_info(app.app_type)

        # Determine command
        if app.app_type == "custom":
            if not app.custom_command:
                print(f"[AppManager] No custom command for app {app.id}")
                app.state = STATE_FAILED
                self._notify_state_changed(app)
                return False
            base_cmd = app.custom_command.split()
        else:
            command = app_info.get("command", "")
            if not command:
                print(f"[AppManager] No command for app type '{app.app_type}'")
                app.state = STATE_FAILED
                self._notify_state_changed(app)
                return False
            base_cmd = [command]

        # Build args — replace {path} with project path
        launch_args = [arg.replace("{path}", project_path)
                       for arg in app_info.get("launch_args", [])]
        cmd = base_cmd + launch_args

        # Append isolation args — these force a separate process instance
        # per session so single-instance apps don't steal each other's windows.
        if not app.shared:
            isolation_args = app_info.get("isolation_args", [])
            for arg in isolation_args:
                cmd.append(
                    arg.replace("{session_id}", app.session_id)
                       .replace("{path}", project_path)
                )

            # Pre-create profile directories for apps that need them
            for arg in cmd:
                if arg.startswith("/tmp/codehub-"):
                    # Could be --user-data-dir=/tmp/... or -profile /tmp/...
                    dir_path = arg.split("=", 1)[-1] if "=" in arg else arg
                    if dir_path.startswith("/tmp/codehub-"):
                        os.makedirs(dir_path, exist_ok=True)

        app.state = STATE_STARTING
        self._notify_state_changed(app)

        print(f"[AppManager] Launching app {app.display_name} for session "
              f"{app.session_id}: {' '.join(cmd)}")

        try:
            env = os.environ.copy()
            if env_vars:
                env.update(env_vars)
            env["CODEHUB_SESSION_ID"] = app.session_id
            env["GDK_BACKEND"] = "x11"

            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._processes[app.slot_key] = proc
            app.pid = proc.pid
            if proc.pid not in app.spawned_pids:
                app.spawned_pids.append(proc.pid)

            if force_external:
                app.state = STATE_EXTERNAL
                self._notify_state_changed(app)
                return True

            # Start window discovery in a background thread
            wm_class = app_info.get("wm_class", "")
            if app.app_type == "custom" and app.custom_wm_class:
                wm_class = app.custom_wm_class

            thread = threading.Thread(
                target=self._discover_window,
                args=(app, wm_class),
                daemon=True,
            )
            thread.start()
            return True

        except FileNotFoundError:
            print(f"[AppManager] Command '{cmd[0]}' not found")
            app.state = STATE_FAILED
            self._notify_state_changed(app)
            return False
        except Exception as e:
            print(f"[AppManager] Failed to launch app: {e}")
            app.state = STATE_FAILED
            self._notify_state_changed(app)
            return False

    # ------------------------------------------------------------------
    # Window discovery (background thread)
    # ------------------------------------------------------------------

    def _discover_window(self, app: SessionApp, wm_class: str):
        """Background thread: discover the app's X11 window."""
        try:
            # Update state to DISCOVERING on main thread
            GLib.idle_add(self._set_app_state, app, STATE_DISCOVERING)

            # Take a snapshot of existing windows with this class BEFORE launch,
            # PLUS all XIDs already managed by other sessions.  This prevents
            # the discovery from "stealing" a window embedded elsewhere.
            before = set(self._managed_xids)  # copy
            if wm_class:
                try:
                    before |= set(
                        self._window_discovery.snapshot_windows(wm_class).keys()
                    )
                except Exception:
                    pass

            # Wait for a new window to appear
            timeout = 20
            start = time.time()
            xid = None

            while time.time() - start < timeout:
                if wm_class:
                    try:
                        # Find ANY new window for this class, even if not yet mapped
                        current = self._window_discovery.snapshot_windows(wm_class)
                        # Exclude both pre-existing AND managed XIDs
                        new_xids = set(current.keys()) - before - self._managed_xids
                        if new_xids:
                            # Pick the newest (highest XID)
                            xid = max(new_xids)
                            break
                    except Exception:
                        pass
                time.sleep(0.5)

            # Fallback: PID-based discovery
            if xid is None and wm_class and app.pid:
                try:
                    xid = self._window_discovery.find_window_by_pid(
                        app.pid, wm_class=wm_class, timeout=5)
                    # Reject XIDs already managed by another session/app
                    if xid and xid in self._managed_xids:
                        print(f"[AppManager] PID fallback found XID {xid} but it is already "
                              f"managed by another slot; discarding for {app.display_name}")
                        xid = None
                except Exception:
                    pass

            if xid:
                print(f"[AppManager] Window discovered for {app.display_name}: XID {xid}")
                GLib.idle_add(self._on_window_discovered, app, xid)
            else:
                print(f"[AppManager] Window discovery FAILED for {app.display_name}")
                GLib.idle_add(self._on_discovery_failed, app)

        except Exception as e:
            print(f"[AppManager] Window discovery error for {app.display_name}: {e}")
            GLib.idle_add(self._on_discovery_failed, app)

    # ------------------------------------------------------------------
    # Embedding (main thread — called after discovery)
    # ------------------------------------------------------------------

    def _on_window_discovered(self, app: SessionApp, xid: int):
        """Main thread: window found — now EMBED it into the workspace container."""
        app.xid = xid
        app.window_pid = self._window_discovery.get_window_pid(xid)
        if app.window_pid and app.window_pid not in app.spawned_pids:
            app.spawned_pids.append(app.window_pid)
        self._managed_xids.add(xid)  # Prevent other sessions from grabbing this XID
        self._embedding_mgr.register_xid(xid, app.slot_key)
        app.state = STATE_EMBEDDING
        self._notify_state_changed(app)

        slot_key = app.slot_key
        container = self._embedding_mgr.get_container(slot_key)

        if container is None:
            print(f"[AppManager] No container for {app.display_name} "
                  f"(slot_key={slot_key}), running in external mode")
            app.state = STATE_EXTERNAL
            self._notify_state_changed(app)
            return

        print(f"[AppManager] Embedding {app.display_name} (XID {xid}) "
              f"into container for slot {slot_key}")

        def on_embed_success():
            print(f"[AppManager] ✓ {app.display_name} embedded successfully")
            app.state = STATE_EMBEDDED
            self._notify_state_changed(app)

        def on_embed_failure():
            print(f"[AppManager] ✗ {app.display_name} embed failed, "
                  f"falling back to managed external mode")
            # The window stays floating but we still track and control it
            app.state = STATE_EXTERNAL
            self._notify_state_changed(app)
            # Even in external mode, remove decorations and track the XID
            self._embedding_mgr._undecorate_window(xid)

        # Use the same embed pipeline as editors: XEMBED → xdotool fallback
        self._embedding_mgr.embed_window(
            slot_key, xid, container,
            on_success=on_embed_success,
            on_failure=on_embed_failure,
        )

        # Set plug-removed callback so we detect if the app window dies
        self._embedding_mgr.set_plug_removed_callback(
            slot_key, self._on_app_plug_removed)

    def _on_discovery_failed(self, app: SessionApp):
        """Main thread: window discovery timed out."""
        app.state = STATE_FAILED
        self._notify_state_changed(app)
        print(f"[AppManager] Window discovery failed for {app.display_name}")

    def _on_app_plug_removed(self, slot_key: str):
        """Called when an embedded app window exits unexpectedly."""
        app = self._apps.get(slot_key)
        if app and app.state not in (STATE_IDLE, STATE_CLOSED):
            print(f"[AppManager] App {app.display_name} window died (plug removed)")
            if app.xid:
                self._embedding_mgr.unregister_xid(app.xid, slot_key)
                self._managed_xids.discard(app.xid)
            app.state = STATE_CLOSED
            app.pid = None
            app.window_pid = None
            app.xid = None
            self._processes.pop(slot_key, None)
            self._notify_state_changed(app)

    def _set_app_state(self, app: SessionApp, state: str):
        """Helper: set app state and notify (safe for GLib.idle_add)."""
        app.state = state
        self._notify_state_changed(app)

    # ------------------------------------------------------------------
    # Stop / terminate
    # ------------------------------------------------------------------

    def stop_app(self, app: SessionApp):
        """Stop a running app."""
        slot_key = app.slot_key

        if app.xid:
            self._embedding_mgr.unregister_xid(app.xid, slot_key)
            self._managed_xids.discard(app.xid)

        # Unembed first (before closing the window) to prevent GTK errors
        self._embedding_mgr.unembed_window(slot_key)

        # Close the window if we have an XID
        if app.xid:
            try:
                subprocess.run(
                    ["xdotool", "windowclose", str(app.xid)],
                    capture_output=True, timeout=3
                )
                # Fallback: kill the process owning this window
                try:
                    res = subprocess.run(
                        ["xdotool", "getwindowpid", str(app.xid)],
                        capture_output=True, text=True, timeout=2
                    )
                    if res.returncode == 0 and res.stdout.strip():
                        win_pid = int(res.stdout.strip())
                        if win_pid not in app.spawned_pids:
                            app.spawned_pids.append(win_pid)
                except Exception:
                    pass
            except Exception:
                pass

        # Terminate the process using tracked PIDs
        proc = self._processes.pop(slot_key, None)
        import psutil
        for pid in list(app.spawned_pids):
            try:
                parent = psutil.Process(pid)
                children = parent.children(recursive=True)
                for child in reversed(children):
                    try:
                        child.terminate()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                try:
                    parent.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                _, alive = psutil.wait_procs(children + [parent], timeout=2)
                for p in alive:
                    try:
                        p.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        app.spawned_pids.clear()

        app.pid = None
        app.window_pid = None
        app.xid = None
        app.state = STATE_CLOSED
        self._notify_state_changed(app)

    def stop_all_apps(self, session_id: str):
        """Stop all apps in a session."""
        for app in list(self.get_apps(session_id)):
            if app.state not in (STATE_IDLE, STATE_CLOSED, STATE_FAILED):
                self.stop_app(app)

    def remove_app(self, app: SessionApp):
        """Stop and fully clean up an app."""
        self.stop_app(app)
        self._embedding_mgr.remove_session(app.slot_key)
        self.unregister_app(app)

    # ------------------------------------------------------------------
    # Session isolation — show / hide
    # ------------------------------------------------------------------

    def hide_session_apps(self, session_id: str):
        """Hide all app windows for a session (both embedded containers
        and external floating windows)."""
        for app in self.get_apps(session_id):
            if app.state == STATE_EMBEDDED:
                # Embedded apps are inside the workspace stack, which is
                # already hidden by the content area switch.  Nothing extra
                # needed.
                pass
            elif app.xid and app.state == STATE_EXTERNAL:
                self._embedding_mgr.hide_external_window(app.xid)

    def show_session_apps(self, session_id: str):
        """Show all app windows for a session."""
        for app in self.get_apps(session_id):
            if app.state == STATE_EMBEDDED:
                # Container visibility handled by workspace stack switch
                pass
            elif app.xid and app.state == STATE_EXTERNAL:
                self._embedding_mgr.show_external_window(app.xid)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def check_dead_apps(self) -> list[tuple[str, str]]:
        """Check for apps whose windows have died.

        Returns a list of (session_id, app_id) tuples for dead apps.
        """
        dead = []
        for slot_key, app in list(self._apps.items()):
            if app.state not in (STATE_EMBEDDED, STATE_EXTERNAL, STATE_STARTING):
                continue
            if app.xid:
                try:
                    result = subprocess.run(
                        ["xwininfo", "-id", str(app.xid)],
                        capture_output=True, text=True, timeout=2
                    )
                    if result.returncode != 0:
                        dead.append((app.session_id, app.id))
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    pass
        return dead

    def mark_app_dead(self, session_id: str, app_id: str):
        """Mark an app as closed when its window died."""
        slot_key = f"{session_id}:{app_id}"
        app = self._apps.get(slot_key)
        if app and app.state not in (STATE_IDLE, STATE_CLOSED):
            print(f"[AppManager] App {app.display_name} window died")
            if app.xid:
                self._embedding_mgr.unregister_xid(app.xid, slot_key)
                self._managed_xids.discard(app.xid)
            app.state = STATE_CLOSED
            app.pid = None
            app.window_pid = None
            app.xid = None
            self._processes.pop(slot_key, None)
            self._embedding_mgr.unembed_window(slot_key)
            self._notify_state_changed(app)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _notify_state_changed(self, app: SessionApp):
        """Notify the UI about a state change."""
        if self.on_app_state_changed:
            try:
                self.on_app_state_changed(app.session_id, app.id, app.state)
            except Exception as e:
                print(f"[AppManager] State change callback error: {e}")

    def cleanup(self):
        """Clean up all app resources."""
        for slot_key in list(self._processes.keys()):
            app = self._apps.get(slot_key)
            if app:
                self.stop_app(app)
        self._apps.clear()
        self._session_apps.clear()
        self._processes.clear()
