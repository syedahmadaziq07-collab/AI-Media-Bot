---
name: SQLite async cursors
description: Compatibility note for async SQLite access in this workspace
---

Use explicit cursors with `execute()`, `fetchone()`/`fetchall()`, and `close()` for aiosqlite reads.

**Why:** The installed aiosqlite connection does not provide the convenience `execute_fetchone` and `execute_fetchall` methods.

**How to apply:** Keep read helpers centralized in the database layer so handlers do not depend on driver-specific convenience methods.