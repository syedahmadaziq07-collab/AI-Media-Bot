"""Thin credit facade over db.queries atomic RPCs."""

from __future__ import annotations

import db.queries as q


def can_afford(user_id: int, cost: int) -> bool:
    return q.balance(user_id) >= cost


def debit(user_id: int, cost: int, reference_id: str) -> int:
    """Debit generation cost. Returns new balance."""
    return q.mutate_balance(user_id, -cost, "generation", reference_id)


def refund(user_id: int, cost: int, reference_id: str) -> int:
    """Refund a failed generation. Returns new balance."""
    return q.mutate_balance(user_id, cost, "generation_refund", reference_id)
