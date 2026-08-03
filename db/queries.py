"""Supabase query helpers — production database layer for Vercel deployment.

All functions are synchronous. Async callers (handlers.py, fal-webhook.py)
wrap every call with asyncio.to_thread() so the event loop is never blocked.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .supabase_client import get_client


# ── Helpers ────────────────────────────────────────────────────────────────────

def utc_now() -> str:
    """Public helper — imported by api/fal-webhook.py."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rpc_scalar(data: Any) -> int:
    """Extract an integer scalar from a Supabase RPC response."""
    if isinstance(data, list):
        return int(data[0])
    return int(data)


# ── Users ──────────────────────────────────────────────────────────────────────

def upsert_user(
    user_id: int,
    username: str | None,
    first_name: str,
    referred_by: int | None = None,
) -> dict:
    sb = get_client()

    # Upsert the user row (update username/first_name on conflict)
    sb.table("users").upsert(
        {"user_id": user_id, "username": username, "first_name": first_name},
        on_conflict="user_id",
    ).execute()

    user = get_user(user_id)

    # Set referred_by only if not already set
    if referred_by and referred_by != user_id and not user.get("referred_by"):
        referrer = (
            sb.table("users").select("user_id").eq("user_id", referred_by).execute()
        )
        if referrer.data:
            try:
                sb.table("users").update({"referred_by": referred_by}).eq(
                    "user_id", user_id
                ).is_("referred_by", "null").execute()
                sb.table("referrals").upsert(
                    {"referrer_id": referred_by, "referred_id": user_id}
                ).execute()
            except Exception:
                pass

    return get_user(user_id)


def get_user(user_id: int) -> dict:
    res = get_client().table("users").select("*").eq("user_id", user_id).execute()
    if not res.data:
        raise KeyError(f"User {user_id} not found")
    return res.data[0]


def balance(user_id: int) -> int:
    return int(get_user(user_id)["balance"])


def mutate_balance(user_id: int, amount: int, txn_type: str, reference_id: str) -> int:
    """Atomic balance mutation via Supabase RPC. Returns new balance."""
    sb = get_client()
    if amount < 0:
        res = sb.rpc(
            "deduct_credit",
            {
                "p_user_id": user_id,
                "p_amount": abs(amount),
                "p_type": txn_type,
                "p_reference_id": reference_id,
            },
        ).execute()
    else:
        res = sb.rpc(
            "add_credit",
            {
                "p_user_id": user_id,
                "p_amount": amount,
                "p_type": txn_type,
                "p_reference_id": reference_id,
            },
        ).execute()
    return _rpc_scalar(res.data)


