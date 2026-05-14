import os
import json
import time
from datetime import datetime
from typing import Callable, List, Optional

from gi.repository import GLib
from codehub.utils.constants import MODES_FILE
from codehub.utils.config import ensure_config_dir

# Mode Definitions
MODE_NORMAL = "normal"
MODE_FOCUS = "focus"
MODE_MANAGED = "managed"
MODE_FOCUS_MANAGED = "focus_managed"

class ModeManager:
    """Manages application modes: Normal, Focus, Managed, and Scheduled Periods."""

    def __init__(self, config_dir: str = None):
        self.config_dir = config_dir
        self.modes_file = os.path.join(config_dir, "modes.json") if config_dir else MODES_FILE
        self.current_mode = MODE_NORMAL
        self.focus_periods = []
        self.managed_sessions = []
        self.manual_focus_sessions = []

        # Current computed state
        self.active_focus_period_id = None
        self.currently_enabled_sessions = None # None means all enabled
        
        self._managed_session_index = 0
        self._is_break = False
        
        # Callbacks
        self.on_state_changed: Optional[Callable[[], None]] = None

        self._timer_id = None
        self.load()
        self.start_scheduler()

    def load(self):
        """Load mode settings from disk."""
        ensure_config_dir(self.config_dir) if self.config_dir else ensure_config_dir()
        if os.path.exists(self.modes_file):
            try:
                with open(self.modes_file, "r") as f:
                    data = json.load(f)
                    self.current_mode = data.get("current_mode", MODE_NORMAL)
                    self.focus_periods = data.get("focus_periods", [])
                    self.managed_sessions = data.get("managed_sessions", [])
                    self.manual_focus_sessions = data.get("manual_focus_sessions", [])
                    self._managed_session_index = data.get("managed_session_index", 0)
            except Exception as e:
                print(f"[ModeManager] Failed to load modes: {e}")
        self._evaluate_state()

    def save(self):
        """Save mode settings to disk."""
        ensure_config_dir(self.config_dir) if self.config_dir else ensure_config_dir()
        data = {
            "current_mode": self.current_mode,
            "focus_periods": self.focus_periods,
            "managed_sessions": self.managed_sessions,
            "manual_focus_sessions": self.manual_focus_sessions,
            "managed_session_index": self._managed_session_index
        }
        try:
            with open(self.modes_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[ModeManager] Failed to save modes: {e}")

    def set_mode(self, mode: str):
        """Change the current mode manually."""
        if mode not in (MODE_NORMAL, MODE_FOCUS, MODE_MANAGED, MODE_FOCUS_MANAGED):
            return
        self.current_mode = mode
        self.save()
        self._evaluate_state()

    def update_focus_periods(self, periods: list):
        self.focus_periods = periods
        self.save()
        self._evaluate_state()

    def start_scheduler(self):
        if self._timer_id is None:
            self._timer_id = GLib.timeout_add_seconds(15, self._on_tick)

    def stop_scheduler(self):
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None

    def _on_tick(self):
        self._evaluate_state()
        return True # Keep running

    def _evaluate_state(self):
        """Determine which sessions should be active based on current mode and time."""
        old_enabled = self.currently_enabled_sessions

        # Check for active focus period
        now = datetime.now()
        active_period = None
        
        for p in self.focus_periods:
            if self._is_period_active(p, now):
                active_period = p
                break

        self.active_focus_period_id = active_period["id"] if active_period else None

        if self.current_mode == MODE_NORMAL:
            self.currently_enabled_sessions = None # all enabled
            
        elif self.current_mode == MODE_FOCUS:
            if active_period:
                self.currently_enabled_sessions = list(active_period.get("sessions", []))
            else:
                self.currently_enabled_sessions = list(self.manual_focus_sessions)
                
        elif self.current_mode == MODE_MANAGED:
            if self._is_break:
                self.currently_enabled_sessions = []
            else:
                pool = self.managed_sessions
                if pool:
                    self.currently_enabled_sessions = [pool[self._managed_session_index % len(pool)]]
                else:
                    self.currently_enabled_sessions = []
            
        elif self.current_mode == MODE_FOCUS_MANAGED:
            if self._is_break:
                self.currently_enabled_sessions = []
            else:
                pool = list(active_period.get("sessions", [])) if active_period else list(self.manual_focus_sessions)
                if pool:
                    self.currently_enabled_sessions = [pool[self._managed_session_index % len(pool)]]
                else:
                    self.currently_enabled_sessions = []

        # Notify if changed
        if old_enabled != self.currently_enabled_sessions:
            if self.on_state_changed:
                self.on_state_changed()

    def _is_period_active(self, period: dict, dt: datetime) -> bool:
        """Check if a given focus period is active right now."""
        # Excluded days (0=Mon, 6=Sun)
        if dt.weekday() in period.get("excluded_days", []):
            return False
            
        # Date limits
        if "start_date" in period and period["start_date"]:
            try:
                sd = datetime.strptime(period["start_date"], "%Y-%m-%d").date()
                if dt.date() < sd: return False
            except: pass
        if "end_date" in period and period["end_date"]:
            try:
                ed = datetime.strptime(period["end_date"], "%Y-%m-%d").date()
                if dt.date() > ed: return False
            except: pass

        # Time limits
        try:
            st = datetime.strptime(period["start_time"], "%H:%M").time()
            et = datetime.strptime(period["end_time"], "%H:%M").time()
            curr = dt.time()
            
            if st <= et:
                return st <= curr <= et
            else:
                # Wraps around midnight
                return curr >= st or curr <= et
        except:
            return False

    def is_session_allowed(self, session_id: str) -> bool:
        """Helper for UI to know if a session should be enabled."""
        if self.currently_enabled_sessions is None:
            return True
        return session_id in self.currently_enabled_sessions

    def get_managed_pool(self) -> List[str]:
        """Returns the pool of sessions to cycle through for Managed Mode."""
        if self.current_mode == MODE_FOCUS_MANAGED:
            # Re-evaluate pool based on current time
            now = datetime.now()
            active_period = None
            for p in self.focus_periods:
                if self._is_period_active(p, now):
                    active_period = p
                    break
            return list(active_period.get("sessions", [])) if active_period else list(self.manual_focus_sessions)
        elif self.current_mode == MODE_MANAGED:
            return self.managed_sessions
        return []

    def set_pomodoro_state(self, is_break: bool, cycle: bool = False):
        """Called by Pomodoro timer to enforce break lock or cycle session."""
        self._is_break = is_break
        if cycle and not is_break:
            self._managed_session_index += 1
        self._evaluate_state()
