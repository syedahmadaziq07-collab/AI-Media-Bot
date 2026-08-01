---
name: SQLite async cursors
description: aiosqlite Connection objects in this environment do not have execute_fetchone/execute_fetchall convenience methods — use explicit async with cursor pattern instead.
---

`aiosqlite` v0.22+ `Connection` objects expose `execute()` which returns a cursor, but do NOT have `execute_fetchone` or `execute_fetchall` shortcut methods. Always use explicit cursor fetching:

```python
# WRONG — AttributeError at runtime
row = await db.execute_fetchone("SELECT ...", (params,))

# CORRECT
async with db.execute("SELECT ...", (params,)) as cur:
    row = await cur.fetchone()
```

**Why:** The memory note originally documented this quirk; confirmed when `database/db.py` used `execute_fetchone` and failed at runtime with `AttributeError: 'Connection' object has no attribute 'execute_fetchone'`.

**How to apply:** Any time a new DB helper is added, use `async with db.execute(...)` and call `fetchone()`/`fetchall()` on the cursor.
