"""Window discovery — finds editor X11 windows by PID, WM_CLASS, and title."""

import subprocess
import time
from typing import Optional

from Xlib import X, display, Xatom


class WindowDiscovery:
    """Discovers and identifies X11 windows belonging to editor instances.
    
    All methods accept an optional *wm_class* parameter so the same discovery
    logic works for VS Code, Cursor, Zed, Sublime, and any other editor whose
    WM_CLASS is known.
    """

    _shared_display = None

    def __init__(self):
        if WindowDiscovery._shared_display is None:
            WindowDiscovery._shared_display = display.Display()
        self._display = WindowDiscovery._shared_display
        self._root = self._display.screen().root

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _get_all_xids_by_class(self, wm_class: str = "code") -> list[int]:
        """
        Find ALL window XIDs for a given WM_CLASS using xdotool.
        Returns all sizes (editor may create small helper windows too).
        """
        if not wm_class:
            return []
        
        # Build case-insensitive regex for xdotool
        regex = "".join(f"[{c.lower()}{c.upper()}]" if c.isalpha() else c for c in wm_class)
        
        try:
            result = subprocess.run(
                ["xdotool", "search", "--class", regex],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                xids = []
                for line in result.stdout.strip().split("\n"):
                    try:
                        xids.append(int(line.strip()))
                    except ValueError:
                        continue
                return xids
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return []

    def _is_window_visible(self, xid: int) -> bool:
        """Return True when a window is currently mapped/visible."""
        try:
            result = subprocess.run(
                ["xwininfo", "-id", str(xid)],
                capture_output=True, text=True, timeout=2
            )
            return result.returncode == 0 and "Map State: IsViewable" in result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _get_main_windows_by_class(self, wm_class: str = "code") -> list[int]:
        """Return only main editor windows (>200×200)."""
        return [xid for xid in self._get_all_xids_by_class(wm_class)
                if self._is_main_window(xid, wm_class)]

    def _get_window_info_by_class(self, wm_class: str = "code") -> dict[int, str]:
        """Return {xid: title} for all main editor windows of the given class."""
        result = {}
        for xid in self._get_main_windows_by_class(wm_class):
            result[xid] = self.get_window_title(xid)
        return result

    def get_visible_main_windows_by_class(self, wm_class: str = "code") -> dict[int, str]:
        """Return only visible main windows for an editor class."""
        return {
            xid: title
            for xid, title in self._get_window_info_by_class(wm_class).items()
            if self._is_window_visible(xid)
        }

    # ------------------------------------------------------------------
    # Public snapshot / discovery API
    # ------------------------------------------------------------------

    def snapshot_windows(self, wm_class: str = "code") -> dict[int, str]:
        """
        Take a snapshot of current editor windows: {xid: title}.
        Used for before/after comparison when launching a new editor.
        """
        return self._get_window_info_by_class(wm_class)

    def snapshot_all_main_windows(self) -> dict[int, str]:
        """Return {xid: title} for ALL main windows (>200x200) regardless of class."""
        result = {}
        try:
            # Get all client windows from root window property
            out = subprocess.run(
                ["xprop", "-root", "_NET_CLIENT_LIST"],
                capture_output=True, text=True, timeout=2
            )
            if out.returncode == 0 and "_NET_CLIENT_LIST(WINDOW): window id # " in out.stdout:
                xids_str = out.stdout.split("#", 1)[1].replace(",", "").split()
                for xid_str in xids_str:
                    try:
                        xid = int(xid_str, 16)
                        if self._is_main_window(xid):
                            result[xid] = self.get_window_title(xid)
                    except ValueError:
                        continue
        except Exception as e:
            print(f"[WindowDiscovery] snapshot_all_main_windows error: {e}")
        return result

    def snapshot_vscode_windows(self) -> dict[int, str]:
        """Backward-compatible alias for snapshot_windows('code')."""
        return self.snapshot_windows("code")

    def find_new_window(self, before_snapshot: dict,
                        wm_class: str = "code",
                        project_path: str = "",
                        timeout: float = 15.0,
                        allow_title_fallback: bool = True) -> Optional[int]:
        """
        Find a new editor window that appeared after launch.

        Detection strategy:
        1. Look for brand new XIDs not in the snapshot
        2. Look for existing XIDs whose title changed to contain the project name
        3. Fallback: accept any window with the project name in the title
        
        Args:
            before_snapshot: {xid: title} snapshot taken before launch
            wm_class: WM_CLASS of the target editor
            project_path: Project directory path for title matching
            timeout: How long to wait (seconds)
        """
        import os
        project_basename = os.path.basename(project_path.rstrip("/")) if project_path else ""
        start = time.time()

        while time.time() - start < timeout:
            current = self._get_window_info_by_class(wm_class)

            # Strategy 1: Brand new windows (new XIDs)
            new_xids = set(current.keys()) - set(before_snapshot.keys())
            if new_xids:
                if project_basename:
                    for xid in new_xids:
                        if project_basename.lower() in current[xid].lower():
                            print(f"[WindowDiscovery] Found NEW window by title: {xid} ({current[xid]})")
                            return xid
                xid = max(new_xids)
                print(f"[WindowDiscovery] Found NEW window: {xid} ({current.get(xid, '')})")
                return xid

            # Strategy 2: Existing window whose title changed to contain project
            if project_basename:
                for xid, title in current.items():
                    old_title = before_snapshot.get(xid, "")
                    if (project_basename.lower() in title.lower() and
                            project_basename.lower() not in old_title.lower()):
                        print(f"[WindowDiscovery] Found window by title CHANGE: {xid}")
                        return xid

            # Strategy 3: After 5 s, accept any window with the project name
            elapsed = time.time() - start
            if allow_title_fallback and elapsed > 5 and project_basename:
                for xid, title in current.items():
                    if project_basename.lower() in title.lower():
                        print(f"[WindowDiscovery] Found window by title match: {xid} ({title})")
                        return xid

            time.sleep(0.5)

        print(f"[WindowDiscovery] Timeout: no new window found for '{project_basename}' (class={wm_class})")
        return None

    def find_new_vscode_window(self, before_snapshot: dict,
                               project_path: str = "",
                               timeout: float = 15.0,
                               allow_title_fallback: bool = True) -> Optional[int]:
        """Backward-compatible alias for find_new_window(wm_class='code')."""
        return self.find_new_window(before_snapshot, wm_class="code",
                                    project_path=project_path, timeout=timeout,
                                    allow_title_fallback=allow_title_fallback)

    def find_window_by_pid(self, pid: int, wm_class: str = "code",
                           project_path: str = "",
                           timeout: float = 15.0,
                           poll_interval: float = 0.5) -> Optional[int]:
        """
        Fallback: find an editor window by PID tree traversal.

        Collects ALL candidate windows and prefers one whose title contains the
        project name, to avoid returning a window belonging to a different session
        when a single-instance editor is shared across sessions.
        """
        import psutil
        import os

        project_basename = os.path.basename(project_path.rstrip("/")) if project_path else ""
        start = time.time()

        while time.time() - start < timeout:
            pids_to_check = {pid}
            try:
                parent = psutil.Process(pid)
                for child in parent.children(recursive=True):
                    pids_to_check.add(child.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            candidates = []
            for p in pids_to_check:
                try:
                    result = subprocess.run(
                        ["xdotool", "search", "--pid", str(p), "--name", ""],
                        capture_output=True, text=True, timeout=2
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        for line in result.stdout.strip().split("\n"):
                            try:
                                xid = int(line.strip())
                                if self._is_main_window(xid, wm_class):
                                    title = self.get_window_title(xid)
                                    candidates.append((xid, title))
                            except ValueError:
                                continue
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    continue

            if candidates:
                # Prefer a window whose title contains the project name
                if project_basename:
                    for xid, title in candidates:
                        if project_basename.lower() in title.lower():
                            print(f"[WindowDiscovery] Found window by PID (title match): {xid} ({title})")
                            return xid
                # Otherwise return the first candidate
                xid, title = candidates[0]
                print(f"[WindowDiscovery] Found window by PID: {xid} ({title})")
                return xid

            time.sleep(poll_interval)

        print(f"[WindowDiscovery] PID-based timeout (PID: {pid})")
        return None

    def find_vscode_window(self, pid: int, project_path: str = "",
                           timeout: float = 15.0,
                           poll_interval: float = 0.5) -> Optional[int]:
        """Backward-compatible alias for find_window_by_pid(wm_class='code')."""
        return self.find_window_by_pid(pid, wm_class="code",
                                       project_path=project_path,
                                       timeout=timeout,
                                       poll_interval=poll_interval)

    # ------------------------------------------------------------------
    # Window property helpers
    # ------------------------------------------------------------------

    def _is_main_window(self, xid: int, wm_class: str = None) -> bool:
        """Check if a window is a main editor window (not a tooltip/helper)."""
        # Protect against root windows or dummy X11 IDs
        if xid <= 1000:
            return False
            
        try:
            window = self._display.create_resource_object("window", xid)
            wc = window.get_wm_class()
            
            if wm_class:
                if not wc:
                    return False
                class_str = " ".join(wc).lower()
                # Accept if wm_class substring is found in any part
                check = wm_class.lower().split(".")[-1]  # e.g. "nautilus" from "org.gnome.nautilus"
                if check not in class_str and wm_class.lower() not in class_str:
                    return False
            elif not wc:
                # Even for generic search, windows should usually have a class
                # but we're less strict here.
                pass
                
            geom = window.get_geometry()
            return geom.width > 200 and geom.height > 200
        except Exception:
            return False

    def _is_vscode_main_window(self, xid: int) -> bool:
        """Backward-compatible alias."""
        return self._is_main_window(xid, "code")

    def get_window_title(self, xid: int) -> str:
        """Get the title of a window."""
        try:
            window = self._display.create_resource_object("window", xid)
            name = window.get_full_property(
                self._display.intern_atom("_NET_WM_NAME"),
                self._display.intern_atom("UTF8_STRING")
            )
            if name:
                return name.value.decode("utf-8", errors="replace")
            name = window.get_wm_name()
            return name or ""
        except Exception:
            return ""

    def get_window_geometry(self, xid: int) -> Optional[dict]:
        """Get window geometry."""
        try:
            window = self._display.create_resource_object("window", xid)
            geom = window.get_geometry()
            return {
                "x": geom.x, "y": geom.y,
                "width": geom.width, "height": geom.height,
            }
        except Exception:
            return None

    def get_window_pid(self, xid: int) -> Optional[int]:
        """Get the PID associated with a window."""
        try:
            window = self._display.create_resource_object("window", xid)
            pid_prop = window.get_full_property(
                self._display.intern_atom("_NET_WM_PID"),
                Xatom.CARDINAL
            )
            if pid_prop and pid_prop.value:
                return pid_prop.value[0]
        except Exception:
            pass
        return None

    def close(self):
        """Clean up the X display connection."""
        try:
            self._display.close()
        except Exception:
            pass
