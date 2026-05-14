import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

class ProcessKillDialog(Gtk.Dialog):
    """Dialog to confirm killing or restarting processes, with scoping options."""

    def __init__(self, parent, target_name: str, app_pids: list = None, sys_pids: list = None, 
                 all_codehub_pids: list = None, show_target_selector: bool = False,
                 running_targets: dict = None, session_pids: list = None,
                 process_details: list = None, description: str = "",
                 all_codehub_label: str = "Same app/editor in CodeHub"):
        """
        If show_target_selector is True, target_name is ignored and the user
        must select a target from running_targets.
        running_targets is a dict keyed by target id. Each value contains
        name, pids, session_pids, all_codehub_pids, sys_pids, and optional
        process_details rows.
        """
        title = "Process Control" if show_target_selector else f"Process Control: {target_name}"
        super().__init__(
            title=title,
            transient_for=parent,
            modal=True,
            use_header_bar=True
        )
        self.set_default_size(680, 540)
        
        self.app_pids = self._normalize_pids(app_pids)
        self.sys_pids = self._normalize_pids(sys_pids)
        self.all_codehub_pids = self._normalize_pids(all_codehub_pids)
        self.session_pids = self._normalize_pids(session_pids)
        self.process_details = process_details or []
        self.description = description
        self.all_codehub_label = all_codehub_label
        self.show_target_selector = show_target_selector
        self.running_targets = running_targets or {}
        
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Execute", Gtk.ResponseType.OK
        )
        # Give the execute button a destructive styling by default
        action_btn = self.get_widget_for_response(Gtk.ResponseType.OK)
        action_btn.get_style_context().add_class("destructive-action")

        content = self.get_content_area()
        content.set_spacing(12)
        content.set_margin_start(20)
        content.set_margin_end(20)
        content.set_margin_top(20)
        content.set_margin_bottom(20)

        # 1. Target Selection (if needed)
        if self.show_target_selector:
            lbl = Gtk.Label(label="<b>Select target to terminate:</b>", xalign=0)
            lbl.set_use_markup(True)
            content.pack_start(lbl, False, False, 0)

            self.combo_target = Gtk.ComboBoxText()
            for tid, info in self.running_targets.items():
                self.combo_target.append(tid, info["name"])
            
            if self.running_targets:
                self.combo_target.set_active(0)
            self.combo_target.connect("changed", self._on_target_changed)
            content.pack_start(self.combo_target, False, False, 0)
        else:
            lbl = Gtk.Label(label=f"Target: <b>{GLib.markup_escape_text(target_name)}</b>", xalign=0)
            lbl.set_use_markup(True)
            content.pack_start(lbl, False, False, 0)

        self.summary_label = Gtk.Label(xalign=0)
        self.summary_label.set_use_markup(True)
        self.summary_label.set_line_wrap(True)
        content.pack_start(self.summary_label, False, False, 0)

        # 2. Scope Selection
        scope_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.rb_codehub = Gtk.RadioButton.new_with_label_from_widget(None, "Selected target only")
        self.rb_session = Gtk.RadioButton.new_with_label_from_widget(self.rb_codehub, "This session")
        self.rb_all_codehub = Gtk.RadioButton.new_with_label_from_widget(self.rb_codehub, "Same app/editor in CodeHub")
        self.rb_out_session = Gtk.RadioButton.new_with_label_from_widget(self.rb_codehub, "System instances outside this session")
        self.rb_out_codehub = Gtk.RadioButton.new_with_label_from_widget(self.rb_codehub, "System instances outside CodeHub")
        self.rb_all = Gtk.RadioButton.new_with_label_from_widget(self.rb_codehub, "All matching system instances")
        
        scope_box.pack_start(self.rb_codehub, False, False, 0)
        scope_box.pack_start(self.rb_session, False, False, 0)
        scope_box.pack_start(self.rb_all_codehub, False, False, 0)
        scope_box.pack_start(self.rb_out_session, False, False, 0)
        scope_box.pack_start(self.rb_out_codehub, False, False, 0)
        scope_box.pack_start(self.rb_all, False, False, 0)
        content.pack_start(scope_box, False, False, 0)

        # 3. PID details
        details_label = Gtk.Label(label="<b>Known PIDs for the selected target</b>", xalign=0)
        details_label.set_use_markup(True)
        content.pack_start(details_label, False, False, 4)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(150)
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        self.pid_label = Gtk.Label(xalign=0, yalign=0)
        self.pid_label.set_selectable(True)
        self.pid_label.set_line_wrap(True)
        self.pid_label.set_margin_start(8)
        self.pid_label.set_margin_end(8)
        self.pid_label.set_margin_top(8)
        self.pid_label.set_margin_bottom(8)
        scroll.add(self.pid_label)
        content.pack_start(scroll, True, True, 0)

        # 4. Action Selection
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15)
        self.rb_kill = Gtk.RadioButton.new_with_label_from_widget(None, "Kill")
        self.rb_restart = Gtk.RadioButton.new_with_label_from_widget(self.rb_kill, "Restart")
        action_box.pack_start(self.rb_kill, False, False, 0)
        action_box.pack_start(self.rb_restart, False, False, 0)
        
        lbl_action = Gtk.Label(label="<b>Action:</b>", xalign=0)
        lbl_action.set_use_markup(True)
        content.pack_start(lbl_action, False, False, 5)
        content.pack_start(action_box, False, False, 0)

        self._load_selected_target(update=False)
        self._update_counts()
        self.show_all()

    @staticmethod
    def _normalize_pids(pids):
        clean = []
        seen = set()
        for pid in pids or []:
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                continue
            if pid > 0 and pid not in seen:
                clean.append(pid)
                seen.add(pid)
        return clean

    def _on_target_changed(self, combo):
        self._load_selected_target(update=True)

    def _load_selected_target(self, update: bool):
        if not self.show_target_selector or not hasattr(self, "combo_target"):
            return
        tid = self.combo_target.get_active_id()
        if tid and tid in self.running_targets:
            info = self.running_targets[tid]
            self.app_pids = self._normalize_pids(info.get("pids", []))
            self.sys_pids = self._normalize_pids(info.get("sys_pids", []))
            self.all_codehub_pids = self._normalize_pids(info.get("all_codehub_pids", []))
            self.session_pids = self._normalize_pids(info.get("session_pids", []))
            self.process_details = info.get("process_details", [])
            self.description = info.get("description", "")
            self.all_codehub_label = info.get(
                "all_codehub_label", "Same app/editor in CodeHub"
            )
        if update:
            self._update_counts()

    def _update_counts(self):
        # Update radio button labels based on counts
        target_set = set(self.app_pids)
        session_set = set(self.session_pids)
        all_codehub_set = set(self.all_codehub_pids)
        sys_set = set(self.sys_pids)
        
        out_codehub_count = len(sys_set - all_codehub_set)
        out_session_count = len(sys_set - session_set)
        
        self.rb_codehub.set_label(f"Selected target only ({len(target_set)} PIDs)")
        self.rb_session.set_label(f"This session ({len(session_set)} PIDs)")
        self.rb_all_codehub.set_label(f"{self.all_codehub_label} ({len(all_codehub_set)} PIDs)")
        self.rb_out_session.set_label(f"Kill all out of this session ({out_session_count} processes)")
        self.rb_out_codehub.set_label(f"Kill all out of CodeHub ({out_codehub_count} processes)")
        self.rb_all.set_label(f"All matching system instances ({len(sys_set)} processes)")

        self.rb_codehub.set_sensitive(bool(target_set))
        self.rb_session.set_sensitive(bool(session_set))
        self.rb_all_codehub.set_sensitive(bool(all_codehub_set))
        self.rb_out_session.set_sensitive(out_session_count > 0)
        self.rb_out_codehub.set_sensitive(out_codehub_count > 0)
        self.rb_all.set_sensitive(bool(sys_set))

        if not self._selected_scope_available():
            for rb in (
                self.rb_codehub,
                self.rb_session,
                self.rb_all_codehub,
                self.rb_out_session,
                self.rb_out_codehub,
                self.rb_all,
            ):
                if rb.get_sensitive():
                    rb.set_active(True)
                    break

        description = GLib.markup_escape_text(self.description or "")
        self.summary_label.set_markup(
            f"{description}\n"
            f"<small>Target: {len(target_set)} PIDs · Session: {len(session_set)} PIDs · "
            f"CodeHub scope: {len(all_codehub_set)} PIDs · System matches: {len(sys_set)} PIDs</small>"
        )
        self.pid_label.set_text(self._build_pid_text())

    def _selected_scope_available(self) -> bool:
        return (
            (self.rb_codehub.get_active() and self.rb_codehub.get_sensitive()) or
            (self.rb_session.get_active() and self.rb_session.get_sensitive()) or
            (self.rb_all_codehub.get_active() and self.rb_all_codehub.get_sensitive()) or
            (self.rb_out_session.get_active() and self.rb_out_session.get_sensitive()) or
            (self.rb_out_codehub.get_active() and self.rb_out_codehub.get_sensitive()) or
            (self.rb_all.get_active() and self.rb_all.get_sensitive())
        )

    def _build_pid_text(self) -> str:
        if self.process_details:
            lines = []
            for item in self.process_details:
                label = item.get("label", "Process")
                pid = item.get("pid")
                state = item.get("state", "")
                xid = item.get("xid")
                parts = [f"{label}: PID {pid}"]
                if state:
                    parts.append(f"state {state}")
                if xid:
                    parts.append(f"XID {xid}")
                lines.append(" | ".join(parts))
            return "\n".join(lines)

        lines = []
        for label, pids in (
            ("Selected target", self.app_pids),
            ("This session", self.session_pids),
            (self.all_codehub_label, self.all_codehub_pids),
            ("Matching system instances", self.sys_pids),
        ):
            text = ", ".join(str(pid) for pid in pids) if pids else "none"
            lines.append(f"{label}: {text}")
        return "\n".join(lines)

    def get_result(self):
        target_id = None
        if self.show_target_selector:
            target_id = self.combo_target.get_active_id()
            
        if self.rb_codehub.get_active():
            scope = "codehub"
        elif self.rb_session.get_active():
            scope = "session"
        elif self.rb_all_codehub.get_active():
            scope = "all_codehub"
        elif self.rb_all.get_active():
            scope = "all"
        elif self.rb_out_codehub.get_active():
            scope = "out_codehub"
        else:
            scope = "out_session"
            
        action = "kill" if self.rb_kill.get_active() else "restart"
        return target_id, scope, action, False
