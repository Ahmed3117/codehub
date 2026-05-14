# CodeHub Improvement Plan

This plan covers four requested changes:

1. Add local accounts so multiple people can use the same computer without sharing sessions, plans, tasks, notes, modes, or settings.
2. Make the interface smaller, more compact, and visually cleaner.
3. Support mouse drag-and-drop reordering for apps inside a session panel.
4. Support right-click renaming for opened apps inside a session panel.

The app is currently a GTK3 Python application. Main state is stored under `~/.config/codehub`, and the key code paths are:

- `codehub/utils/constants.py`: config file paths and app defaults.
- `codehub/utils/config.py`: settings load/save.
- `codehub/session_registry.py`: sessions, plans, tasks, workspace apps.
- `codehub/group_registry.py`: sidebar groups.
- `codehub/app_notes.py`: general app-level notes, plans, and ideas.
- `codehub/mode_manager.py`: focus/managed mode persistence.
- `codehub/app.py`: application boot, registries, windows, callbacks.
- `codehub/ui/session_workspace.py`: app tabs, app panel, drag/drop, right-click menu.
- `codehub/ui/styles.css`: visual density and theme.

## Goals

- Keep each account isolated in its own data directory.
- Allow two app windows to run at the same time with different logged-in accounts.
- Avoid showing or loading one account's sessions while another account is active.
- Keep account management local and simple: account name plus password.
- Reduce visual size across the header, sidebar, rows, buttons, tabs, and dialogs.
- Make app tab reordering and renaming feel natural with mouse interactions.
- Preserve existing user data through a migration path.

## Non-Goals

- Cloud sync.
- Online authentication.
- Multi-machine account sync.
- OS-level user integration.
- Strong security against an attacker who already controls the Linux user account.
- Rewriting the app in a different UI framework.

## Phase 1: Account Data Model

### Storage Layout

Current storage:

```text
~/.config/codehub/
  sessions.json
  groups.json
  settings.json
  modes.json
  general_notes.json
```

New storage:

```text
~/.config/codehub/
  accounts.json
  active_account.json
  accounts/
    <account_id>/
      sessions.json
      groups.json
      settings.json
      modes.json
      general_notes.json
```

`accounts.json` should contain account metadata only:

```json
[
  {
    "id": "ahmed-8f3a21",
    "name": "Ahmed",
    "password_hash": "...",
    "password_salt": "...",
    "created_at": "2026-05-12T12:00:00",
    "updated_at": "2026-05-12T12:00:00"
  }
]
```

`active_account.json` should contain only the last account selected:

```json
{
  "account_id": "ahmed-8f3a21"
}
```

### Password Handling

- Use `hashlib.pbkdf2_hmac("sha256", ...)` with a per-account random salt from `secrets.token_bytes`.
- Store only salt and hash, never plaintext.
- Add password verification on login.
- Add password confirmation on account delete.
- Add a password update flow under account settings.

### New Module

Create `codehub/account_manager.py`.

Responsibilities:

- Ensure account root directories exist.
- Load/save `accounts.json`.
- Create account.
- Rename account.
- Change password.
- Delete account and its data directory.
- Verify password.
- Load/save last active account.
- Return the config directory for the selected account.

Proposed API:

```python
class AccountManager:
    def get_accounts(self) -> list[Account]: ...
    def create_account(self, name: str, password: str) -> Account: ...
    def update_account(self, account_id: str, name: str | None, password: str | None) -> Account: ...
    def delete_account(self, account_id: str, password: str) -> None: ...
    def verify_password(self, account_id: str, password: str) -> bool: ...
    def get_account_config_dir(self, account_id: str) -> str: ...
    def get_last_active_account_id(self) -> str | None: ...
    def set_last_active_account_id(self, account_id: str | None) -> None: ...
```

## Phase 2: Account-Aware Persistence

### Problem

Most registries currently import global paths from `codehub/utils/constants.py`, such as `SESSIONS_FILE`, `GROUPS_FILE`, and `MODES_FILE`. That makes all users share the same data.

### Target Design

Every registry should receive a `config_dir` or file path from the app after login.

Update these modules:

- `SessionRegistry(config_dir)`
- `GroupRegistry(config_dir)`
- `TemplateRegistry(config_dir)` if it persists user data.
- `AppNotesRegistry(config_dir)`
- `SessionHistoryRegistry(config_dir)` if it persists user data.
- `ModeManager(config_dir)`
- `load_settings(config_dir)`
- `save_settings(settings, config_dir)`

Keep default behavior pointed at `~/.config/codehub` for tests or simple imports, but the running app should always pass the active account directory after login.

### Migration

On first launch after account support:

1. If `accounts.json` does not exist and old root-level data files exist, show an account creation/import dialog.
2. Ask for account name and password.
3. Create the first account.
4. Move or copy old root files into `accounts/<account_id>/`.
5. Leave a backup copy if using copy-first migration:

