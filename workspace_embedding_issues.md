# Coder3 Session Editor & Re-embed Issues

## 1. Issue: Cross-Session Editor Interference
**Status**: Resolved
**Description**: When using the same editor (e.g., Zed) for two sessions, switching between them sometimes crashes the entire app, opens one of them externally, or stopping one session stops the other.
**Root Cause**: 
When a new session tried to open the editor, window discovery sometimes found the existing editor window from the first session. It correctly saw the XID was already owned and fell back to external mode. However, the background external mode XID discovery thread blindly called `register_xid` on that same window. `register_xid` printed a warning but allowed it to proceed, overwriting the first session's ownership! Later, when the second session was stopped, it called `unregister_xid` (globally removing ownership) and closed the window, crashing the first session.
**Fix**: 
- Updated `EmbeddingManager.register_xid` to return a boolean (`True` on success, `False` if already owned).
- Updated `app.py`'s external XID discovery thread to abort registering and tracking if `register_xid` returns `False`.
- Updated `EmbeddingManager.unregister_xid` to take an optional `slot_key`. If provided, it verifies the caller actually owns the XID before unregistering.
- Updated all callers of `unregister_xid` to pass their `session_id`/`slot_key`.

## 2. Issue: "Attempt Re-embed" Failing
**Status**: Resolved
**Description**: Attempting to "Re-embed" the editor gives "no unmanaged ... window found", or shows all external windows but the intended editor is not among them (even though it appears as 'external' and is running).
**Root Cause**: 
The "Attempt Re-embed" dialog filtered out any XIDs that were inside `owned_xids`. But because the background external discovery thread was successfully registering external windows to `owned_xids` (assigning ownership to the active session), the dialog completely ignored the very window it was supposed to re-embed!
**Fix**: 
- Updated `_on_recover_workspace_app` to include windows that are either completely unmanaged (`xid not in owned_xids`) OR are already owned by the calling session (`self.embedding_mgr._owned_xids.get(xid) == slot_key`). Now, the active external window will correctly appear as a candidate for re-embedding.

## 3. Issue: Zed Editor Reusing Windows
**Status**: Resolved
**Description**: The user noticed that even with the ownership fixes, the Zed editor still resulted in one embedded window and one external window, and the second session's editor could not be re-embedded. This issue was unique to Zed and did not occur with VS Code.
**Root Cause**:
By default, the `zed` command-line tool opens new projects as tabs within the existing Zed window if one is already open. Because the new project was opening inside the first session's window, no new window XID was created. The first session's window just changed its title. `WindowDiscovery` detected this title change, but because that window XID was already owned by the first session, it was correctly rejected by the isolation logic. Thus, the second session fell back to external mode without a window, and the "Attempt Re-embed" dialog showed nothing because there was no "unmanaged" window (the only window was managed by the first session).
**Fix**:
- Updated the `EDITORS` configuration in `coder3/utils/constants.py` to add the `-n` (new window) flag to Zed's `launch_args` (`["-n", "{path}"]`). This ensures Zed behaves like VS Code (`--new-window`) and always spawns a distinct window for each session, allowing correct discovery and embedding.

## Summary:
The core isolation logic in `EmbeddingManager` has been hardened to prevent cross-session stealing, the recovery dialog has been adjusted to recognize self-owned external windows, and the Zed editor configuration has been fixed to enforce per-session windows. All requested fixes are implemented successfully.
