# Coder3 — Improvement Roadmap

This document outlines planned improvements for Coder3, organized by impact and category.

---

## 🔥 Tier 1 — High Impact / Daily Use

### 1. Session Templates (Workspace Presets)
- **Concept:** Save a session's app configuration as a reusable template.
- **Benefit:** Instantly set up new sessions for "Backend", "Frontend", or "Full Stack" without manual app addition.

### 2. Quick Launcher / Command Palette (Ctrl+P)
- **Concept:** A fuzzy-search popup for sessions and apps.
- **Benefit:** Keyboard-driven navigation across many sessions and apps.

### 3. Session Auto-Start & Auto-Restore
- **Concept:** Reopen sessions that were active when the app was closed; add "Start on launch" per session.
- **Benefit:** Zero-setup startup every morning.

### 4. Integrated Terminal (Vte)
- **Concept:** Native embedded terminal widget (`Vte.Terminal`).
- **Benefit:** Better integration, auto-cd to project path, and more reliable embedding than external terminals.

### 5. Session Status Dashboard
- **Concept:** Show running app icons (📝 📮 🌐) and uptime badges in the sidebar.
- **Benefit:** Global visibility of active work across all sessions.

---

## ⚡ Tier 2 — Smart Features

### 6. Smart Project Scanning
- **Concept:** Auto-detect projects in folders and suggest session creation.
- **Benefit:** Lower friction for adding new work.

### 7. Session Environment Variables
- **Concept:** Pass custom env vars to the editor and all apps in a session.
- **Benefit:** Isolate project configurations (ports, API keys, DB URLs).

### 8. Session Linking / Dependencies
- **Concept:** Define dependencies (e.g., Frontend depends on Backend).
- **Benefit:** Orchestrated startup of complex microservice environments.

### 9. Time Tracking
- **Concept:** Track active time spent per session.
- **Benefit:** Insight into project effort and productivity.

### 10. Comprehensive Keyboard Shortcuts
- **Concept:** Map every action to a shortcut (Session switching, App switching, Start/Stop).
- **Benefit:** "Pro" feel and speed.

---

## 🎨 Tier 3 — Polish & UX

### 11. Tags & Search/Filter
- **Concept:** Add tags to sessions and a filter bar to the sidebar.
- **Benefit:** Manage hundreds of sessions efficiently.

### 12. Notification System
- **Concept:** Toast notifications for app crashes or successful starts.
- **Benefit:** Awareness of background events.

### 13. Session Snapshots / Backup
- **Concept:** Auto-backup and manual export/import of sessions.
- **Benefit:** Safety and portability of configuration.

### 14. Split View
- **Concept:** Side-by-side apps within a single session workspace.
- **Benefit:** Multitasking (e.g., Editor + Browser) without tab switching.

### 15. App Quick Actions
- **Concept:** "Restart", "Detach", and "Duplicate" options in app tab menus.
- **Benefit:** Finer control over workspace apps.

---

## 📊 Recommended Priority

1. **Keyboard Shortcuts & Auto-Restore** (Low Effort, High Impact)
2. **Command Palette (Ctrl+P)** (Medium Effort, Very High Impact)
3. **Session Templates** (Medium Effort, High Impact)
4. **Environment Variables** (Low Effort, High Impact)
5. **Integrated Terminal** (Medium Effort, High Impact)
