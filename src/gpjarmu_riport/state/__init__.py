"""State package — SQLite-backed dedup + run metadata."""
from .db import ReportedItem, StateDB

__all__ = ["StateDB", "ReportedItem"]
