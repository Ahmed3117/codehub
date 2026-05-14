"""Process manager — launches and monitors editor instances."""

import os
import signal
import subprocess
from typing import Optional

import psutil

import shutil
from codehub.utils.constants import VSCODE_COMMAND, EDITORS, APPS


class ProcessManager:
    """Manages editor process lifecycle.
    
    NOTE: The `code` CLI on Linux is a wrapper script (bash/sh) that signals
    the actual Electron process and exits almost immediately. This means:
    - The PID we get from subprocess.Popen is the wrapper, NOT the editor
    - The wrapper exits within ~1 second, so poll() returns quickly
    - We must NOT use wrapper PID liveness to detect session death
    
    Instead, we track window liveness via XIDs (see app.py health check).
    """

    def __init__(self):
        self._processes: dict[str, subprocess.Popen] = {}  # session_id -> wrapper process
        self._electron_pids: dict[str, int] = {}  # session_id -> actual electron PID
        self._xids: dict[str, int] = {}  # session_id -> X11 window ID (most reliable)

    # ------------------------------------------------------------------
    # Editor launch
    # ------------------------------------------------------------------

    def launch_editor(self, session_id: str, project_path: str,
                      editor: str = "vscode",
                      custom_editor_cmd: str = "",
                      extra_args: list = None,
                      env_vars: dict = None) -> Optional[int]:
        """
        Launch an editor for a session.

        Builds the command from the EDITORS dict (or uses custom_editor_cmd when
        editor == "custom").  Returns the PID of the launched wrapper, or None.
        """
        if session_id in self._processes:
            proc = self._processes[session_id]
            if proc.poll() is None:
                print(f"[ProcessManager] Session {session_id} already has a running editor (PID {proc.pid})")
                return proc.pid

        editor_info = EDITORS.get(editor, EDITORS["vscode"])

        # Resolve the executable command
        if editor == "custom":
            if not custom_editor_cmd:
                print(f"[ProcessManager] Custom editor command is empty for session {session_id}")
                return None
            # Split custom command into parts (e.g. "subl -n")
            base_cmd = custom_editor_cmd.split()
            launch_args = [arg.replace("{path}", project_path)
                           for arg in editor_info["launch_args"]]
            cmd = base_cmd + launch_args
        else:
            command = editor_info["command"]
            if not command:
                print(f"[ProcessManager] Editor '{editor}' has no command configured")
                return None
            
            # Resolve command path (handle cases where it's not in PATH but exists in known locations)
            resolved_command = shutil.which(command)
            if not resolved_command:
                # Try common absolute paths for known editors
                fallbacks = {
                    "trae": ["/usr/share/trae/trae", "/usr/share/trae/bin/trae", "/opt/trae/trae"],
                    "vscode": ["/usr/bin/code", "/usr/local/bin/code"],
                    "cursor": ["/usr/bin/cursor", "/opt/cursor/cursor"],
                }
                for path in fallbacks.get(editor, []):
                    if os.path.exists(path):
                        resolved_command = path
                        print(f"[ProcessManager] Resolved '{command}' to fallback path: {resolved_command}")
                        break
            
            if not resolved_command:
                # If still not found, we'll let Popen try (and likely fail) to get standard error handling
                resolved_command = command

            launch_args = [arg.replace("{path}", project_path)
                           for arg in editor_info["launch_args"]]
            cmd = [resolved_command] + launch_args

        if extra_args:
            cmd.extend(extra_args)

        print(f"[ProcessManager] Launching editor for session {session_id}: {' '.join(cmd)}")

        try:
            env = os.environ.copy()
            if env_vars:
                env.update(env_vars)
            env["CODEHUB_SESSION_ID"] = session_id
            env["GDK_BACKEND"] = "x11"

            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._processes[session_id] = proc
            print(f"[ProcessManager] Editor launched for session {session_id}, PID: {proc.pid}")
            return proc.pid
        except FileNotFoundError:
            print(f"[ProcessManager] Command '{cmd[0]}' not found")
            return None
        except Exception as e:
            print(f"[ProcessManager] Failed to launch editor: {e}")
            return None

    def launch_vscode(self, session_id: str, project_path: str,
                      extra_args: list = None) -> Optional[int]:
        """
        Backward-compatible wrapper — launches VS Code.
        Prefer launch_editor() for new code.
        """
        return self.launch_editor(session_id, project_path,
                                  editor="vscode", extra_args=extra_args)

    # ------------------------------------------------------------------
    # XID / PID tracking
    # ------------------------------------------------------------------

    def set_xid(self, session_id: str, xid: int):
        """Store the X11 window ID for a session (used for liveness checks)."""
        self._xids[session_id] = xid

    def set_electron_pid(self, session_id: str, pid: int):
        """Store the actual Electron PID for a session."""
        self._electron_pids[session_id] = pid

    def close_window(self, xid: int) -> bool:
        """Best-effort close of a single X11 window by XID."""
        try:
            result = subprocess.run(
                ["xdotool", "windowclose", str(xid)],
                capture_output=True, timeout=3
            )
            if result.returncode == 0:
                return True
            stderr = result.stderr.decode(errors="replace").strip()
            print(f"[ProcessManager] Could not close window {xid}: {stderr}")
        except Exception as e:
            print(f"[ProcessManager] Could not close window {xid}: {e}")
        return False

    def forget(self, session_id: str):
        """Drop tracked runtime state for a session without changing app model state."""
        self._processes.pop(session_id, None)
        self._electron_pids.pop(session_id, None)
        self._xids.pop(session_id, None)

    def is_window_alive(self, session_id: str) -> bool:
        """Check if the editor window for a session still exists using xwininfo."""
        xid = self._xids.get(session_id)
        if xid is None:
            return False
        try:
            result = subprocess.run(
                ["xwininfo", "-id", str(xid)],
                capture_output=True, text=True, timeout=2
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def is_alive(self, session_id: str) -> bool:
        """Check if the editor instance for a session is still running."""
        if session_id in self._xids:
            return self.is_window_alive(session_id)

        epid = self._electron_pids.get(session_id)
        if epid:
            try:
                os.kill(epid, 0)
                return True
            except OSError:
                return False

        return False

    def get_pid(self, session_id: str) -> Optional[int]:
        """Get the PID for a session's editor process (prefers electron PID)."""
        epid = self._electron_pids.get(session_id)
        if epid:
            try:
                os.kill(epid, 0)
                return epid
            except OSError:
                pass

        proc = self._processes.get(session_id)
        if proc and proc.poll() is None:
            return proc.pid
        return None

    def get_window_owner_pid(self, xid: int) -> Optional[int]:
        """Return the process PID that owns an X11 window, if discoverable."""
        try:
            result = subprocess.run(
                ["xdotool", "getwindowpid", str(xid)],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(result.stdout.strip().splitlines()[-1])
        except (ValueError, subprocess.TimeoutExpired, FileNotFoundError):
            return None
        return None

    def get_child_pids(self, parent_pid: int) -> list[int]:
        """Get all child PIDs of a process (recursive)."""
        try:
            parent = psutil.Process(parent_pid)
            children = parent.children(recursive=True)
            return [c.pid for c in children]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []

    def expand_pid_tree(self, root_pids: list[int]) -> set[int]:
        """Expand a list of root PIDs to include all their descendants."""
        all_pids = set()
        for pid in root_pids:
            try:
                all_pids.add(pid)
                parent = psutil.Process(pid)
                for child in parent.children(recursive=True):
                    all_pids.add(child.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return all_pids

    def terminate_pid_tree(self, pid: int):
        """Terminate a process and its children."""
        try:
            parent = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return

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
        for proc in alive:
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def terminate_window_owner(self, xid: int) -> bool:
        """Terminate the owning PID tree of a single window."""
        try:
            result = subprocess.run(
                ["xdotool", "getwindowpid", str(xid)],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode != 0 or not result.stdout.strip():
                return False
            pid = int(result.stdout.strip().splitlines()[-1])
        except (ValueError, subprocess.TimeoutExpired, FileNotFoundError):
            return False

        self.terminate_pid_tree(pid)
        return True

    def terminate_windows(self, xids: list[int]):
        """Terminate all processes owning the provided windows."""
        for xid in xids:
            self.close_window(xid)
        for xid in xids:
            self.terminate_window_owner(xid)

    def terminate_editor_processes(self, command: str, extra_names: list = None):
        """Terminate all processes belonging to an editor.

        Matches against *command* (the launch executable name) **and** any
        names in *extra_names*.  The latter is necessary for editors like Zed
        whose CLI launcher exits immediately while the real long-running server
        uses a different binary name (e.g. ``zed-editor`` in libexec/).
        """
        if not command:
            return

        names_to_kill = {command}
        if extra_names:
            names_to_kill.update(extra_names)

        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = proc.info.get("name") or ""
                cmdline = proc.info.get("cmdline") or []
                if (name in names_to_kill or
                        (cmdline and os.path.basename(cmdline[0]) in names_to_kill)):
                    self.terminate_pid_tree(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def terminate_session_processes(self, session_id: str):
        """Kill all processes associated with a session (via CODEHUB_SESSION_ID env var)."""
        pids_to_kill = []
        for proc in psutil.process_iter(["pid", "environ"]):
            try:
                env = proc.info.get("environ") or {}
                if env.get("CODEHUB_SESSION_ID") == session_id:
                    pids_to_kill.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        for pid in pids_to_kill:
            self.terminate_pid_tree(pid)

    def terminate(self, session_id: str):
        """Gracefully terminate an editor session.

        For single-instance editors (Zed, VS Code, etc.) we ONLY close the
        window via xdotool — we do NOT kill the underlying process tree,
        because the same server process is shared across multiple sessions.
        Killing the shared server would destroy every other session's window.
        """
        xid = self._xids.get(session_id)

        if xid:
            if self.close_window(xid):
                print(f"[ProcessManager] Closed editor window for session {session_id}")
            # Intentionally NOT calling terminate_window_owner here.
            # The window close above is sufficient for session teardown.

        proc = self._processes.get(session_id)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        self.forget(session_id)

    def terminate_all(self):
        """Terminate all managed editor processes."""
        while True:
            try:
                session_ids = list(self._processes.keys())
                break
            except RuntimeError:
                pass
        for session_id in session_ids:
            self.terminate(session_id)

    def check_dead_sessions(self) -> list[str]:
        """
        Check for sessions whose editor windows have died.
        Uses XID-based window checking.
        """
        dead = []
        while True:
            try:
                xids_keys = list(self._xids.keys())
                break
            except RuntimeError:
                pass
                
        for session_id in xids_keys:
            if not self.is_window_alive(session_id):
                dead.append(session_id)
                self._xids.pop(session_id, None)
                self._electron_pids.pop(session_id, None)
                self._processes.pop(session_id, None)
        return dead
