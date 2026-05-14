# Coder3 Modes Implementation Plan

## 1. Overview
The goal is to implement three operating modes in Coder3:
- **Normal Mode**: The current behavior. All sessions are active and manually manageable.
- **Focus Mode**: Restricts activity to specific selected sessions. Supports scheduling automated focus periods.
- **Managed Mode (Pomodoro Integration)**: Automates session cycling based on the Pomodoro timer. Only works on selected sessions (or Focus Mode sessions if both modes are active). Disables all apps during breaks.

## 2. Core Concepts
- **App/Session Disabling**: When a session is "disabled" due to mode restrictions, its UI should be visually locked (e.g., a semi-transparent overlay or insensitive state) and interactions prevented.
- **Modes Engine (`ModeManager`)**: A central component responsible for keeping track of the current mode, focus periods, and communicating with the UI and Session Registry to enforce the mode restrictions.

## 3. Data Models & Persistence
### 3.1 Mode State & Settings
Create a `ModeSettings` model (managed via `coder3/mode_manager.py`):
- `current_mode`: Enum (NORMAL, FOCUS, MANAGED, FOCUS_AND_MANAGED)
- `focus_periods`: List of scheduled periods.
- `managed_sessions`: List of session IDs selected for Managed Mode.
- `manual_focus_sessions`: List of session IDs selected for manual Focus Mode.

### 3.2 Focus Period Structure
- `id`: Unique identifier
- `name`: Display name
- `start_time`: Time of day (e.g., "09:00")
- `end_time`: Time of day (e.g., "11:00")
- `sessions`: List of session IDs to enable
- `repeat_daily`: Boolean
- `start_date`, `end_date`: Optional date range limits
- `excluded_days`: List of integers (e.g., 0=Monday) to skip

## 4. Implementation Phases

### Phase 1: Mode Management Engine (Backend Logic)
- [x] Create `coder3/mode_manager.py` to hold `ModeManager` class.
- [x] Implement persistence for Mode Settings (save to/load from `~/.coder3/modes.json`).
- [x] Implement scheduling logic for Focus Periods: A GLib timeout that checks every minute if a focus period should start or end.
- [x] Add signals/callbacks to notify the main app when the active focus sessions change.

### Phase 2: Session Disabling Mechanism
- [x] Extend `SessionWorkspace` UI to support a "disabled/locked" state (e.g., an overlay covering the workspace with a lock icon, blocking clicks).
- [x] Add `set_session_enabled(session_id, enabled)` logic in the UI layer (Sidebar and Content Area).
- [x] Connect `ModeManager` state changes to enable/disable sessions in the UI.

### Phase 3: Focus Mode UI
- [x] Add a "Modes" switch/menu in the HeaderBar.
- [x] Create a `ModesDialog` to configure Focus Periods, Manual Focus sessions, and Managed Mode sessions.
- [x] Implement UI to add, edit, delete Focus Periods (time pickers, session multi-select).
- [x] Test Focus Mode manual activation (only selected sessions stay enabled).
- [x] Test Focus Mode scheduled activation.

### Phase 4: Managed Mode (Pomodoro Integration)
- [x] Hook `ModeManager` to `PomodoroTimer` events (`on_phase_complete`, `_tick` state changes).
- [x] Implement `ManagedMode` logic:
    - Keep track of the "current active session index" from the selected list.
    - When state = `POMODORO_WORK`, ensure *only* the current session is enabled.
    - When state = `POMODORO_SHORT_BREAK` or `POMODORO_LONG_BREAK`, disable *all* sessions.
    - When advancing from break to work, increment the session index (cycle to next session).
- [x] Support "Focus + Managed" combined mode (dynamically pull the session list from the active Focus Period instead of the static managed list).

### Phase 5: UI Polish & Feedback
- [x] Add visual indicators in the Sidebar to show which sessions are currently focused or managed.
- [x] Add a toast notification when a Focus Period starts/ends.
- [x] Add a toast notification when Managed Mode cycles to the next session.

## 5. Current Status
- [x] Initial Plan Created.
- [x] Phase 1 Completed.
- [x] Phase 2 Completed.
- [x] Phase 3 Completed.
- [x] Phase 4 Completed.
- [x] Phase 5 Completed.
- [x] Done!
