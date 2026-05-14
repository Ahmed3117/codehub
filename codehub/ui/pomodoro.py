"""Pomodoro Timer widget — global timer with work/break cycles.

Default cycle: 25 min work → 5 min break × 4, then 15 min long break.
All values are configurable through settings.
"""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Gdk


# Timer states
POMODORO_STOPPED = "stopped"
POMODORO_WORK = "work"
POMODORO_SHORT_BREAK = "short_break"
POMODORO_LONG_BREAK = "long_break"
POMODORO_PAUSED = "paused"


class PomodoroTimer(Gtk.Box):
    """Compact Pomodoro timer widget for the header bar area.

    Parameters
    ----------
    settings : dict
        App settings dict (read for defaults, written on change).
    on_phase_complete : callable or None
        Called with (phase_name, next_phase_name) when a phase finishes.
    """

    def __init__(self, settings: dict = None, on_phase_complete=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.get_style_context().add_class("pomodoro-widget")

        self._settings = settings or {}
        self._on_phase_complete = on_phase_complete
        self.on_state_changed = None

        # Configuration (from settings, with sane defaults)
        self._work_duration = self._settings.get("pomodoro_work", 25) * 60
        self._short_break = self._settings.get("pomodoro_short_break", 5) * 60
        self._long_break = self._settings.get("pomodoro_long_break", 15) * 60
        self._cycles = self._settings.get("pomodoro_cycles", 4)

        # State
        self._state = POMODORO_STOPPED
        self._paused_state = None  # State before pause
        self._remaining = self._work_duration
        self._current_cycle = 1
        self._timer_id = None

        # ── UI ────────────────────────────────────────────────────
        # Phase label
        self._phase_label = Gtk.Label()
        self._phase_label.get_style_context().add_class("pomodoro-phase")
        self._phase_label.set_markup('<small>🍅 Pomodoro</small>')
        self.pack_start(self._phase_label, False, False, 0)

        # Time display
        self._time_label = Gtk.Label()
        self._time_label.get_style_context().add_class("pomodoro-time")
        self._time_label.set_text(self._format_time(self._remaining))
        self.pack_start(self._time_label, False, False, 0)

        # Cycle counter
        self._cycle_label = Gtk.Label()
        self._cycle_label.get_style_context().add_class("pomodoro-cycle")
        self._cycle_label.set_markup(f'<small>{self._current_cycle}/{self._cycles}</small>')
        self.pack_start(self._cycle_label, False, False, 0)

        # Buttons
        self._start_btn = Gtk.Button(label="▶")
        self._start_btn.set_relief(Gtk.ReliefStyle.NONE)
        self._start_btn.set_tooltip_text("Start")
        self._start_btn.get_style_context().add_class("pomodoro-btn")
        self._start_btn.connect("clicked", self._on_start)
        self.pack_start(self._start_btn, False, False, 0)

        self._pause_btn = Gtk.Button(label="⏸")
        self._pause_btn.set_relief(Gtk.ReliefStyle.NONE)
        self._pause_btn.set_tooltip_text("Pause")
        self._pause_btn.get_style_context().add_class("pomodoro-btn")
        self._pause_btn.connect("clicked", self._on_pause)
        self._pause_btn.set_sensitive(False)
        self.pack_start(self._pause_btn, False, False, 0)

        self._reset_btn = Gtk.Button(label="↺")
        self._reset_btn.set_relief(Gtk.ReliefStyle.NONE)
        self._reset_btn.set_tooltip_text("Reset")
        self._reset_btn.get_style_context().add_class("pomodoro-btn")
        self._reset_btn.connect("clicked", self._on_reset)
        self.pack_start(self._reset_btn, False, False, 0)

        self._skip_btn = Gtk.Button(label="⏭")
        self._skip_btn.set_relief(Gtk.ReliefStyle.NONE)
        self._skip_btn.set_tooltip_text("Skip to next phase")
        self._skip_btn.get_style_context().add_class("pomodoro-btn")
        self._skip_btn.connect("clicked", self._on_skip)
        self._skip_btn.set_sensitive(False)
        self.pack_start(self._skip_btn, False, False, 0)

        self._update_display()

    # ── Public API ────────────────────────────────────────────────

    def start(self):
        """Start or resume the timer."""
        if self._state == POMODORO_STOPPED:
            self._state = POMODORO_WORK
            self._remaining = self._work_duration
            self._current_cycle = 1
        elif self._state == POMODORO_PAUSED:
            self._state = self._paused_state or POMODORO_WORK
            self._paused_state = None

        if self.on_state_changed:
            self.on_state_changed(self._state)

        self._start_timer()
        self._update_display()

    def pause(self):
        """Pause the timer."""
        if self._state in (POMODORO_WORK, POMODORO_SHORT_BREAK, POMODORO_LONG_BREAK):
            self._paused_state = self._state
            self._state = POMODORO_PAUSED
            
            if self.on_state_changed:
                self.on_state_changed(self._state)
                
            self._stop_timer()
            self._update_display()

    def reset(self):
        """Reset to initial state."""
        self._stop_timer()
        self._state = POMODORO_STOPPED
        self._paused_state = None
        self._remaining = self._work_duration
        self._current_cycle = 1
        
        if self.on_state_changed:
            self.on_state_changed(self._state)
            
        self._update_display()

    def skip(self):
        """Skip to the next phase."""
        self._advance_phase()

    def update_settings(self, settings: dict):
        """Update timer configuration from settings."""
        self._work_duration = settings.get("pomodoro_work", 25) * 60
        self._short_break = settings.get("pomodoro_short_break", 5) * 60
        self._long_break = settings.get("pomodoro_long_break", 15) * 60
        self._cycles = settings.get("pomodoro_cycles", 4)
        if self._state == POMODORO_STOPPED:
            self._remaining = self._work_duration
            self._update_display()

    # ── Timer internals ───────────────────────────────────────────

    def _start_timer(self):
        if self._timer_id is None:
            self._timer_id = GLib.timeout_add_seconds(1, self._tick)

    def _stop_timer(self):
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None

    def _tick(self):
        """Called every second."""
        if self._state not in (POMODORO_WORK, POMODORO_SHORT_BREAK, POMODORO_LONG_BREAK):
            return False

        self._remaining -= 1
        self._update_display()

        if self._remaining <= 0:
            self._advance_phase()

        return True  # Keep timer running

    def _advance_phase(self):
        """Move to the next phase in the Pomodoro cycle."""
        old_state = self._state

        if self._state == POMODORO_WORK:
            if self._current_cycle >= self._cycles:
                # Long break after completing all cycles
                self._state = POMODORO_LONG_BREAK
                self._remaining = self._long_break
                next_name = "Long Break"
            else:
                self._state = POMODORO_SHORT_BREAK
                self._remaining = self._short_break
                next_name = "Short Break"
        elif self._state == POMODORO_SHORT_BREAK:
            self._current_cycle += 1
            self._state = POMODORO_WORK
            self._remaining = self._work_duration
            next_name = f"Work (Cycle {self._current_cycle})"
        elif self._state == POMODORO_LONG_BREAK:
            # Full pomodoro set complete — reset
            self._current_cycle = 1
            self._state = POMODORO_WORK
            self._remaining = self._work_duration
            next_name = "Work (Cycle 1)"
        else:
            return

        phase_names = {
            POMODORO_WORK: "Work",
            POMODORO_SHORT_BREAK: "Short Break",
            POMODORO_LONG_BREAK: "Long Break",
        }

        if self._on_phase_complete:
            self._on_phase_complete(
                phase_names.get(old_state, "Unknown"),
                next_name,
            )
            
        if self.on_state_changed:
            self.on_state_changed(self._state)

        self._update_display()

    # ── UI updates ────────────────────────────────────────────────

    def _update_display(self):
        """Refresh all UI elements to match current state."""
        self._time_label.set_text(self._format_time(self._remaining))
        self._cycle_label.set_markup(f'<small>{self._current_cycle}/{self._cycles}</small>')

        phase_map = {
            POMODORO_STOPPED: ('🍅 Pomodoro', ''),
            POMODORO_WORK: ('🍅 Work', 'pomodoro-work'),
            POMODORO_SHORT_BREAK: ('☕ Break', 'pomodoro-break'),
            POMODORO_LONG_BREAK: ('🏖 Long Break', 'pomodoro-long-break'),
            POMODORO_PAUSED: ('⏸ Paused', 'pomodoro-paused'),
        }
        text, css = phase_map.get(self._state, ('🍅', ''))
        self._phase_label.set_markup(f'<small>{text}</small>')

        # Update CSS classes on the widget
        ctx = self.get_style_context()
        for _, c in phase_map.values():
            if c:
                ctx.remove_class(c)
        if css:
            ctx.add_class(css)

        # Button sensitivity
        is_running = self._state in (POMODORO_WORK, POMODORO_SHORT_BREAK, POMODORO_LONG_BREAK)
        is_paused = self._state == POMODORO_PAUSED
        is_stopped = self._state == POMODORO_STOPPED

        self._start_btn.set_sensitive(is_stopped or is_paused)
        self._start_btn.set_label("▶" if is_stopped else "▶")
        self._pause_btn.set_sensitive(is_running)
        self._skip_btn.set_sensitive(is_running or is_paused)

    @staticmethod
    def _format_time(seconds: int) -> str:
        """Format seconds as MM:SS."""
        m, s = divmod(max(0, seconds), 60)
        return f"{m:02d}:{s:02d}"

    # ── Button handlers ───────────────────────────────────────────

    def _on_start(self, button):
        self.start()

    def _on_pause(self, button):
        self.pause()

    def _on_reset(self, button):
        self.reset()

    def _on_skip(self, button):
        self.skip()

    def destroy(self):
        self._stop_timer()
        super().destroy()
