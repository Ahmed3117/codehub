"""Tasks dialog — manage tasks and their nested subtasks."""

import uuid
from datetime import datetime
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, Pango

_STATUS_LABEL = {
    "waiting": "● Waiting",
    "working": "◐ Working",
    "done":    "✓ Done",
}

_STATUS_CSS = {
    "waiting": "note-status-waiting",
    "working": "note-status-working",
    "done":    "note-status-done",
}

_TASK_DND_TARGET = Gtk.TargetEntry.new("application/x-codehub-task", Gtk.TargetFlags.SAME_APP, 0)
_SUBTASK_DND_TARGET = Gtk.TargetEntry.new("application/x-codehub-subtask", Gtk.TargetFlags.SAME_APP, 0)

def _new_task(name: str) -> dict:
    return {
        "id": str(uuid.uuid4())[:8],
        "name": name.strip(),
        "status": "waiting",
        "subtasks": [],
        "created_at": datetime.now().isoformat(),
    }

def _new_subtask(text: str) -> dict:
    return {
        "id": str(uuid.uuid4())[:8],
        "text": text.strip(),
        "status": "waiting",
        "created_at": datetime.now().isoformat(),
    }

class TasksDialog(Gtk.Window):
    def __init__(self, parent: Gtk.Window, tasks_owner, save_fn: Callable[[], None], *, on_tasks_changed: Optional[Callable[[], None]] = None):
        super().__init__(title=f"Tasks — {tasks_owner.name}")
        self.set_transient_for(parent)
        self.set_destroy_with_parent(True)
        self.set_default_size(800, 600)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)

        self._owner = tasks_owner
        self._save_fn = save_fn
        self._on_tasks_changed = on_tasks_changed
        self._selected_task_id: Optional[str] = None
        self._task_rows: dict[str, "TaskRow"] = {}
        self._subtask_rows: dict[str, "SubtaskRow"] = {}

        self._build_ui()
        self.show_all()
        self._refresh_tasks()

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.get_style_context().add_class("notes-root")
        self.add(root)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        root.pack_start(paned, True, True, 0)

        # ── Left Pane: Tasks List ──
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        # Add Task bar
        add_task_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        add_task_box.set_margin_start(8)
        add_task_box.set_margin_end(8)
        add_task_box.set_margin_top(8)
        add_task_box.set_margin_bottom(8)
        
        self._task_entry = Gtk.Entry(placeholder_text="New task name…")
        self._task_entry.connect("activate", self._on_add_task)
        add_task_box.pack_start(self._task_entry, True, True, 0)
        
        add_task_btn = Gtk.Button(label="Add")
        add_task_btn.connect("clicked", self._on_add_task)
        add_task_box.pack_start(add_task_btn, False, False, 0)
        
        left_box.pack_start(add_task_box, False, False, 0)
        left_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        self._left_stack = Gtk.Stack()
        
        empty_tasks_lbl = Gtk.Label(label="No tasks yet. Type a name above and press ↵")
        empty_tasks_lbl.get_style_context().add_class("notes-empty")
        self._left_stack.add_named(empty_tasks_lbl, "empty")

        self._tasks_listbox = Gtk.ListBox()
        self._tasks_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._tasks_listbox.connect("row-selected", self._on_task_selected)
        self._tasks_listbox.drag_dest_set(Gtk.DestDefaults.MOTION | Gtk.DestDefaults.HIGHLIGHT, [_TASK_DND_TARGET], Gdk.DragAction.MOVE)
        self._tasks_listbox.connect("drag-motion", self._on_drag_motion_task)
        self._tasks_listbox.connect("drag-drop", self._on_drag_drop_task)
        self._tasks_listbox.connect("drag-leave", self._on_drag_leave)
        
        scroll_tasks = Gtk.ScrolledWindow()
        scroll_tasks.add(self._tasks_listbox)
        self._left_stack.add_named(scroll_tasks, "list")
        
        left_box.pack_start(self._left_stack, True, True, 0)
        
        paned.pack1(left_box, resize=True, shrink=False)

        # ── Right Pane: Subtasks List ──
        self._right_stack = Gtk.Stack()
        
        empty_lbl = Gtk.Label(label="No subtasks yet. Add one above to track progress.")
        empty_lbl.get_style_context().add_class("notes-empty")
        self._right_stack.add_named(empty_lbl, "empty")
        
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        # Add Subtask bar
        add_subtask_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        add_subtask_box.set_margin_start(8)
        add_subtask_box.set_margin_end(8)
        add_subtask_box.set_margin_top(8)
        add_subtask_box.set_margin_bottom(8)
        
        self._subtask_entry = Gtk.Entry(placeholder_text="Add a subtask to this task…")
        self._subtask_entry.connect("activate", self._on_add_subtask)
        add_subtask_box.pack_start(self._subtask_entry, True, True, 0)
        
        add_subtask_btn = Gtk.Button(label="Add")
        add_subtask_btn.connect("clicked", self._on_add_subtask)
        add_subtask_box.pack_start(add_subtask_btn, False, False, 0)
        
        right_box.pack_start(add_subtask_box, False, False, 0)
        right_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        self._subtasks_listbox = Gtk.ListBox()
        self._subtasks_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._subtasks_listbox.drag_dest_set(Gtk.DestDefaults.MOTION | Gtk.DestDefaults.HIGHLIGHT, [_SUBTASK_DND_TARGET], Gdk.DragAction.MOVE)
        self._subtasks_listbox.connect("drag-motion", self._on_drag_motion_subtask)
        self._subtasks_listbox.connect("drag-drop", self._on_drag_drop_subtask)
        self._subtasks_listbox.connect("drag-leave", self._on_drag_leave)
        
        scroll_subtasks = Gtk.ScrolledWindow()
        scroll_subtasks.add(self._subtasks_listbox)
        right_box.pack_start(scroll_subtasks, True, True, 0)
        
        self._right_stack.add_named(right_box, "subtasks")
        
        paned.pack2(self._right_stack, resize=True, shrink=False)
        paned.set_position(300)

        self._drag_task_row = None
        self._drag_subtask_row = None
        self._drag_highlight_row = None

    def _save(self):
        self._save_fn()
        if self._on_tasks_changed:
            self._on_tasks_changed()

    # ── Tasks Management ──

    def _refresh_tasks(self):
        for row in list(self._tasks_listbox.get_children()):
            self._tasks_listbox.remove(row)
        self._task_rows.clear()
        for item in self._owner.tasks:
            self._insert_task_row(item)
        if self._owner.tasks:
            self._left_stack.set_visible_child_name("list")
        else:
            self._left_stack.set_visible_child_name("empty")

    def _insert_task_row(self, item: dict):
        row = TaskRow(item, self._on_task_status, self._on_task_delete)
        self._task_rows[item["id"]] = row
        row.drag_handle.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [_TASK_DND_TARGET], Gdk.DragAction.MOVE)
        row.drag_handle.connect("drag-begin", lambda w, ctx: self._on_drag_begin_task(row, ctx))
        row.drag_handle.connect("drag-data-get", lambda w, ctx, sel, info, time: sel.set(sel.get_target(), 8, item["id"].encode()))
        row.drag_handle.connect("drag-end", lambda w, ctx: self._on_drag_end())
        self._tasks_listbox.add(row)
        row.show_all()

    def _on_add_task(self, *_):
        name = self._task_entry.get_text().strip()
        if not name: return
        item = _new_task(name)
        self._owner.tasks.append(item)
        self._save()
        self._task_entry.set_text("")
        self._insert_task_row(item)
        self._tasks_listbox.select_row(self._task_rows[item["id"]])

    def _on_task_status(self, task_id: str, new_status: Optional[str] = None):
        task = self._find_task(task_id)
        if not task: return
        if new_status:
            task["status"] = new_status
        else:
            idx = ["waiting", "working", "done"].index(task["status"])
            task["status"] = ["waiting", "working", "done"][(idx + 1) % 3]
        self._save()
        self._task_rows[task_id].refresh()

    def _on_task_delete(self, task_id: str):
        self._owner.tasks[:] = [t for t in self._owner.tasks if t["id"] != task_id]
        self._save()
        row = self._task_rows.pop(task_id, None)
        if row: self._tasks_listbox.remove(row)
        if not self._owner.tasks:
            self._left_stack.set_visible_child_name("empty")
        if self._selected_task_id == task_id:
            self._selected_task_id = None
            self._right_stack.set_visible_child_name("empty")

    def _on_task_selected(self, listbox, row):
        if not row:
            self._selected_task_id = None
            self._right_stack.set_visible_child_name("empty")
            return
        self._selected_task_id = row.item["id"]
        self._right_stack.set_visible_child_name("subtasks")
        self._refresh_subtasks()

    def _find_task(self, task_id: str) -> Optional[dict]:
        for t in self._owner.tasks:
            if t["id"] == task_id: return t
        return None

    # ── Subtasks Management ──

    def _refresh_subtasks(self):
        for row in list(self._subtasks_listbox.get_children()):
            self._subtasks_listbox.remove(row)
        self._subtask_rows.clear()
        task = self._find_task(self._selected_task_id)
        if not task: return
        for subtask in task.get("subtasks", []):
            self._insert_subtask_row(subtask)
        if not task.get("subtasks"):
            self._right_stack.set_visible_child_name("empty")
        else:
            self._right_stack.set_visible_child_name("subtasks")

    def _insert_subtask_row(self, item: dict):
        row = SubtaskRow(item, self._on_subtask_status, self._on_subtask_edit, self._on_subtask_delete)
        self._subtask_rows[item["id"]] = row
        row.drag_handle.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [_SUBTASK_DND_TARGET], Gdk.DragAction.MOVE)
        row.drag_handle.connect("drag-begin", lambda w, ctx: self._on_drag_begin_subtask(row, ctx))
        row.drag_handle.connect("drag-data-get", lambda w, ctx, sel, info, time: sel.set(sel.get_target(), 8, item["id"].encode()))
        row.drag_handle.connect("drag-end", lambda w, ctx: self._on_drag_end())
        self._subtasks_listbox.add(row)
        row.show_all()

    def _on_add_subtask(self, *_):
        if not self._selected_task_id: return
        task = self._find_task(self._selected_task_id)
        if not task: return
        text = self._subtask_entry.get_text().strip()
        if not text: return
        item = _new_subtask(text)
        if "subtasks" not in task: task["subtasks"] = []
        task["subtasks"].append(item)
        self._save()
        self._subtask_entry.set_text("")
        self._insert_subtask_row(item)
        self._task_rows[self._selected_task_id].refresh()

    def _on_subtask_status(self, subtask_id: str, new_status: Optional[str] = None):
        task = self._find_task(self._selected_task_id)
        if not task: return
        for st in task.get("subtasks", []):
            if st["id"] == subtask_id:
                if new_status:
                    st["status"] = new_status
                else:
                    idx = ["waiting", "working", "done"].index(st["status"])
                    st["status"] = ["waiting", "working", "done"][(idx + 1) % 3]
                self._save()
                self._subtask_rows[subtask_id].refresh()
                break

    def _on_subtask_edit(self, subtask_id: str):
        task = self._find_task(self._selected_task_id)
        if not task: return
        for st in task.get("subtasks", []):
            if st["id"] == subtask_id:
                dialog = Gtk.Dialog(title="Edit Subtask", transient_for=self, modal=True)
                dialog.set_default_size(400, 100)
                dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
                save_btn = dialog.add_button("Save", Gtk.ResponseType.OK)
                entry = Gtk.Entry(text=st["text"])
                entry.set_margin_start(10)
                entry.set_margin_end(10)
                entry.set_margin_top(10)
                entry.set_margin_bottom(10)
                def on_changed(e):
                    save_btn.set_sensitive(bool(e.get_text().strip()))
                entry.connect("changed", on_changed)
                dialog.get_content_area().pack_start(entry, True, True, 0)
                dialog.show_all()
                if dialog.run() == Gtk.ResponseType.OK:
                    new_txt = entry.get_text().strip()
                    if new_txt:
                        st["text"] = new_txt
                        self._save()
                        self._subtask_rows[subtask_id].refresh()
                dialog.destroy()
                break

    def _on_subtask_delete(self, subtask_id: str):
        task = self._find_task(self._selected_task_id)
        if not task: return
        task["subtasks"][:] = [st for st in task.get("subtasks", []) if st["id"] != subtask_id]
        self._save()
        row = self._subtask_rows.pop(subtask_id, None)
        if row: self._subtasks_listbox.remove(row)
        self._task_rows[self._selected_task_id].refresh()
        if not task.get("subtasks"):
            self._right_stack.set_visible_child_name("empty")

    # ── DnD ──

    def _on_drag_begin_task(self, row, context):
        self._drag_task_row = row
        Gtk.drag_set_icon_name(context, "emblem-symbolic", 0, 0)

    def _on_drag_begin_subtask(self, row, context):
        self._drag_subtask_row = row
        Gtk.drag_set_icon_name(context, "emblem-symbolic", 0, 0)

    def _on_drag_end(self):
        self._drag_task_row = None
        self._drag_subtask_row = None
        self._clear_dnd_highlight()

    def _on_drag_motion_task(self, widget, context, x, y, timestamp):
        if not self._drag_task_row: return False
        return self._do_drag_motion(widget, context, y, timestamp)

    def _on_drag_motion_subtask(self, widget, context, x, y, timestamp):
        if not self._drag_subtask_row: return False
        return self._do_drag_motion(widget, context, y, timestamp)

    def _do_drag_motion(self, widget, context, y, timestamp):
        target_row = widget.get_row_at_y(y)
        if self._drag_highlight_row and self._drag_highlight_row is not target_row:
            self._clear_dnd_highlight()
        if target_row:
            alloc = target_row.get_allocation()
            sc = target_row.get_style_context()
            if y < alloc.y + alloc.height // 2:
                sc.remove_class("dnd-drop-below")
                sc.add_class("dnd-drop-above")
            else:
                sc.remove_class("dnd-drop-above")
                sc.add_class("dnd-drop-below")
            self._drag_highlight_row = target_row
        Gdk.drag_status(context, Gdk.DragAction.MOVE, timestamp)
        return True

    def _on_drag_leave(self, widget, context, timestamp):
        self._clear_dnd_highlight()

    def _clear_dnd_highlight(self):
        if self._drag_highlight_row:
            sc = self._drag_highlight_row.get_style_context()
            sc.remove_class("dnd-drop-above")
            sc.remove_class("dnd-drop-below")
            self._drag_highlight_row = None

    def _on_drag_drop_task(self, widget, context, x, y, timestamp):
        if not self._drag_task_row: return False
        success = self._do_drag_drop(widget, self._drag_task_row, y, self._owner.tasks)
        self._clear_dnd_highlight()
        Gtk.drag_finish(context, success, False, timestamp)
        return True

    def _on_drag_drop_subtask(self, widget, context, x, y, timestamp):
        if not self._drag_subtask_row: return False
        task = self._find_task(self._selected_task_id)
        if not task: return False
        success = self._do_drag_drop(widget, self._drag_subtask_row, y, task["subtasks"])
        self._clear_dnd_highlight()
        Gtk.drag_finish(context, success, False, timestamp)
        return True

    def _do_drag_drop(self, widget, drag_row, y, data_list):
        target_row = widget.get_row_at_y(y)
        if target_row and target_row is not drag_row:
            children = widget.get_children()
            try:
                src_pos = children.index(drag_row)
                dst_pos = children.index(target_row)
            except ValueError:
                return False
            
            alloc = target_row.get_allocation()
            drop_after = y > alloc.y + (alloc.height / 2)
            new_pos = dst_pos + (1 if drop_after else 0)
            if src_pos < new_pos: new_pos -= 1

            if src_pos != new_pos:
                widget.remove(drag_row)
                widget.insert(drag_row, new_pos)
                
                # Re-sync list
                new_data = [r.item for r in widget.get_children() if isinstance(r, (TaskRow, SubtaskRow))]
                data_list[:] = new_data
                self._save()
                return True
        return False


