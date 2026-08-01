"""Payment service placeholder.

The full manual top-up flow (package selection, QR display, receipt upload,
admin approval) is implemented in handlers/topup.py and handlers/credit.py,
backed directly by the database layer (database/db.py topup_* methods).

This file is retained as a thin stub so existing bot_data structure is unchanged.
"""

from __future__ import annotations

from database import Database


class PaymentService:
    def __init__(self, db: Database):
        self.db = db
