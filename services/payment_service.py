"""Payment abstraction.

The gateway-specific implementation is intentionally isolated. Replace the
placeholder URL with a signed checkout session once a gateway is connected.
"""

from dataclasses import dataclass
from uuid import uuid4

from database import Database


@dataclass(frozen=True)
class CreditPackage:
    key: str
    label: str
    amount_sen: int
    price_label: str


PACKAGES = (
    CreditPackage("starter", "Starter", 1000, "RM 10"),
    CreditPackage("creator", "Creator", 3000, "RM 30"),
    CreditPackage("studio", "Studio", 6000, "RM 60"),
    CreditPackage("pro", "Pro", 12000, "RM 120"),
)


class PaymentService:
    def __init__(self, db: Database, gateway_key: str | None):
        self.db = db
        self.gateway_key = gateway_key

    def create_checkout(self, user_id: int, package: CreditPackage) -> str:
        reference = uuid4().hex
        if not self.gateway_key:
            return (
                "Payment gateway belum disambungkan.\n"
                f"Reference demo: {reference}\n"
                "Admin boleh credit secara manual dengan /addcredit."
            )
        return f"Payment session placeholder: {reference}"

    async def confirm_webhook(self, user_id: int, amount_sen: int, reference: str) -> int:
        return await self.db.mutate_balance(user_id, amount_sen, "topup", reference)