class TaskRow(Gtk.ListBoxRow):
    def __init__(self, item: dict, on_status, on_delete):
        super().__init__()
        self.item = item
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.set_margin_start(8)
        hbox.set_margin_end(8)
        hbox.set_margin_top(8)
        hbox.set_margin_bottom(8)

        self.drag_handle = Gtk.EventBox()
        self.drag_handle.add(Gtk.Label(label="⠿"))
        hbox.pack_start(self.drag_handle, False, False, 0)

        self._status_btn = Gtk.Button()
        self._status_btn.set_relief(Gtk.ReliefStyle.NONE)
        self._status_btn.connect("clicked", lambda w: on_status(item["id"]))
        self._status_btn.connect("button-press-event", self._on_status_btn_press, on_status)
        hbox.pack_start(self._status_btn, False, False, 0)

        self._name_lbl = Gtk.Label(xalign=0)
        self._name_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        hbox.pack_start(self._name_lbl, True, True, 0)

        del_btn = Gtk.Button(label="✕")
        del_btn.set_relief(Gtk.ReliefStyle.NONE)
        del_btn.connect("clicked", lambda w: on_delete(item["id"]))
        hbox.pack_end(del_btn, False, False, 0)

        self.add(hbox)
        self.refresh()

    def _on_status_btn_press(self, btn, event, on_status):
        if event.button == 3: # Right click
            menu = Gtk.Menu()
            for st in ["waiting", "working", "done"]:
                menu_item = Gtk.MenuItem(label=_STATUS_LABEL[st])
                menu_item.connect("activate", lambda w, s=st: on_status(self.item["id"], s))
                menu.append(menu_item)
            menu.show_all()
            menu.popup_at_pointer(event)
            return True
        return False

    def refresh(self):
        st = self.item["status"]
        self._status_btn.set_label(_STATUS_LABEL.get(st, "●"))
        ctx = self._status_btn.get_style_context()
        for c in _STATUS_CSS.values(): ctx.remove_class(c)
        ctx.add_class(_STATUS_CSS.get(st, "note-status-waiting"))
        # Add subtask count
        n_subtasks = len(self.item.get("subtasks", []))
        self._name_lbl.set_markup(f"<b>{self.item['name']}</b> <small>({n_subtasks})</small>")