```text
~/.config/codehub/legacy-backup-YYYYMMDD-HHMMSS/
```

### Files To Migrate

- `sessions.json`
- `groups.json`
- `settings.json`
- `modes.json`
- `general_notes.json`
- any history/template files found in the current config directory

## Phase 3: Account UI

### Startup Flow

When the app opens:

1. Load CSS.
2. Load accounts.
3. If no accounts exist, show `Create First Account`.
4. If accounts exist, show `Choose Account`.
5. User selects account and enters password.
6. App initializes registries using that account's config directory.
7. Main window shows only that account's sessions and account-owned data.

### Dialogs To Add

Create `codehub/ui/account_dialog.py`.

Dialogs:

- `AccountChooserDialog`
  - List accounts.
  - Password entry.
  - Login button.
  - Create Account button.
  - Edit Account button.
  - Delete Account button.

- `AccountFormDialog`
  - Account name.
  - Password.
  - Confirm password.
  - Used for create and update.

- `AccountDeleteDialog`
  - Shows account name.
  - Requires password.
  - Warns that sessions, plans, tasks, notes, groups, settings, and modes will be deleted.

### Header / Menu Changes

Add an account menu to the header bar:

- Current account name.
- Switch Account.
- Edit Account.
- Change Password.
- Logout.

Logout behavior:

1. Stop active timers.
2. Persist current window/settings for the current account.
3. Stop or detach embedded/session apps after confirmation.
4. Clear in-memory registries and workspace widgets.
5. Return to account chooser.

Switch account behavior:

1. Same as logout.
2. Open account chooser.
3. Initialize registries for selected account.
4. Repopulate sidebar/content with selected account data.

### Multiple Accounts Open Side-by-Side

Requirement: two screens may run two accounts beside each other.

Implementation rule:

- Do not use GTK application single-instance behavior if it prevents a second process/window.
- Current `CodeHubApp` uses `Gio.ApplicationFlags.FLAGS_NONE`, which may activate an existing app instance for the same `APP_ID`.
- Change to a mode that allows separate windows/processes, or use an account-specific application id/session id when launching.
- Ensure each process holds its own active account directory and does not overwrite another process's in-memory state.

Acceptance check:

- Launch CodeHub twice.
- Login as Account A in the first window.
- Login as Account B in the second window.
- Create/edit sessions in both windows.
- Restart and verify each account still sees only its own data.

## Phase 4: Compact UI Redesign

### Current Visual Issues

The current CSS uses large paddings, tall rows, rounded cards, large buttons, and wide spacing:

- Header min-height is around `56px`.
- Sidebar width defaults to `280px`.
- Session rows use large margins and `16px 20px` padding.
- Buttons are commonly `32px` to `40px`.
- App tabs have generous margins and icon/name spacing.

### Compact Design Targets

- Default sidebar width: `220px` to `240px`.
- Header height: `40px` to `44px`.
- Session row vertical padding: `8px` to `10px`.
- App tab height: `28px` to `32px`.
- Icon/action buttons: `26px` to `30px`.
- Border radius: keep most controls at `6px` to `8px`.
- Reduce gradients and heavy shadows.
- Keep text readable, but use tighter hierarchy:
  - session name: `13px`
  - path: `10px`
  - status: `9px` or compact icon state

### CSS Work

Update `codehub/ui/styles.css`:

- Header bar padding and min-height.
- Header button padding, radius, min-height.
- Sidebar header padding.
- Session list padding and row margin.
- Session item padding and indicator size.
- Action button dimensions.
- App bar height and app tab padding.
- Dialog padding where controls feel too large.
- Reduce decorative gradients where they make the UI visually heavy.

### Python Widget Size Work

Update fixed widget sizes in:

- `codehub/ui/sidebar.py`
  - session action buttons
  - drag handle width
  - indicator width
  - details/action buttons

- `codehub/ui/session_workspace.py`
  - app bar action buttons
  - app tab close button
  - tab label max width
  - tab margins

- `codehub/utils/constants.py`
  - `SIDEBAR_WIDTH`
  - possibly `MIN_WINDOW_WIDTH`
  - default window size if the app should open smaller

### Visual Acceptance Checks

- Sidebar can show more sessions without scrolling.
- Header does not dominate the top of the app.
- Session rows remain readable.
- App tabs fit more apps before horizontal scrolling.
- Buttons are still easy to click.
- No text overlaps or gets clipped at normal window sizes.

## Phase 5: App Reordering In Session Panel

### Current State

`codehub/ui/session_workspace.py` already has drag/drop support:

- Non-editor tabs are drag sources.
- All tabs are drag destinations.
- `_reorder_tabs()` prevents moving an app before the editor tab.
- `on_reorder_apps(session_id, app_ids)` callback exists.

`codehub/app.py` already wires:

- `workspace.on_reorder_apps = self._on_reorder_workspace_apps`
- `_on_reorder_workspace_apps()` persists the new `session.apps` order.

