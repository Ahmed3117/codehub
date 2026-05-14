import uuid
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from codehub.mode_manager import (
    ModeManager,
    MODE_NORMAL, MODE_FOCUS, MODE_MANAGED, MODE_FOCUS_MANAGED
)

class ModesDialog(Gtk.Dialog):
    """Dialog to configure CodeHub Modes."""

    def __init__(self, parent, mode_mgr: ModeManager, sessions: list):
        super().__init__(
            title="Mode Settings",
            transient_for=parent,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT
        )
        self.set_default_size(500, 600)
        self.get_style_context().add_class("modes-dialog")
        
        self.mode_mgr = mode_mgr
        self.sessions = sorted(sessions, key=lambda s: s.name.lower())
        
        # Working copies
        self._current_mode = self.mode_mgr.current_mode
        self._focus_periods = list(self.mode_mgr.focus_periods)
        self._managed_sessions = list(self.mode_mgr.managed_sessions)
        self._manual_focus_sessions = list(self.mode_mgr.manual_focus_sessions)

        self._build_ui()
        self._update_ui_state()

    def _build_ui(self):
        vbox = self.get_content_area()
        vbox.set_spacing(16)
        vbox.set_margin_top(16)
        vbox.set_margin_bottom(16)
        vbox.set_margin_start(16)
        vbox.set_margin_end(16)

        # Mode Selector
        mode_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        lbl = Gtk.Label(label="<b>Operating Mode</b>", use_markup=True, xalign=0)
        mode_box.pack_start(lbl, False, False, 0)

        self.mode_combo = Gtk.ComboBoxText()
        self.mode_combo.append(MODE_NORMAL, "Normal Mode (All active)")
        self.mode_combo.append(MODE_FOCUS, "Focus Mode (Restrict to selected)")
        self.mode_combo.append(MODE_MANAGED, "Managed Mode (Pomodoro auto-cycles)")
        self.mode_combo.append(MODE_FOCUS_MANAGED, "Focus + Managed Mode")
        self.mode_combo.set_active_id(self._current_mode)
        self.mode_combo.connect("changed", self._on_mode_changed)
        mode_box.pack_start(self.mode_combo, False, False, 0)
        
        vbox.pack_start(mode_box, False, False, 0)

        # Settings Tabs
        self.notebook = Gtk.Notebook()
        
        # Tab 1: Focus
        focus_tab = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        focus_tab.set_border_width(12)
        self._build_focus_tab(focus_tab)
        self.notebook.append_page(focus_tab, Gtk.Label(label="Focus Settings"))

        # Tab 2: Managed
        managed_tab = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        managed_tab.set_border_width(12)
        self._build_managed_tab(managed_tab)
        self.notebook.append_page(managed_tab, Gtk.Label(label="Managed Settings"))

        vbox.pack_start(self.notebook, True, True, 0)

        # Action Buttons
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        save_btn = self.add_button("Save Changes", Gtk.ResponseType.OK)
        save_btn.get_style_context().add_class("suggested-action")

        self.show_all()

    def _build_focus_tab(self, parent_box):
        # Manual Focus Sessions
        lbl = Gtk.Label(label="<b>Manual Focus Sessions</b>", use_markup=True, xalign=0)
        parent_box.pack_start(lbl, False, False, 0)
        
        desc = Gtk.Label(label="Select sessions to enable when Focus Mode is active (and no period is active).", xalign=0)
        desc.set_line_wrap(True)
        desc.get_style_context().add_class("dim-label")
        parent_box.pack_start(desc, False, False, 0)

        scroll1 = Gtk.ScrolledWindow()
        scroll1.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll1.set_min_content_height(150)
        
        self.manual_focus_listbox = Gtk.ListBox()
        self.manual_focus_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        for s in self.sessions:
            row = self._create_session_check_row(s, self._manual_focus_sessions)
            self.manual_focus_listbox.add(row)
            
        scroll1.add(self.manual_focus_listbox)
        parent_box.pack_start(scroll1, True, True, 0)

        # Scheduled Periods
        lbl2 = Gtk.Label(label="<b>Scheduled Focus Periods</b>", use_markup=True, xalign=0)
        lbl2.set_margin_top(12)
        parent_box.pack_start(lbl2, False, False, 0)

        self.periods_listbox = Gtk.ListBox()
        self.periods_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        
        scroll2 = Gtk.ScrolledWindow()
        scroll2.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll2.set_min_content_height(150)
        scroll2.add(self.periods_listbox)
        parent_box.pack_start(scroll2, True, True, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_period_btn = Gtk.Button(label="+ Add Period")
        add_period_btn.connect("clicked", self._on_add_period)
        btn_box.pack_start(add_period_btn, False, False, 0)
        parent_box.pack_start(btn_box, False, False, 0)

        self._refresh_periods_list()

    def _build_managed_tab(self, parent_box):
        lbl = Gtk.Label(label="<b>Managed Sessions Pool</b>", use_markup=True, xalign=0)
        parent_box.pack_start(lbl, False, False, 0)
        
        desc = Gtk.Label(label="Select sessions to cycle through automatically using the Pomodoro timer. (Ignored if Focus+Managed is selected)", xalign=0)
        desc.set_line_wrap(True)
        desc.get_style_context().add_class("dim-label")
        parent_box.pack_start(desc, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(200)
        
        self.managed_listbox = Gtk.ListBox()
        self.managed_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        for s in self.sessions:
            row = self._create_session_check_row(s, self._managed_sessions)
            self.managed_listbox.add(row)
            
        scroll.add(self.managed_listbox)
        parent_box.pack_start(scroll, True, True, 0)

    def _create_session_check_row(self, session, target_list):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        
        chk = Gtk.CheckButton()
        chk.set_active(session.id in target_list)
        
        def on_toggled(button, sid=session.id, lst=target_list):
            if button.get_active():
                if sid not in lst: lst.append(sid)
            else:
                if sid in lst: lst.remove(sid)
                
        chk.connect("toggled", on_toggled)
        
        box.pack_start(chk, False, False, 0)
        box.pack_start(Gtk.Label(label=session.name, xalign=0), True, True, 0)
        row.add(box)
        return row

    def _on_mode_changed(self, combo):
        self._current_mode = combo.get_active_id()
        self._update_ui_state()

    def _update_ui_state(self):
        # Optional: enable/disable tabs based on selected mode
        pass

    def _refresh_periods_list(self):
        for child in self.periods_listbox.get_children():
            self.periods_listbox.remove(child)

        for p in self._focus_periods:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_margin_start(8)
            box.set_margin_end(8)
            box.set_margin_top(4)
            box.set_margin_bottom(4)
            
            lbl = Gtk.Label(label=f"{p.get('name', 'Period')} ({p.get('start_time', '')} - {p.get('end_time', '')})", xalign=0)
            box.pack_start(lbl, True, True, 0)
            
            del_btn = Gtk.Button(label="✕")
            del_btn.set_relief(Gtk.ReliefStyle.NONE)
            del_btn.connect("clicked", lambda b, per=p: self._delete_period(per))
            box.pack_end(del_btn, False, False, 0)
            
            row.add(box)
            self.periods_listbox.add(row)
        
        self.periods_listbox.show_all()

    def _on_add_period(self, btn):
        # A simple dialog to ask for period details
        dialog = PeriodDialog(self, self.sessions)
        if dialog.run() == Gtk.ResponseType.OK:
            period = dialog.get_period()
            self._focus_periods.append(period)
            self._refresh_periods_list()
        dialog.destroy()

    def _delete_period(self, period):
        if period in self._focus_periods:
            self._focus_periods.remove(period)
            self._refresh_periods_list()

    def save_settings(self):
        self.mode_mgr.current_mode = self._current_mode
        self.mode_mgr.managed_sessions = self._managed_sessions
        self.mode_mgr.manual_focus_sessions = self._manual_focus_sessions
        self.mode_mgr.focus_periods = self._focus_periods
        self.mode_mgr.save()
        self.mode_mgr._evaluate_state()


class PeriodDialog(Gtk.Dialog):
    def __init__(self, parent, sessions):
        super().__init__(
            title="Add Focus Period",
            transient_for=parent,
            flags=Gtk.DialogFlags.MODAL
        )
        self.set_default_size(300, 500)
        self.sessions = sessions
        self.selected_sessions = []
        self.excluded_days = []
        
        self._build_ui()

    def _build_ui(self):
        vbox = self.get_content_area()
        vbox.set_spacing(8)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)

        grid = Gtk.Grid(row_spacing=8, column_spacing=8)
        
        grid.attach(Gtk.Label(label="Name:", xalign=0), 0, 0, 1, 1)
        self.name_entry = Gtk.Entry(text="New Period")
        grid.attach(self.name_entry, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="Start Time (HH:MM):", xalign=0), 0, 1, 1, 1)
        self.start_entry = Gtk.Entry(text="09:00")
        grid.attach(self.start_entry, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="End Time (HH:MM):", xalign=0), 0, 2, 1, 1)
        self.end_entry = Gtk.Entry(text="17:00")
        grid.attach(self.end_entry, 1, 2, 1, 1)
        
        vbox.pack_start(grid, False, False, 0)

        # Excluded Days
        lbl_days = Gtk.Label(label="<b>Exclude Days:</b>", use_markup=True, xalign=0)
        lbl_days.set_margin_top(8)
        vbox.pack_start(lbl_days, False, False, 0)
        
        days_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        day_names = ["M", "T", "W", "T", "F", "S", "S"]
        full_day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        
        for i, (name, full_name) in enumerate(zip(day_names, full_day_names)):
            day_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            chk = Gtk.CheckButton()
            chk.set_tooltip_text(full_name)
            
            def on_day_toggled(button, day_idx=i):
                if button.get_active():
                    if day_idx not in self.excluded_days: self.excluded_days.append(day_idx)
                elif day_idx in self.excluded_days:
                    self.excluded_days.remove(day_idx)
            
            chk.connect("toggled", on_day_toggled)
            day_vbox.pack_start(chk, False, False, 0)
            day_vbox.pack_start(Gtk.Label(label=name), False, False, 0)
            days_box.pack_start(day_vbox, True, True, 0)
            
        vbox.pack_start(days_box, False, False, 0)
        
        lbl = Gtk.Label(label="<b>Sessions to Enable:</b>", use_markup=True, xalign=0)
        lbl.set_margin_top(8)
        vbox.pack_start(lbl, False, False, 0)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        
        for s in self.sessions:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            chk = Gtk.CheckButton()
            
            def on_toggled(button, sid=s.id):
                if button.get_active():
                    self.selected_sessions.append(sid)
                elif sid in self.selected_sessions:
                    self.selected_sessions.remove(sid)
                    
            chk.connect("toggled", on_toggled)
            box.pack_start(chk, False, False, 0)
            box.pack_start(Gtk.Label(label=s.name, xalign=0), True, True, 0)
            row.add(box)
            listbox.add(row)
            
        scroll.add(listbox)
        vbox.pack_start(scroll, True, True, 0)

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Add", Gtk.ResponseType.OK)
        
        self.show_all()

    def get_period(self) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "name": self.name_entry.get_text(),
            "start_time": self.start_entry.get_text(),
            "end_time": self.end_entry.get_text(),
            "sessions": self.selected_sessions,
            "excluded_days": sorted(self.excluded_days)
        }
