"""Ideas dialog — manage ideas and their nested todos."""

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

_IDEA_DND_TARGET = Gtk.TargetEntry.new("application/x-codehub-idea", Gtk.TargetFlags.SAME_APP, 0)
_TODO_DND_TARGET = Gtk.TargetEntry.new("application/x-codehub-todo", Gtk.TargetFlags.SAME_APP, 0)

def _new_idea(name: str) -> dict:
    return {
        "id": str(uuid.uuid4())[:8],
        "name": name.strip(),
        "status": "waiting",
        "todos": [],
        "created_at": datetime.now().isoformat(),
    }

def _new_todo(text: str) -> dict:
    return {
        "id": str(uuid.uuid4())[:8],
        "text": text.strip(),
        "status": "waiting",
        "created_at": datetime.now().isoformat(),
    }

class IdeasDialog(Gtk.Window):
    def __init__(self, parent: Gtk.Window, ideas_owner, save_fn: Callable[[], None]):
        super().__init__(title=f"Ideas — {ideas_owner.name}")
        self.set_transient_for(parent)
        self.set_destroy_with_parent(True)
        self.set_default_size(800, 600)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)

        self._owner = ideas_owner
        self._save_fn = save_fn
        self._selected_idea_id: Optional[str] = None
        self._idea_rows: dict[str, "IdeaRow"] = {}
        self._todo_rows: dict[str, "TodoRow"] = {}

        self._build_ui()
        self.show_all()
        self._refresh_ideas()

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.get_style_context().add_class("notes-root")
        self.add(root)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        root.pack_start(paned, True, True, 0)

        # ── Left Pane: Ideas List ──
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        # Add Idea bar
        add_idea_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        add_idea_box.set_margin_start(8)
        add_idea_box.set_margin_end(8)
        add_idea_box.set_margin_top(8)
        add_idea_box.set_margin_bottom(8)
        
        self._idea_entry = Gtk.Entry(placeholder_text="New idea name…")
        self._idea_entry.connect("activate", self._on_add_idea)
        add_idea_box.pack_start(self._idea_entry, True, True, 0)
        
        add_idea_btn = Gtk.Button(label="Add")
        add_idea_btn.connect("clicked", self._on_add_idea)
        add_idea_box.pack_start(add_idea_btn, False, False, 0)
        
        left_box.pack_start(add_idea_box, False, False, 0)
        left_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        self._left_stack = Gtk.Stack()
        
        empty_ideas_lbl = Gtk.Label(label="No ideas yet. Type a name above and press ↵")
        empty_ideas_lbl.get_style_context().add_class("notes-empty")
        self._left_stack.add_named(empty_ideas_lbl, "empty")

        self._ideas_listbox = Gtk.ListBox()
        self._ideas_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._ideas_listbox.connect("row-selected", self._on_idea_selected)
        self._ideas_listbox.drag_dest_set(Gtk.DestDefaults.MOTION | Gtk.DestDefaults.HIGHLIGHT, [_IDEA_DND_TARGET], Gdk.DragAction.MOVE)
        self._ideas_listbox.connect("drag-motion", self._on_drag_motion_idea)
        self._ideas_listbox.connect("drag-drop", self._on_drag_drop_idea)
        self._ideas_listbox.connect("drag-leave", self._on_drag_leave)
        
        scroll_ideas = Gtk.ScrolledWindow()
        scroll_ideas.add(self._ideas_listbox)
        self._left_stack.add_named(scroll_ideas, "list")
        
        left_box.pack_start(self._left_stack, True, True, 0)
        
        paned.pack1(left_box, resize=True, shrink=False)

        # ── Right Pane: Todos List ──
        self._right_stack = Gtk.Stack()
        
        empty_lbl = Gtk.Label(label="No todos yet. Add one above to track progress.")
        empty_lbl.get_style_context().add_class("notes-empty")
        self._right_stack.add_named(empty_lbl, "empty")
        
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        # Add Todo bar
        add_todo_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        add_todo_box.set_margin_start(8)
        add_todo_box.set_margin_end(8)
        add_todo_box.set_margin_top(8)
        add_todo_box.set_margin_bottom(8)
        
        self._todo_entry = Gtk.Entry(placeholder_text="Add a todo to this idea…")
        self._todo_entry.connect("activate", self._on_add_todo)
        add_todo_box.pack_start(self._todo_entry, True, True, 0)
        
        add_todo_btn = Gtk.Button(label="Add")
        add_todo_btn.connect("clicked", self._on_add_todo)
        add_todo_box.pack_start(add_todo_btn, False, False, 0)
        
        right_box.pack_start(add_todo_box, False, False, 0)
        right_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        self._todos_listbox = Gtk.ListBox()
        self._todos_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._todos_listbox.drag_dest_set(Gtk.DestDefaults.MOTION | Gtk.DestDefaults.HIGHLIGHT, [_TODO_DND_TARGET], Gdk.DragAction.MOVE)
        self._todos_listbox.connect("drag-motion", self._on_drag_motion_todo)
        self._todos_listbox.connect("drag-drop", self._on_drag_drop_todo)
        self._todos_listbox.connect("drag-leave", self._on_drag_leave)
        
        scroll_todos = Gtk.ScrolledWindow()
        scroll_todos.add(self._todos_listbox)
        right_box.pack_start(scroll_todos, True, True, 0)
        
        self._right_stack.add_named(right_box, "todos")
        
        paned.pack2(self._right_stack, resize=True, shrink=False)
        paned.set_position(300)

        self._drag_idea_row = None
        self._drag_todo_row = None
        self._drag_highlight_row = None

    def _save(self):
        self._save_fn()

    # ── Ideas Management ──

    def _refresh_ideas(self):
        for row in list(self._ideas_listbox.get_children()):
            self._ideas_listbox.remove(row)
        self._idea_rows.clear()
        for item in self._owner.ideas:
            self._insert_idea_row(item)
        if self._owner.ideas:
            self._left_stack.set_visible_child_name("list")
        else:
            self._left_stack.set_visible_child_name("empty")

    def _insert_idea_row(self, item: dict):
        row = IdeaRow(item, self._on_idea_status, self._on_idea_delete)
        self._idea_rows[item["id"]] = row
        row.drag_handle.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [_IDEA_DND_TARGET], Gdk.DragAction.MOVE)
        row.drag_handle.connect("drag-begin", lambda w, ctx: self._on_drag_begin_idea(row, ctx))
        row.drag_handle.connect("drag-data-get", lambda w, ctx, sel, info, time: sel.set(sel.get_target(), 8, item["id"].encode()))
        row.drag_handle.connect("drag-end", lambda w, ctx: self._on_drag_end())
        self._ideas_listbox.add(row)
        row.show_all()

    def _on_add_idea(self, *_):
        name = self._idea_entry.get_text().strip()
        if not name: return
        item = _new_idea(name)
        self._owner.ideas.append(item)
        self._save()
        self._idea_entry.set_text("")
        self._insert_idea_row(item)
        # Select the newly added idea
        self._ideas_listbox.select_row(self._idea_rows[item["id"]])

    def _on_idea_status(self, idea_id: str, new_status: Optional[str] = None):
        idea = self._find_idea(idea_id)
        if not idea: return
        if new_status:
            idea["status"] = new_status
        else:
            idx = ["waiting", "working", "done"].index(idea["status"])
            idea["status"] = ["waiting", "working", "done"][(idx + 1) % 3]
        self._save()
        self._idea_rows[idea_id].refresh()

    def _on_idea_delete(self, idea_id: str):
        self._owner.ideas[:] = [i for i in self._owner.ideas if i["id"] != idea_id]
        self._save()
        row = self._idea_rows.pop(idea_id, None)
        if row: self._ideas_listbox.remove(row)
        if not self._owner.ideas:
            self._left_stack.set_visible_child_name("empty")
        if self._selected_idea_id == idea_id:
            self._selected_idea_id = None
            self._right_stack.set_visible_child_name("empty")

    def _on_idea_selected(self, listbox, row):
        if not row:
            self._selected_idea_id = None
            self._right_stack.set_visible_child_name("empty")
            return
        self._selected_idea_id = row.item["id"]
        self._right_stack.set_visible_child_name("todos")
        self._refresh_todos()

    def _find_idea(self, idea_id: str) -> Optional[dict]:
        for i in self._owner.ideas:
            if i["id"] == idea_id: return i
        return None

    # ── Todos Management ──

    def _refresh_todos(self):
        for row in list(self._todos_listbox.get_children()):
            self._todos_listbox.remove(row)
        self._todo_rows.clear()
        idea = self._find_idea(self._selected_idea_id)
        if not idea: return
        for todo in idea["todos"]:
            self._insert_todo_row(todo)
        if not idea["todos"]:
            self._right_stack.set_visible_child_name("empty")
        else:
            self._right_stack.set_visible_child_name("todos")

    def _insert_todo_row(self, item: dict):
        row = TodoRow(item, self._on_todo_status, self._on_todo_edit, self._on_todo_delete)
        self._todo_rows[item["id"]] = row
        row.drag_handle.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [_TODO_DND_TARGET], Gdk.DragAction.MOVE)
        row.drag_handle.connect("drag-begin", lambda w, ctx: self._on_drag_begin_todo(row, ctx))
        row.drag_handle.connect("drag-data-get", lambda w, ctx, sel, info, time: sel.set(sel.get_target(), 8, item["id"].encode()))
        row.drag_handle.connect("drag-end", lambda w, ctx: self._on_drag_end())
        self._todos_listbox.add(row)
        row.show_all()

    def _on_add_todo(self, *_):
        if not self._selected_idea_id: return
        idea = self._find_idea(self._selected_idea_id)
        if not idea: return
        text = self._todo_entry.get_text().strip()
        if not text: return
        item = _new_todo(text)
        idea["todos"].append(item)
        self._save()
        self._todo_entry.set_text("")
        self._insert_todo_row(item)

    def _on_todo_status(self, todo_id: str, new_status: Optional[str] = None):
        idea = self._find_idea(self._selected_idea_id)
        if not idea: return
        for t in idea["todos"]:
            if t["id"] == todo_id:
                if new_status:
                    t["status"] = new_status
                else:
                    idx = ["waiting", "working", "done"].index(t["status"])
                    t["status"] = ["waiting", "working", "done"][(idx + 1) % 3]
                self._save()
                self._todo_rows[todo_id].refresh()
                break

    def _on_todo_edit(self, todo_id: str):
        idea = self._find_idea(self._selected_idea_id)
        if not idea: return
        for t in idea["todos"]:
            if t["id"] == todo_id:
                dialog = Gtk.Dialog(title="Edit Todo", transient_for=self, modal=True)
                dialog.set_default_size(400, 100)
                dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
                save_btn = dialog.add_button("Save", Gtk.ResponseType.OK)
                entry = Gtk.Entry(text=t["text"])
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
                        t["text"] = new_txt
                        self._save()
                        self._todo_rows[todo_id].refresh()
                dialog.destroy()
                break

    def _on_todo_delete(self, todo_id: str):
        idea = self._find_idea(self._selected_idea_id)
        if not idea: return
        idea["todos"][:] = [t for t in idea["todos"] if t["id"] != todo_id]
        self._save()
        row = self._todo_rows.pop(todo_id, None)
        if row: self._todos_listbox.remove(row)
        if not idea["todos"]:
            self._right_stack.set_visible_child_name("empty")

    # ── DnD ──

    def _on_drag_begin_idea(self, row, context):
        self._drag_idea_row = row
        Gtk.drag_set_icon_name(context, "emblem-symbolic", 0, 0)

    def _on_drag_begin_todo(self, row, context):
        self._drag_todo_row = row
        Gtk.drag_set_icon_name(context, "emblem-symbolic", 0, 0)

    def _on_drag_end(self):
        self._drag_idea_row = None
        self._drag_todo_row = None
        self._clear_dnd_highlight()

    def _on_drag_motion_idea(self, widget, context, x, y, timestamp):
        if not self._drag_idea_row: return False
        return self._do_drag_motion(widget, context, y, timestamp)

    def _on_drag_motion_todo(self, widget, context, x, y, timestamp):
        if not self._drag_todo_row: return False
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

    def _on_drag_drop_idea(self, widget, context, x, y, timestamp):
        if not self._drag_idea_row: return False
        success = self._do_drag_drop(widget, self._drag_idea_row, y, self._owner.ideas)
        self._clear_dnd_highlight()
        Gtk.drag_finish(context, success, False, timestamp)
        return True

    def _on_drag_drop_todo(self, widget, context, x, y, timestamp):
        if not self._drag_todo_row: return False
        idea = self._find_idea(self._selected_idea_id)
        if not idea: return False
        success = self._do_drag_drop(widget, self._drag_todo_row, y, idea["todos"])
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
                new_data = [r.item for r in widget.get_children() if isinstance(r, (IdeaRow, TodoRow))]
                data_list[:] = new_data
                self._save()
                return True
        return False


class IdeaRow(Gtk.ListBoxRow):
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
        # Add todo count
        n_todos = len(self.item.get("todos", []))
        self._name_lbl.set_markup(f"<b>{self.item['name']}</b> <small>({n_todos})</small>")

class TodoRow(Gtk.ListBoxRow):
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
