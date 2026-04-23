"""Notes & Plans dialog — generic notes manager with DnD reordering.

Works with any object that exposes:
  .name   : str   — used in the window title
  .notes  : list  — list of note dicts (mutated in-place)

Persistence is handled by the caller via the save_fn argument so this
dialog is decoupled from SessionRegistry and can serve both per-session
notes and the app-level general notes.
"""

import uuid
from datetime import datetime
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, Pango


# ── Constants ────────────────────────────────────────────────────────────────

NOTE_STATUSES = ["waiting", "working", "done"]

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

# DnD target — restricted to the same widget so notes can't be dragged
# between two open Notes windows.
_NOTE_DND_TARGET = Gtk.TargetEntry.new(
    "application/x-coder3-note", Gtk.TargetFlags.SAME_WIDGET, 0
)


def _new_note(text: str) -> dict:
    return {
        "id": str(uuid.uuid4())[:8],
        "text": text.strip(),
        "status": "waiting",
        "created_at": datetime.now().isoformat(),
    }


# ── NotesDialog ───────────────────────────────────────────────────────────────

class NotesDialog(Gtk.Window):
    """Non-modal window for managing notes and plans.

    Parameters
    ----------
    parent          : transient-for window
    notes_owner     : any object with `.name: str` and `.notes: list`
    save_fn         : zero-argument callable that persists notes_owner
    on_notes_changed: optional callback fired after every mutation so the
                      caller (e.g. the sidebar badge) can refresh itself
    """

    def __init__(
        self,
        parent: Gtk.Window,
        notes_owner,
        save_fn: Callable[[], None],
        *,
        on_notes_changed: Optional[Callable[[], None]] = None,
    ):
        super().__init__(title=f"Notes & Plans — {notes_owner.name}")
        self.set_transient_for(parent)
        self.set_destroy_with_parent(True)
        self.set_default_size(600, 520)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)

        self._owner = notes_owner
        self._save_fn = save_fn
        self._on_notes_changed = on_notes_changed
        self._rows: dict[str, "NoteRow"] = {}

        self._build_ui()
        self.show_all()       # realize the widget tree first …
        self._refresh_list()  # … then populate (Stack child switch works on mapped widget)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.get_style_context().add_class("notes-root")
        self.add(root)

        # ── Add bar ──────────────────────────────────────────────────────────
        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        add_box.get_style_context().add_class("notes-add-bar")

        input_overlay = Gtk.Overlay()
        input_overlay.set_hexpand(True)

        add_scroll = Gtk.ScrolledWindow()
        add_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        add_scroll.set_min_content_height(38)
        add_scroll.set_max_content_height(110)
        add_scroll.get_style_context().add_class("notes-add-scroll")

        self._add_tv = Gtk.TextView()
        self._add_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._add_tv.get_style_context().add_class("notes-add-view")
        self._add_tv.connect("key-press-event", self._on_add_key_press)
        add_scroll.add(self._add_tv)
        input_overlay.add(add_scroll)

        self._add_placeholder = Gtk.Label()
        self._add_placeholder.set_markup(
            '<span foreground="#3b4261">'
            "Add a note or plan…"
            '  <span font_size="small">'
            "Enter = submit · Shift+Enter = new line · Ctrl+Enter = submit"
            "</span></span>"
        )
        self._add_placeholder.set_xalign(0)
        self._add_placeholder.set_yalign(0)
        self._add_placeholder.get_style_context().add_class("notes-add-placeholder")
        input_overlay.add_overlay(self._add_placeholder)
        input_overlay.set_overlay_pass_through(self._add_placeholder, True)

        self._add_tv.get_buffer().connect(
            "changed",
            lambda buf: self._add_placeholder.set_visible(buf.get_char_count() == 0),
        )

        add_box.pack_start(input_overlay, True, True, 0)

        add_btn = Gtk.Button(label="Add")
        add_btn.get_style_context().add_class("suggested-action")
        add_btn.set_valign(Gtk.Align.START)
        add_btn.connect("clicked", self._on_add)
        add_box.pack_start(add_btn, False, False, 0)

        root.pack_start(add_box, False, False, 0)
        root.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        # ── Note list (with empty-state fallback) ─────────────────────────────
        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)

        empty_label = Gtk.Label(label="No notes yet. Add one above.")
        empty_label.get_style_context().add_class("notes-empty")
        self._stack.add_named(empty_label, "empty")

        self._listbox = Gtk.ListBox()
        self._listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._listbox.get_style_context().add_class("notes-list")
        # No sort_func — display order equals list order; user reorders via DnD.

        # Set up the listbox as a DnD drop destination
        self._listbox.drag_dest_set(
            Gtk.DestDefaults.MOTION | Gtk.DestDefaults.DROP,
            [_NOTE_DND_TARGET],
            Gdk.DragAction.MOVE,
        )
        self._listbox.connect("drag-data-received", self._on_dnd_received)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self._listbox)
        self._stack.add_named(scroll, "list")

        root.pack_start(self._stack, True, True, 0)

        # ── Bottom bar ────────────────────────────────────────────────────────
        root.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        btn_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        btn_bar.get_style_context().add_class("notes-btn-bar")

        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", lambda w: self.destroy())
        btn_bar.pack_end(close_btn, False, False, 0)

        root.pack_start(btn_bar, False, False, 0)

    # ── List management ───────────────────────────────────────────────────────

    def _refresh_list(self):
        for row in list(self._listbox.get_children()):
            self._listbox.remove(row)
        self._rows.clear()
        for item in self._owner.notes:
            self._insert_row(item)
        self._update_empty_state()

    def _insert_row(self, item: dict):
        row = NoteRow(
            item=item,
            on_status_change=self._on_cycle_status,
            on_mark=self._on_mark_status,
            on_copy=self._on_copy,
            on_edit=self._on_edit,
            on_delete=self._on_delete,
        )
        self._rows[item["id"]] = row
        self._listbox.add(row)
        row.show_all()

    def _update_empty_state(self):
        name = "list" if self._owner.notes else "empty"
        self._stack.set_visible_child_name(name)

    def _save(self):
        self._save_fn()

    def _emit_changed(self):
        """Notify the caller that notes have been mutated (e.g. to refresh a badge)."""
        if self._on_notes_changed:
            self._on_notes_changed()

    # ── DnD reordering ────────────────────────────────────────────────────────

    def _on_dnd_received(self, widget, context, x, y, data, info, time):
        """Handle a note row being dropped at a new position."""
        src_id = data.get_text()
        if not src_id:
            Gdk.drag_finish(context, False, False, time)
            return

        notes = self._owner.notes
        src_idx = next((i for i, n in enumerate(notes) if n["id"] == src_id), None)
        if src_idx is None:
            Gdk.drag_finish(context, False, False, time)
            return

        # Determine drop target index from the Y coordinate in the listbox
        target_row = widget.get_row_at_y(y)
        if target_row is None:
            # Dropped below all rows — move to the very end
            dst_idx = len(notes) - 1
        else:
            dst_id = getattr(target_row, "item", {}).get("id")
            dst_idx = next(
                (i for i, n in enumerate(notes) if n["id"] == dst_id), src_idx
            )

        if src_idx != dst_idx:
            note = notes.pop(src_idx)
            notes.insert(dst_idx, note)
            self._save()
            self._emit_changed()
            self._refresh_list()

        Gdk.drag_finish(context, True, False, time)

    # ── Input handlers ────────────────────────────────────────────────────────

    def _on_add(self, *_):
        buf = self._add_tv.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        if not text:
            return
        item = _new_note(text)
        self._owner.notes.append(item)
        self._save()
        self._emit_changed()
        buf.set_text("")
        self._add_placeholder.set_visible(True)
        self._insert_row(item)
        self._update_empty_state()
        self._add_tv.grab_focus()

    def _on_add_key_press(self, widget, event):
        """Enter = submit · Shift+Enter = newline · Ctrl+Enter = submit."""
        is_enter = event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter)
        if not is_enter:
            return False
        mods = event.state & Gtk.accelerator_get_default_mod_mask()
        if mods == Gdk.ModifierType.SHIFT_MASK:
            return False   # let the TextView insert a newline
        self._on_add()
        return True

    def _on_cycle_status(self, note_id: str):
        item = self._find_item(note_id)
        if not item:
            return
        idx = NOTE_STATUSES.index(item["status"])
        item["status"] = NOTE_STATUSES[(idx + 1) % len(NOTE_STATUSES)]
        self._save()
        self._emit_changed()
        if note_id in self._rows:
            self._rows[note_id].refresh()

    def _on_mark_status(self, note_id: str, status: str):
        item = self._find_item(note_id)
        if not item:
            return
        item["status"] = status
        self._save()
        self._emit_changed()
        if note_id in self._rows:
            self._rows[note_id].refresh()

    def _on_copy(self, note_id: str):
        item = self._find_item(note_id)
        if not item:
            return
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(item["text"], -1)

    def _on_edit(self, note_id: str):
        item = self._find_item(note_id)
        if not item:
            return

        dialog = Gtk.Dialog(title="Edit Note", transient_for=self, modal=True)
        dialog.set_default_size(480, 240)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        save_btn = dialog.add_button("Save", Gtk.ResponseType.OK)
        save_btn.get_style_context().add_class("suggested-action")

        content = dialog.get_content_area()
        content.get_style_context().add_class("dialog-content")

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_size_request(-1, 140)

        tv = Gtk.TextView()
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.get_buffer().set_text(item["text"])
        tv.get_style_context().add_class("note-edit-view")
        sw.add(tv)
        content.pack_start(sw, True, True, 0)

        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            buf = tv.get_buffer()
            text = buf.get_text(
                buf.get_start_iter(), buf.get_end_iter(), False
            ).strip()
            if text:
                item["text"] = text
                self._save()
                self._emit_changed()
                if note_id in self._rows:
                    self._rows[note_id].refresh()
        dialog.destroy()

    def _on_delete(self, note_id: str):
        self._owner.notes = [n for n in self._owner.notes if n["id"] != note_id]
        self._save()
        self._emit_changed()
        row = self._rows.pop(note_id, None)
        if row:
            self._listbox.remove(row)
        self._update_empty_state()

    def _find_item(self, note_id: str) -> Optional[dict]:
        for item in self._owner.notes:
            if item["id"] == note_id:
                return item
        return None