### Remaining Work

- Manually test the current implementation.
- Verify app order persists after app restart.
- Verify app order persists after CodeHub restart.
- Improve drag feedback if needed:
  - clear drop highlight reliably
  - show before/after indicator
  - avoid accidental tab selection during drag
- Confirm editor tab is always pinned first.
- Confirm terminal/native tabs are handled correctly if they are reorderable.

### Acceptance Checks

- Add three apps to a session.
- Drag the third app before the second app.
- Switch sessions and return.
- Restart CodeHub.
- The new order remains.
- Editor remains first.

## Phase 6: Rename Opened Apps From Right-Click Menu

### Data Model

`SessionApp` already has:

```python
display_name: str = ""
```

Renaming should update:

- The visible tab label.
- The persisted `session.apps[*].display_name`.
- Any sidebar/details view that shows connected app names.

### UI Flow

Right-click an app tab:

```text
Rename App
```

Then show a small dialog:

- Title: `Rename App`
- Entry prefilled with current display name.
- Save and Cancel.
- Validation:
  - cannot be empty
  - trim whitespace
  - max length around 40 characters

Editor tab:

- Option A: do not allow editor rename because it represents the session editor.
- Option B: allow a local display alias but do not change the session name.

Recommended: start with Option A and keep rename only for non-editor app tabs.

### Code Changes

Update `codehub/ui/session_workspace.py`:

- Add callback:

```python
self.on_rename_app = None  # (session_id, app_id)
```

- Add `Rename App` item to `_on_tab_right_click()` for non-editor tabs.
- Add method to update the visible tab label:

```python
def rename_app_tab(self, app_id: str, display_name: str):
    tab = self._tabs.get(app_id)
    if tab:
        tab.name_label.set_text(display_name)
        tab.name_label.set_tooltip_text(display_name)
```

Update `codehub/app.py`:

- Wire `workspace.on_rename_app = self._on_rename_workspace_app`.
- Implement `_on_rename_workspace_app(session_id, app_id)`.
- Find the app dict in `session.apps`.
- Show rename dialog.
- Save new `display_name`.
- Update `SessionRegistry`.
- Update registered `SessionApp` in `AppManager` if present.
- Call `workspace.rename_app_tab(app_id, new_name)`.
- Refresh sidebar row/details if needed.

Dialog options:

- Use a simple `Gtk.Dialog` inline in `app.py`.
- Or add reusable `RenameAppDialog` in `codehub/ui/app_dialog.py`.

Recommended: add `RenameAppDialog` to `codehub/ui/app_dialog.py`, because app creation dialogs already live there.

### Acceptance Checks

- Add Postman or another app to a session.
- Right-click the tab.
- Choose Rename App.
- Enter a new name.
- Tab updates immediately.
- Session details show the new name.
- Restart CodeHub.
- The renamed app still has the new name.

## Phase 7: Testing Plan

### Manual Test Matrix

Accounts:

- Create first account.
- Login with valid password.
- Reject invalid password.
- Create second account.
- Switch from first account to second account.
- Verify sessions are isolated.
- Rename account.
- Change password.
- Delete account with password confirmation.
- Open two CodeHub windows with different accounts.

Data migration:

- Start with existing root-level `sessions.json`.
- Create first account.
- Verify old sessions appear in the first account.
- Verify backup exists.

Compact UI:

- Test at default size.
- Test at minimum window size.
- Test with many sessions.
- Test with long session names and long paths.
- Test with many app tabs.

App reorder:

- Reorder multiple apps.
- Restart app.
- Verify persisted order.

App rename:

- Rename normal app.
- Try empty name and confirm validation.
- Restart app.
- Verify persisted name.

### Automated Tests Worth Adding

If adding tests is practical, add focused unit tests for:

- `AccountManager` create/login/update/delete.
- Account path isolation.
- Migration from root-level config files.
- `SessionRegistry(config_dir)` loads different data for different accounts.
- Reordering app dicts by app id.
- Rename persistence in session app dict.

## Suggested Implementation Order

1. Add `AccountManager` and account storage.
2. Make config/settings and registries accept account-specific config directories.
3. Add migration from current root-level config into the first account.
4. Add account chooser/create/login UI.
5. Wire startup, logout, and switch-account flows in `CodeHubApp`.
6. Enable or verify multiple app windows with different accounts.
7. Compact CSS and fixed widget sizes.
8. Verify and polish app tab drag/drop reorder.
9. Add right-click app rename.
10. Run manual acceptance checks and fix regressions.

## Open Decisions

- Should account delete permanently remove the account directory, or move it to a trash/backup folder first?
- Should logout stop all launched apps automatically, ask first, or leave external apps running?
- Should the app remember the last selected account, or always start at the chooser?
- Should the editor tab ever be renameable, or should only extra workspace apps be renameable?
- Should each account have its own window size/sidebar width, or should those remain global? Recommended: account-owned settings.

