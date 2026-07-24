from database import Database


class CreditService:
    def __init__(self, db: Database):
        self.db = db

    async def can_afford(self, user_id: int, cost: int) -> bool:
        return await self.db.balance(user_id) >= cost

    async def debit(self, user_id: int, cost: int, reference_id: str) -> int:
        return await self.db.mutate_balance(user_id, -cost, "generation", reference_id)

    async def refund(self, user_id: int, cost: int, reference_id: str) -> int:
        return await self.db.mutate_balance(user_id, cost, "generation_refund", reference_id)