class SubtaskRow(Gtk.ListBoxRow):
    def __init__(self, item: dict, on_status, on_edit, on_delete):
        super().__init__()
        self.item = item
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.set_margin_start(8)
        hbox.set_margin_end(8)
        hbox.set_margin_top(8)
        hbox.set_margin_bottom(8)

        self.drag_handle = Gtk.EventBox()
        self.drag_handle.add(Gtk.Label(label="⠿"))
        hbox.pack_start(self.drag_handle, False, False, 0)

        self._status_btn = Gtk.Button()
        self._status_btn.set_relief(Gtk.ReliefStyle.NONE)
        self._status_btn.connect("clicked", lambda w: on_status(item["id"]))
        self._status_btn.connect("button-press-event", self._on_status_btn_press, on_status)
        hbox.pack_start(self._status_btn, False, False, 0)

        self._text_lbl = Gtk.Label(xalign=0)
        self._text_lbl.set_line_wrap(True)
        hbox.pack_start(self._text_lbl, True, True, 0)

        actions = Gtk.Box(spacing=2)
        edit_btn = Gtk.Button(label="✎")
        edit_btn.set_relief(Gtk.ReliefStyle.NONE)
        edit_btn.connect("clicked", lambda w: on_edit(item["id"]))
        actions.pack_start(edit_btn, False, False, 0)

        del_btn = Gtk.Button(label="✕")
        del_btn.set_relief(Gtk.ReliefStyle.NONE)
        del_btn.connect("clicked", lambda w: on_delete(item["id"]))
        actions.pack_start(del_btn, False, False, 0)

        hbox.pack_end(actions, False, False, 0)
        self.add(hbox)
        self.refresh()

    def _on_status_btn_press(self, btn, event, on_status):
        if event.button == 3: # Right click
            menu = Gtk.Menu()
            for st in ["waiting", "working", "done"]:
                menu_item = Gtk.MenuItem(label=_STATUS_LABEL[st])
                menu_item.connect("activate", lambda w, s=st: on_status(self.item["id"], s))
                menu.append(menu_item)
            menu.show_all()
            menu.popup_at_pointer(event)
            return True
        return False

    def refresh(self):
        st = self.item["status"]
        self._status_btn.set_label(_STATUS_LABEL.get(st, "●"))
        ctx = self._status_btn.get_style_context()
        for c in _STATUS_CSS.values(): ctx.remove_class(c)
        ctx.add_class(_STATUS_CSS.get(st, "note-status-waiting"))
        self._text_lbl.set_text(self.item["text"])