def recent_transactions(user_id: int, limit: int = 5) -> list[dict]:
    res = (
        get_client()
        .table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


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
    get_client().table("jobs").insert(
        {
            "id": job_id,
            "user_id": user_id,
            "model_key": model_key,
            "job_type": job_type,
            "prompt": prompt,
            "cost": cost,
            "input_image_url": input_image_url,
            "fal_request_id": fal_request_id,
            "status": status,
        }
    ).execute()
    return get_job(job_id)


def get_job(job_id: str) -> dict:
    res = get_client().table("jobs").select("*").eq("id", job_id).execute()
    if not res.data:
        raise KeyError(f"Job {job_id} not found")
    return res.data[0]


def get_job_by_fal_request(fal_request_id: str) -> dict | None:
    res = (
        get_client()
        .table("jobs")
        .select("*")
        .eq("fal_request_id", fal_request_id)
        .execute()
    )
    return res.data[0] if res.data else None


def update_job(job_id: str, **kwargs: Any) -> None:
    allowed = {"status", "fal_request_id", "output_url", "completed_at"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    get_client().table("jobs").update(fields).eq("id", job_id).execute()


def recent_jobs(user_id: int, offset: int = 0, limit: int = 8) -> list[dict]:
    res = (
        get_client()
        .table("jobs")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return res.data or []


def user_stats(user_id: int) -> dict:
    sb = get_client()
    total_res = (
        sb.table("jobs").select("id", count="exact").eq("user_id", user_id).execute()
    )
    completed_res = (
        sb.table("jobs")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("status", "completed")
        .execute()
    )
    return {
        "total": total_res.count or 0,
        "completed": completed_res.count or 0,
    }


# ── Credit packages ────────────────────────────────────────────────────────────

def get_credit_packages() -> list[dict]:
    res = (
        get_client()
        .table("credit_packages")
        .select("*")
        .eq("is_active", True)
        .execute()
    )
    return res.data or []


def get_credit_package(pkg_id: int) -> dict:
    res = (
        get_client().table("credit_packages").select("*").eq("id", pkg_id).execute()
    )
    if not res.data:
        raise KeyError(f"Package {pkg_id} not found")
    return res.data[0]


# ── Payment settings ───────────────────────────────────────────────────────────

def get_payment_settings() -> dict | None:
    res = (
        get_client().table("payment_settings").select("*").eq("id", 1).execute()
    )
    return res.data[0] if res.data else None


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
    payload = {
        "id": request_id,
        "user_id": user_id,
        "package_id": package_id,
        "amount_rm": amount_rm,
        "bonus_percent": bonus_percent,
        "status": "awaiting_receipt",
        "created_at": created_at,
        "expires_at": expires_at,
    }
    print(f"[DEBUG] create_topup_request payload={payload}", flush=True)
    try:
        get_client().table("topup_requests").insert(payload).execute()
        print("[DEBUG] create_topup_request insert OK", flush=True)
    except Exception as exc:
        # Unwrap full postgrest APIError detail — str(exc) is often just "400 Bad Request"
        code    = getattr(exc, "code",    None)
        message = getattr(exc, "message", None)
        details = getattr(exc, "details", None)
        hint    = getattr(exc, "hint",    None)
        print(
            f"[ERROR] create_topup_request FAILED — "
            f"code={code!r} message={message!r} details={details!r} hint={hint!r} "
            f"raw={exc!r}",
            flush=True,
        )
        raise


def get_topup_request(request_id: str) -> dict:
    res = (
        get_client()
        .table("topup_requests")
        .select("*")
        .eq("id", request_id)
        .execute()
    )
    if not res.data:
        raise KeyError(f"Topup request {request_id} not found")
    return res.data[0]


def update_topup_request(request_id: str, **kwargs: Any) -> None:
    allowed = {"status", "receipt_file_id", "admin_id", "admin_note", "processed_at"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    get_client().table("topup_requests").update(fields).eq("id", request_id).execute()


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
        processed_at=utc_now(),
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
        processed_at=utc_now(),
    )
    return req["user_id"], pkg["name"]


# ── Conversation state ─────────────────────────────────────────────────────────

def get_conversation_state(user_id: int) -> dict | None:
    res = (
        get_client()
        .table("conversation_state")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )
    return res.data[0] if res.data else None


def set_conversation_state(user_id: int, **kwargs: Any) -> None:
    allowed = {
        "step", "job_type", "model_key", "ratio", "prompt",
        "image_url", "bot_message_id", "bot_chat_id", "topup_request_id",
    }
    fields: dict[str, Any] = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return

    sb = get_client()
    fields["updated_at"] = utc_now()

    existing = (
        sb.table("conversation_state")
        .select("user_id")
        .eq("user_id", user_id)
        .execute()
    )
    if existing.data:
        sb.table("conversation_state").update(fields).eq("user_id", user_id).execute()
    else:
        fields["user_id"] = user_id
        sb.table("conversation_state").insert(fields).execute()


def clear_conversation_state(user_id: int) -> None:
    get_client().table("conversation_state").delete().eq("user_id", user_id).execute()


# ── Check-in ───────────────────────────────────────────────────────────────────

def checkin(user_id: int, bonus_sen: int) -> int | None:
    """Attempt weekly check-in. Returns new balance if successful, None if too early."""
    user = get_user(user_id)
    now = datetime.now(UTC)
    last = user.get("last_checkin")
    if last:
        # Supabase returns ISO strings; handle both offset-aware and naive
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=UTC)
        if now - last_dt < timedelta(days=7):
            return None
    get_client().table("users").update(
        {"last_checkin": now.isoformat()}
    ).eq("user_id", user_id).execute()
    return mutate_balance(
        user_id, bonus_sen, "checkin", f"checkin:{now.date().isoformat()}"
    )


# ── Referral ───────────────────────────────────────────────────────────────────

def settle_referral(referred_id: int, bonus_sen: int) -> None:
    """Credit referral bonus to both parties if not yet paid."""
    sb = get_client()
    res = (
        sb.table("referrals").select("*").eq("referred_id", referred_id).execute()
    )
    if not res.data:
        return
    row = res.data[0]
    if row["bonus_paid"]:
        return
    referrer_id = row["referrer_id"]
    sb.table("referrals").update({"bonus_paid": 1}).eq(
        "referred_id", referred_id
    ).execute()
    ref_id = f"referral:{referred_id}"
    mutate_balance(referrer_id, bonus_sen, "referral_bonus", ref_id)
    mutate_balance(referred_id, bonus_sen, "referral_bonus", ref_id)


# ── Leaderboard / admin ────────────────────────────────────────────────────────

def leaderboard(limit: int = 10) -> list[dict]:
    try:
        res = get_client().rpc("leaderboard_top", {"p_limit": limit}).execute()
        return res.data or []
    except Exception:
        # Fallback if the RPC doesn't exist yet
        res = (
            get_client()
            .table("jobs")
            .select("user_id")
            .eq("status", "completed")
            .execute()
        )
        counts: dict[int, int] = {}
        for row in (res.data or []):
            uid = row["user_id"]
            counts[uid] = counts.get(uid, 0) + 1
        sorted_rows = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [{"user_id": uid, "completed": cnt} for uid, cnt in sorted_rows]


def admin_stats() -> dict:
    sb = get_client()
    users_res = sb.table("users").select("user_id", count="exact").execute()
    jobs_res = sb.table("jobs").select("id", count="exact").execute()
    completed_res = (
        sb.table("jobs").select("id", count="exact").eq("status", "completed").execute()
    )
    spent_res = (
        sb.table("jobs").select("cost").eq("status", "completed").execute()
    )
    spent = sum(int(r["cost"]) for r in (spent_res.data or []))
    return {
        "users": users_res.count or 0,
        "jobs": jobs_res.count or 0,
        "completed": completed_res.count or 0,
        "spent": spent,
    }


def all_user_ids() -> list[int]:
    res = get_client().table("users").select("user_id").execute()
    return [int(r["user_id"]) for r in (res.data or [])]


# ── App settings ───────────────────────────────────────────────────────────────

_APP_SETTINGS_DEFAULTS = {
    "maintenance_mode": 0,
    "maintenance_message": "Bot dalam penyelenggaraan. Sila cuba lagi kemudian.",
    "admin_away_mode": 0,
    "admin_away_message": "Admin sedang tidak berada. Semakan mungkin mengambil masa lebih lama.",
    "admin_chat_id": None,  # comma-separated admin Telegram IDs stored in DB (live, no redeploy needed)
}


def get_app_settings() -> dict:
    try:
        res = (
            get_client().table("app_settings").select("*").eq("id", 1).execute()
        )
        if res.data:
            return res.data[0]
    except Exception:
        pass
    return dict(_APP_SETTINGS_DEFAULTS)


# ── Broadcast log ──────────────────────────────────────────────────────────────

def log_broadcast(message: str, sent_count: int, failed_count: int) -> None:
    try:
        get_client().table("broadcast_log").insert(
            {
                "message": message,
                "sent_count": sent_count,
                "failed_count": failed_count,
                "created_at": utc_now(),
            }
        ).execute()
    except Exception:
        pass  # Non-critical — don't let logging failures break broadcast
