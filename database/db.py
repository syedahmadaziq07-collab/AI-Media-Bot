"""SQLite persistence with atomic balance mutations."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.connection: aiosqlite.Connection | None = None
        self._balance_lock = asyncio.Lock()

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.path)
        self.connection.row_factory = aiosqlite.Row
        await self.connection.execute("PRAGMA journal_mode=WAL")
        await self.connection.execute("PRAGMA foreign_keys=ON")
        await self._migrate()

    async def close(self) -> None:
        if self.connection:
            await self.connection.close()
            self.connection = None

    def _db(self) -> aiosqlite.Connection:
        if not self.connection:
            raise RuntimeError("Database is not connected.")
        return self.connection

    async def _fetchone(
        self, query: str, parameters: tuple[Any, ...] = ()
    ) -> aiosqlite.Row | None:
        cursor = await self._db().execute(query, parameters)
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def _fetchall(
        self, query: str, parameters: tuple[Any, ...] = ()
    ) -> list[aiosqlite.Row]:
        cursor = await self._db().execute(query, parameters)
        try:
            return await cursor.fetchall()
        finally:
            await cursor.close()

    async def _migrate(self) -> None:
        db = self._db()
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER NOT NULL DEFAULT 0,
                language TEXT NOT NULL DEFAULT 'ms',
                referred_by INTEGER,
                created_at TEXT NOT NULL,
                last_checkin TEXT
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                reference_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                model_key TEXT NOT NULL,
                job_type TEXT NOT NULL,
                prompt TEXT NOT NULL,
                input_image_url TEXT,
                fal_request_id TEXT,
                status TEXT NOT NULL,
                output_url TEXT,
                cost INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS referrals (
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER PRIMARY KEY,
                bonus_paid INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (referrer_id) REFERENCES users(user_id),
                FOREIGN KEY (referred_id) REFERENCES users(user_id)
            );
            """
        )
        await db.commit()

    async def upsert_user(
        self, user_id: int, username: str | None, referred_by: int | None = None
    ) -> dict[str, Any]:
        db = self._db()
        await db.execute(
            """
            INSERT INTO users (user_id, username, referred_by, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
            """,
            (user_id, username, referred_by, utc_now()),
        )
        if referred_by and referred_by != user_id:
            await db.execute(
                """
                INSERT OR IGNORE INTO referrals
                    (referrer_id, referred_id, created_at)
                VALUES (?, ?, ?)
                """,
                (referred_by, user_id, utc_now()),
            )
        await db.commit()
        return await self.get_user(user_id)

    async def get_user(self, user_id: int) -> dict[str, Any]:
        row = await self._fetchone(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        if row is None:
            raise KeyError(f"User {user_id} does not exist.")
        return dict(row)

    async def balance(self, user_id: int) -> int:
        user = await self.get_user(user_id)
        return int(user["balance"])

    async def mutate_balance(
        self,
        user_id: int,
        amount: int,
        transaction_type: str,
        reference_id: str | None = None,
    ) -> int:
        """Atomically mutate a balance and append the ledger entry."""
        async with self._balance_lock:
            db = self._db()
            await db.execute("BEGIN IMMEDIATE")
            try:
                row = await self._fetchone(
                    "SELECT balance FROM users WHERE user_id = ?", (user_id,)
                )
                if row is None:
                    raise KeyError(f"User {user_id} does not exist.")
                new_balance = int(row["balance"]) + amount
                if new_balance < 0:
                    raise ValueError("Insufficient credit balance.")
                await db.execute(
                    "UPDATE users SET balance = ? WHERE user_id = ?",
                    (new_balance, user_id),
                )
                await db.execute(
                    """
                    INSERT INTO transactions
                        (user_id, type, amount, balance_after, reference_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, transaction_type, amount, new_balance, reference_id, utc_now()),
                )
                await db.commit()
                return new_balance
            except Exception:
                await db.rollback()
                raise

    async def create_job(
        self,
        job_id: str,
        user_id: int,
        model_key: str,
        job_type: str,
        prompt: str,
        cost: int,
        input_image_url: str | None = None,
    ) -> None:
        await self._db().execute(
            """
            INSERT INTO jobs
                (id, user_id, model_key, job_type, prompt, input_image_url,
                 status, cost, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (job_id, user_id, model_key, job_type, prompt, input_image_url, cost, utc_now()),
        )
        await self._db().commit()

    async def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {
            "status",
            "fal_request_id",
            "output_url",
            "input_image_url",
            "completed_at",
        }
        if not fields or not set(fields).issubset(allowed):
            raise ValueError("Invalid or empty job update.")
        assignments = ", ".join(f"{key} = ?" for key in fields)
        await self._db().execute(
            f"UPDATE jobs SET {assignments} WHERE id = ?",
            (*fields.values(), job_id),
        )
        await self._db().commit()

    async def get_job(self, job_id: str) -> dict[str, Any]:
        row = await self._fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if row is None:
            raise KeyError(f"Job {job_id} does not exist.")
        return dict(row)

    async def recent_jobs(self, user_id: int, limit: int = 8, offset: int = 0) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            """
            SELECT * FROM jobs WHERE user_id = ?
            ORDER BY created_at DESC LIMIT ? OFFSET ?
            """,
            (user_id, limit, offset),
        )
        return [dict(row) for row in rows]

    async def recent_transactions(self, user_id: int, limit: int = 5) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            """
            SELECT * FROM transactions WHERE user_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, limit),
        )
        return [dict(row) for row in rows]

    async def user_stats(self, user_id: int) -> dict[str, int]:
        row = await self._fetchone(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed
            FROM jobs WHERE user_id = ?
            """,
            (user_id,),
        )
        return {"total": int(row["total"] or 0), "completed": int(row["completed"] or 0)}

    async def set_checkin(self, user_id: int) -> None:
        await self._db().execute(
            "UPDATE users SET last_checkin = ? WHERE user_id = ?", (utc_now(), user_id)
        )
        await self._db().commit()

    async def can_checkin(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        if not user["last_checkin"]:
            return True
        last = datetime.fromisoformat(user["last_checkin"])
        return datetime.now(UTC) - last >= timedelta(days=7)

    async def leaderboard(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            """
            SELECT u.username, u.user_id, COUNT(j.id) AS completed_jobs,
                   COALESCE(SUM(CASE WHEN t.type = 'generation' THEN -t.amount ELSE 0 END), 0)
                   AS spent
            FROM users u
            LEFT JOIN jobs j ON j.user_id = u.user_id AND j.status = 'completed'
            LEFT JOIN transactions t ON t.user_id = u.user_id
            GROUP BY u.user_id
            ORDER BY completed_jobs DESC, spent DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in rows]

    async def all_user_ids(self) -> list[int]:
        rows = await self._fetchall("SELECT user_id FROM users")
        return [int(row["user_id"]) for row in rows]

    async def admin_stats(self) -> dict[str, int]:
        row = await self._fetchone(
            """
            SELECT
                (SELECT COUNT(*) FROM users) AS users,
                (SELECT COUNT(*) FROM jobs) AS jobs,
                (SELECT COUNT(*) FROM jobs WHERE status = 'completed') AS completed,
                COALESCE((SELECT SUM(-amount) FROM transactions
                          WHERE type = 'generation'), 0) AS spent
            """
        )
        return {key: int(row[key] or 0) for key in ("users", "jobs", "completed", "spent")}

    async def settle_referral(self, referred_id: int, bonus: int) -> bool:
        db = self._db()
        row = await self._fetchone(
            "SELECT referrer_id, bonus_paid FROM referrals WHERE referred_id = ?",
            (referred_id,),
        )
        if row is None or row["bonus_paid"]:
            return False
        await self.mutate_balance(referred_id, bonus, "referral_bonus", f"ref:{referred_id}")
        await self.mutate_balance(int(row["referrer_id"]), bonus, "referral_bonus", f"ref:{referred_id}")
        await db.execute(
            "UPDATE referrals SET bonus_paid = 1 WHERE referred_id = ?", (referred_id,)
        )
        await db.commit()
        return True