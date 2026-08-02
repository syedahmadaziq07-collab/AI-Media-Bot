"""SQLite query helpers — same public interface as the Supabase version."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from .sqlite_db import get_connection


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r is not None else None


# ── Users ──────────────────────────────────────────────────────────────────────

def upsert_user(
    user_id: int,
    username: str | None,
    first_name: str,
    referred_by: int | None = None,
) -> dict:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO users (user_id, username, first_name, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username   = excluded.username,
            first_name = excluded.first_name
        """,
        (user_id, username, first_name, _utc_now()),
    )
    conn.commit()

    user = get_user(user_id)

    if referred_by and referred_by != user_id and not user.get("referred_by"):
        referrer = conn.execute(
            "SELECT user_id FROM users WHERE user_id = ?", (referred_by,)
        ).fetchone()
        if referrer:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, created_at) VALUES (?, ?, ?)",
                    (referred_by, user_id, _utc_now()),
                )
                conn.execute(
                    "UPDATE users SET referred_by = ? WHERE user_id = ? AND referred_by IS NULL",
                    (referred_by, user_id),
                )
                conn.commit()
            except Exception:
                pass

    return get_user(user_id)


def get_user(user_id: int) -> dict:
    row = get_connection().execute(
        "SELECT * FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"User {user_id} not found")
    return dict(row)


def balance(user_id: int) -> int:
    return int(get_user(user_id)["balance"])


def mutate_balance(user_id: int, amount: int, txn_type: str, reference_id: str) -> int:
    """Atomic balance mutation using BEGIN IMMEDIATE. Returns new balance."""
    conn = get_connection()
    # Use a fresh connection for this transaction to avoid conflicts
    db_path = conn.execute("PRAGMA database_list").fetchone()["file"]
    with sqlite3.connect(db_path, timeout=30) as c:
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=10000")
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            raise KeyError(f"User {user_id} not found")
        new_balance = int(row["balance"]) + amount
        if new_balance < 0:
            raise ValueError(f"Insufficient balance: {row['balance']} + {amount} < 0")
        txn_id = uuid.uuid4().hex
        c.execute(
            "UPDATE users SET balance = ? WHERE user_id = ?",
            (new_balance, user_id),
        )
        c.execute(
            "INSERT INTO transactions (id, user_id, amount, type, reference_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (txn_id, user_id, amount, txn_type, reference_id, _utc_now()),
        )
        c.execute("COMMIT")
    return new_balance


def recent_transactions(user_id: int, limit: int = 5) -> list[dict]:
    rows = get_connection().execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Jobs ───────────────────────────────────────────────────────────────────────

def create_job(
    job_id: str,
    user_id: int,
    model_key: str,
    job_type: str,
    prompt: str,
    cost: int,
    input_image_url: str | None = None,
    fal_request_id: str | None = None,
    status: str = "pending",
) -> dict:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs
            (id, user_id, model_key, job_type, prompt, cost,
             input_image_url, fal_request_id, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (job_id, user_id, model_key, job_type, prompt, cost,
         input_image_url, fal_request_id, status, _utc_now()),
    )
    conn.commit()
    return get_job(job_id)


def get_job(job_id: str) -> dict:
    row = get_connection().execute(
        "SELECT * FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"Job {job_id} not found")
    return dict(row)


def get_job_by_fal_request(fal_request_id: str) -> dict | None:
    row = get_connection().execute(
        "SELECT * FROM jobs WHERE fal_request_id = ?", (fal_request_id,)
    ).fetchone()
    return dict(row) if row else None


def update_job(job_id: str, **kwargs: Any) -> None:
    allowed = {"status", "fal_request_id", "output_url", "completed_at"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    conn = get_connection()
    conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", values)
    conn.commit()


def recent_jobs(user_id: int, offset: int = 0, limit: int = 8) -> list[dict]:
    rows = get_connection().execute(
        "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (user_id, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def user_stats(user_id: int) -> dict:
    conn = get_connection()
    total = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    completed = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE user_id = ? AND status = 'completed'", (user_id,)
    ).fetchone()[0]
    return {"total": total, "completed": completed}


# ── Credit packages ────────────────────────────────────────────────────────────

def get_credit_packages() -> list[dict]:
    rows = get_connection().execute(
        "SELECT * FROM credit_packages WHERE is_active = 1"
    ).fetchall()
    return [dict(r) for r in rows]


def get_credit_package(pkg_id: int) -> dict:
    row = get_connection().execute(
        "SELECT * FROM credit_packages WHERE id = ?", (pkg_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"Package {pkg_id} not found")
    return dict(row)


# ── Payment settings ───────────────────────────────────────────────────────────

def get_payment_settings() -> dict | None:
    row = get_connection().execute(
        "SELECT * FROM payment_settings WHERE id = 1"
    ).fetchone()
    return dict(row) if row else None


# ── Topup requests ─────────────────────────────────────────────────────────────

def create_topup_request(
    request_id: str,
    user_id: int,
    package_id: int,
    amount_rm: float,
    bonus_percent: int,
    created_at: str,
    expires_at: str,
) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO topup_requests
            (id, user_id, package_id, amount_rm, bonus_percent,
             status, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, 'awaiting_receipt', ?, ?)
        """,
        (request_id, user_id, package_id, amount_rm, bonus_percent,
         created_at, expires_at),
    )
    conn.commit()


def get_topup_request(request_id: str) -> dict:
    row = get_connection().execute(
        "SELECT * FROM topup_requests WHERE id = ?", (request_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"Topup request {request_id} not found")
    return dict(row)


def update_topup_request(request_id: str, **kwargs: Any) -> None:
    allowed = {"status", "receipt_file_id", "admin_id", "admin_note", "processed_at"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [request_id]
    conn = get_connection()
    conn.execute(f"UPDATE topup_requests SET {set_clause} WHERE id = ?", values)
    conn.commit()


def approve_topup(request_id: str, admin_id: int) -> tuple[int, int, float, int, str]:
    """Atomically approve a topup. Returns (user_id, new_balance_sen, amount_rm, bonus_pct, pkg_name)."""
    req = get_topup_request(request_id)
    if req["status"] != "pending_review":
        raise ValueError(f"Cannot approve request with status '{req['status']}'")
    pkg = get_credit_package(req["package_id"])
    credit_sen = int(float(req["amount_rm"]) * 100 * (1 + req["bonus_percent"] / 100))
    new_balance = mutate_balance(req["user_id"], credit_sen, "topup", request_id)
    update_topup_request(
        request_id,
        status="approved",
        admin_id=admin_id,
        processed_at=_utc_now(),
    )
    return req["user_id"], new_balance, float(req["amount_rm"]), req["bonus_percent"], pkg["name"]


def reject_topup(request_id: str, admin_id: int) -> tuple[int, str]:
    """Mark a topup request as rejected. Returns (user_id, pkg_name)."""
    req = get_topup_request(request_id)
    if req["status"] not in ("pending_review", "awaiting_receipt"):
        raise ValueError(f"Cannot reject request with status '{req['status']}'")
    pkg = get_credit_package(req["package_id"])
    update_topup_request(
        request_id,
        status="rejected",
        admin_id=admin_id,
        processed_at=_utc_now(),
    )
    return req["user_id"], pkg["name"]


# ── Conversation state ─────────────────────────────────────────────────────────

def get_conversation_state(user_id: int) -> dict | None:
    row = get_connection().execute(
        "SELECT * FROM conversation_state WHERE user_id = ?", (user_id,)
    ).fetchone()
    return dict(row) if row else None


def set_conversation_state(user_id: int, **kwargs: Any) -> None:
    allowed = {
        "step", "job_type", "model_key", "ratio", "prompt",
        "image_url", "bot_message_id", "bot_chat_id", "topup_request_id",
    }
    fields: dict[str, Any] = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return

    conn = get_connection()
    # Try UPDATE first; INSERT if no row exists
    existing = conn.execute(
        "SELECT user_id FROM conversation_state WHERE user_id = ?", (user_id,)
    ).fetchone()
    now = _utc_now()
    if existing:
        set_clause = ", ".join(f"{k} = ?" for k in fields) + ", updated_at = ?"
        values = list(fields.values()) + [now, user_id]
        conn.execute(f"UPDATE conversation_state SET {set_clause} WHERE user_id = ?", values)
    else:
        fields["user_id"] = user_id
        fields["updated_at"] = now
        cols = ", ".join(fields)
        placeholders = ", ".join("?" * len(fields))
        conn.execute(
            f"INSERT INTO conversation_state ({cols}) VALUES ({placeholders})",
            list(fields.values()),
        )
    conn.commit()


def clear_conversation_state(user_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM conversation_state WHERE user_id = ?", (user_id,))
    conn.commit()


# ── Check-in ───────────────────────────────────────────────────────────────────

def checkin(user_id: int, bonus_sen: int) -> int | None:
    """Attempt weekly check-in. Returns new balance if successful, None if too early."""
    user = get_user(user_id)
    now = datetime.now(UTC)
    last = user.get("last_checkin")
    if last:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=UTC)
        if now - last_dt < timedelta(days=7):
            return None
    conn = get_connection()
    conn.execute(
        "UPDATE users SET last_checkin = ? WHERE user_id = ?",
        (now.strftime("%Y-%m-%dT%H:%M:%SZ"), user_id),
    )
    conn.commit()
    return mutate_balance(user_id, bonus_sen, "checkin", f"checkin:{now.date().isoformat()}")


# ── Referral ───────────────────────────────────────────────────────────────────

def settle_referral(referred_id: int, bonus_sen: int) -> None:
    """Credit referral bonus to both parties if not yet paid."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM referrals WHERE referred_id = ?", (referred_id,)
    ).fetchone()
    if not row or row["bonus_paid"]:
        return
    referrer_id = row["referrer_id"]
    conn.execute(
        "UPDATE referrals SET bonus_paid = 1 WHERE referred_id = ?", (referred_id,)
    )
    conn.commit()
    ref_id = f"referral:{referred_id}"
    mutate_balance(referrer_id, bonus_sen, "referral_bonus", ref_id)
    mutate_balance(referred_id, bonus_sen, "referral_bonus", ref_id)


# ── Leaderboard / admin ────────────────────────────────────────────────────────

def leaderboard(limit: int = 10) -> list[dict]:
    rows = get_connection().execute(
        """
        SELECT user_id, COUNT(*) AS completed
        FROM jobs
        WHERE status = 'completed'
        GROUP BY user_id
        ORDER BY completed DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def admin_stats() -> dict:
    conn = get_connection()
    users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    completed = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status = 'completed'"
    ).fetchone()[0]
    spent = conn.execute(
        "SELECT COALESCE(SUM(cost), 0) FROM jobs WHERE status = 'completed'"
    ).fetchone()[0]
    return {"users": users, "jobs": jobs, "completed": completed, "spent": spent}


def all_user_ids() -> list[int]:
    rows = get_connection().execute("SELECT user_id FROM users").fetchall()
    return [r["user_id"] for r in rows]


# ── App settings ───────────────────────────────────────────────────────────────

def get_app_settings() -> dict:
    row = get_connection().execute(
        "SELECT * FROM app_settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return {
            "maintenance_mode": 0,
            "maintenance_message": "Bot dalam penyelenggaraan. Sila cuba lagi kemudian.",
            "admin_away_mode": 0,
            "admin_away_message": "Admin sedang tidak berada. Semakan mungkin mengambil masa lebih lama.",
        }
    return dict(row)


# ── Broadcast log ──────────────────────────────────────────────────────────────

def log_broadcast(message: str, sent_count: int, failed_count: int) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO broadcast_log (message, sent_count, failed_count, created_at) "
        "VALUES (?, ?, ?, ?)",
        (message, sent_count, failed_count, _utc_now()),
    )
    conn.commit()
