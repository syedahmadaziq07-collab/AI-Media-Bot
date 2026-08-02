"""Stub — Supabase replaced by SQLite. Import from db.sqlite_db instead."""
# This file is kept to avoid import errors from any tooling that references it.
# The active DB layer is db.sqlite_db / db.queries.

def get_client():
    raise RuntimeError(
        "Supabase client is not used in this deployment. "
        "All database access goes through db.queries (SQLite)."
    )
