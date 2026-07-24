"""Compatibility exports for the database query layer."""

from .db import Database, utc_now

__all__ = ["Database", "utc_now"]