# ── NoteRow ───────────────────────────────────────────────────────────────────

class NoteRow(Gtk.ListBoxRow):
    """A single note/plan item in the list.

    Left side : ⠿ drag handle (EventBox — drag source for DnD reordering)
    Next      : status badge button
                  - left-click  → cycles waiting → working → done → waiting
                  - right-click → popup menu for explicit pick
    Centre    : note text (wrapping label)
    Right side: Copy | Edit | Delete buttons
    """

    def __init__(self, item: dict, on_status_change, on_mark, on_copy, on_edit, on_delete):
        super().__init__()
        self.item = item
        self._on_mark = on_mark
        self.get_style_context().add_class("note-row")

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.get_style_context().add_class("note-item")

        # ── Drag handle ───────────────────────────────────────────────────────
        # The EventBox is the drag source so dragging is only triggered from
        # the handle area, not from the action buttons or text.
        handle_lbl = Gtk.Label(label="⠿")
        handle_lbl.get_style_context().add_class("note-drag-handle")
        handle_lbl.set_tooltip_text("Drag to reorder")

        handle_box = Gtk.EventBox()
        handle_box.add(handle_lbl)
        handle_box.drag_source_set(
            Gdk.ModifierType.BUTTON1_MASK,
            [_NOTE_DND_TARGET],
            Gdk.DragAction.MOVE,
        )
        handle_box.connect(
            "drag-data-get",
            lambda w, ctx, sel, info, t: sel.set_text(item["id"], -1),
        )
        hbox.pack_start(handle_box, False, False, 0)

        # ── Status badge ──────────────────────────────────────────────────────
        self._status_btn = Gtk.Button()
        self._status_btn.set_relief(Gtk.ReliefStyle.NONE)
        self._status_btn.get_style_context().add_class("note-status-btn")
        self._status_btn.connect("clicked", lambda w: on_status_change(item["id"]))
        self._status_btn.connect("button-press-event", self._on_status_btn_press)
        hbox.pack_start(self._status_btn, False, False, 0)

        # ── Note text ─────────────────────────────────────────────────────────
        self._text_label = Gtk.Label(xalign=0)
        self._text_label.set_line_wrap(True)
        self._text_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._text_label.set_max_width_chars(52)
        self._text_label.get_style_context().add_class("note-text")
        hbox.pack_start(self._text_label, True, True, 0)

        # ── Action buttons ────────────────────────────────────────────────────
        actions = Gtk.Box(spacing=2)
        for label, tooltip, cb in [
            ("📋", "Copy text", lambda w: on_copy(item["id"])),
            ("✎",  "Edit",      lambda w: on_edit(item["id"])),
            ("✕",  "Delete",    lambda w: on_delete(item["id"])),
        ]:
            btn = Gtk.Button(label=label)
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.set_tooltip_text(tooltip)
            btn.get_style_context().add_class("note-action-btn")
            btn.connect("clicked", cb)
            actions.pack_start(btn, False, False, 0)

        hbox.pack_end(actions, False, False, 0)
        self.add(hbox)
        self._refresh_display()

    # ── Status popup ──────────────────────────────────────────────────────────

    def _on_status_btn_press(self, widget, event):
        if event.button == 3:
            self._show_status_menu(event)
            return True
        return False

    def _show_status_menu(self, event):
        menu = Gtk.Menu()
        for status in NOTE_STATUSES:
            menu_item = Gtk.MenuItem(label=_STATUS_LABEL[status])
            menu_item.connect("activate", lambda w, s=status: self._on_mark(self.item["id"], s))
            menu.append(menu_item)
        menu.show_all()
        menu.popup_at_pointer(event)

    # ── Display refresh ───────────────────────────────────────────────────────

    def _refresh_display(self):
        status = self.item["status"]
        ctx = self._status_btn.get_style_context()
        for cls in _STATUS_CSS.values():
            ctx.remove_class(cls)
        ctx.add_class(_STATUS_CSS.get(status, "note-status-waiting"))
        self._status_btn.set_label(_STATUS_LABEL.get(status, "● Waiting"))
        self._status_btn.set_tooltip_text("Click to cycle status · Right-click to pick")
        self._text_label.set_text(self.item["text"])

    def refresh(self):
        """Called externally after the underlying item dict is mutated."""
        self._refresh_display()
