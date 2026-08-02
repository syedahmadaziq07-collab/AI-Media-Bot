"""Supabase query helpers — replaces the SQLite Database class."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from .supabase_client import get_client

logger = logging.getLogger(__name__)


def _exec(query, label: str = ""):
    """Execute a Supabase query and log the full response body on any error."""
    try:
        return query.execute()
    except Exception as exc:
        body = getattr(exc, "message", None) or getattr(exc, "details", None)
        code = getattr(exc, "code", None)
        hint = getattr(exc, "hint", None)
        raw = None
        for attr in ("response", "_response", "args"):
            candidate = getattr(exc, attr, None)
            if candidate:
                raw = candidate
                break
        print(
            f"[supabase] ERROR{' (' + label + ')' if label else ''}: "
            f"{exc!r} | body={body!r} | code={code!r} | hint={hint!r} | raw={raw!r}",
            flush=True,
        )
        logger.error(
            "Supabase query failed%s: %r | body=%r | code=%r | hint=%r | raw=%r",
            f" ({label})" if label else "",
            exc, body, code, hint, raw,
        )
        raise


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


# ── Users ──────────────────────────────────────────────────────────────────────

def upsert_user(
    user_id: int,
    username: str | None,
    first_name: str,
    referred_by: int | None = None,
) -> dict:
    sb = get_client()
    now = utc_now()

    # Single upsert: DB column defaults fill balance=0 and created_at=NOW() on
    # first INSERT; on conflict only username/first_name are updated, balance preserved.
    _exec(
        sb.table("users").upsert(
            {"user_id": user_id, "username": username, "first_name": first_name},
            on_conflict="user_id",
        ),
        "users.upsert",
    )

    # Fetch current row to check referral status.
    user = get_user(user_id)

    # Register referral only for users that don't have one yet.
    if referred_by and referred_by != user_id and not user.get("referred_by"):
        referrer = _exec(sb.table("users").select("user_id").eq("user_id", referred_by), "users.select_referrer")
        if referrer.data:
            try:
                _exec(sb.table("referrals").insert({
                    "referrer_id": referred_by,
                    "referred_id": user_id,
                    "created_at": now,
                }), "referrals.insert")
                _exec(sb.table("users").update({"referred_by": referred_by}).eq("user_id", user_id), "users.update_referred_by")
            except Exception:
                pass

    return user


def get_user(user_id: int) -> dict:
    sb = get_client()
    result = _exec(sb.table("users").select("*").eq("user_id", user_id).single(), "users.get")
    return result.data


def balance(user_id: int) -> int:
    return int(get_user(user_id)["balance"])


def mutate_balance(user_id: int, amount: int, txn_type: str, reference_id: str) -> int:
    """Atomic balance mutation via RPC. Returns new balance (sen)."""
    sb = get_client()
    if amount < 0:
        result = _exec(sb.rpc("deduct_credit", {
            "p_user_id": user_id,
            "p_amount": abs(amount),
            "p_type": txn_type,
            "p_reference_id": reference_id,
        }), "rpc.deduct_credit")
    else:
        result = _exec(sb.rpc("add_credit", {
            "p_user_id": user_id,
            "p_amount": amount,
            "p_type": txn_type,
            "p_reference_id": reference_id,
        }), "rpc.add_credit")
    return int(result.data)


def recent_transactions(user_id: int, limit: int = 5) -> list[dict]:
    sb = get_client()
    result = _exec(
        sb.table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit),
        "transactions.select",
    )
    return result.data


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
    sb = get_client()
    payload: dict[str, Any] = {
        "id": job_id,
        "user_id": user_id,
        "model_key": model_key,
        "job_type": job_type,
        "prompt": prompt,
        "cost": cost,
        "status": status,
        "created_at": utc_now(),
    }
    if input_image_url:
        payload["input_image_url"] = input_image_url
    if fal_request_id:
        payload["fal_request_id"] = fal_request_id
    result = _exec(sb.table("jobs").insert(payload), "jobs.insert")
    return result.data[0]


def get_job(job_id: str) -> dict:
    sb = get_client()
    result = _exec(sb.table("jobs").select("*").eq("id", job_id).single(), "jobs.get")
    return result.data


def get_job_by_fal_request(fal_request_id: str) -> dict | None:
    sb = get_client()
    result = _exec(sb.table("jobs").select("*").eq("fal_request_id", fal_request_id), "jobs.get_by_fal")
    return result.data[0] if result.data else None


def update_job(job_id: str, **kwargs: Any) -> None:
    allowed = {"status", "fal_request_id", "output_url", "completed_at"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    _exec(get_client().table("jobs").update(fields).eq("id", job_id), "jobs.update")


def recent_jobs(user_id: int, offset: int = 0, limit: int = 8) -> list[dict]:
    sb = get_client()
    result = _exec(
        sb.table("jobs")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1),
        "jobs.recent",
    )
    return result.data


def user_stats(user_id: int) -> dict:
    sb = get_client()
    total = _exec(sb.table("jobs").select("id", count="exact").eq("user_id", user_id), "jobs.count_total")
    completed = _exec(
        sb.table("jobs")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("status", "completed"),
        "jobs.count_completed",
    )
    return {
        "total": total.count or 0,
        "completed": completed.count or 0,
    }


# ── Credit packages ────────────────────────────────────────────────────────────

def get_credit_packages() -> list[dict]:
    sb = get_client()
    result = _exec(sb.table("credit_packages").select("*").eq("is_active", True), "credit_packages.select")
    return result.data


def get_credit_package(pkg_id: int) -> dict:
    sb = get_client()
    result = _exec(sb.table("credit_packages").select("*").eq("id", pkg_id).single(), "credit_packages.get")
    if not result.data:
        raise KeyError(f"Package {pkg_id} not found")
    return result.data


# ── Payment settings ───────────────────────────────────────────────────────────

def get_payment_settings() -> dict | None:
    sb = get_client()
    result = _exec(sb.table("payment_settings").select("*").eq("id", 1), "payment_settings.select")
    return result.data[0] if result.data else None


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
    _exec(get_client().table("topup_requests").insert({
        "id": request_id,
        "user_id": user_id,
        "package_id": package_id,
        "amount_rm": amount_rm,
        "bonus_percent": bonus_percent,
        "status": "awaiting_receipt",
        "created_at": created_at,
        "expires_at": expires_at,
    }), "topup_requests.insert")


def get_topup_request(request_id: str) -> dict:
    sb = get_client()
    result = _exec(sb.table("topup_requests").select("*").eq("id", request_id).single(), "topup_requests.get")
    if not result.data:
        raise KeyError(f"Topup request {request_id} not found")
    return result.data


def update_topup_request(request_id: str, **kwargs: Any) -> None:
    allowed = {"status", "receipt_file_id", "admin_id", "admin_note", "processed_at"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    _exec(get_client().table("topup_requests").update(fields).eq("id", request_id), "topup_requests.update")


def approve_topup(request_id: str, admin_id: int) -> tuple[int, int, float, int, str]:
    """Atomically approve a topup. Returns (user_id, new_balance_sen, amount_rm, bonus_pct, pkg_name)."""
    req = get_topup_request(request_id)
    if req["status"] != "pending_review":
        raise ValueError(f"Cannot approve request with status '{req['status']}'")
    pkg = get_credit_package(req["package_id"])
    credit_sen = int(float(req["amount_rm"]) * 100 * (1 + req["bonus_percent"] / 100))
    new_balance = mutate_balance(req["user_id"], credit_sen, "topup", request_id)
    update_topup_request(request_id, status="approved", admin_id=admin_id, processed_at=utc_now())
    return req["user_id"], new_balance, float(req["amount_rm"]), req["bonus_percent"], pkg["name"]


def reject_topup(request_id: str, admin_id: int) -> tuple[int, str]:
    """Mark a topup request as rejected. Returns (user_id, pkg_name)."""
    req = get_topup_request(request_id)
    if req["status"] not in ("pending_review", "awaiting_receipt"):
        raise ValueError(f"Cannot reject request with status '{req['status']}'")
    pkg = get_credit_package(req["package_id"])
    update_topup_request(request_id, status="rejected", admin_id=admin_id, processed_at=utc_now())
    return req["user_id"], pkg["name"]


# ── Conversation state ─────────────────────────────────────────────────────────

def get_conversation_state(user_id: int) -> dict | None:
    sb = get_client()
    result = _exec(sb.table("conversation_state").select("*").eq("user_id", user_id), "conv_state.select")
    return result.data[0] if result.data else None


def set_conversation_state(user_id: int, **kwargs: Any) -> None:
    allowed = {
        "step", "job_type", "model_key", "ratio", "prompt",
        "image_url", "bot_message_id", "bot_chat_id", "topup_request_id",
    }
    fields: dict[str, Any] = {k: v for k, v in kwargs.items() if k in allowed}
    fields["user_id"] = user_id
    fields["updated_at"] = utc_now()
    _exec(get_client().table("conversation_state").upsert(fields, on_conflict="user_id"), "conv_state.upsert")


def clear_conversation_state(user_id: int) -> None:
    _exec(get_client().table("conversation_state").delete().eq("user_id", user_id), "conv_state.delete")


# ── Check-in ───────────────────────────────────────────────────────────────────

def checkin(user_id: int, bonus_sen: int) -> int | None:
    """Attempt weekly check-in. Returns new balance if successful, None if too early."""
    user = get_user(user_id)
    now = datetime.now(UTC)
    last = user.get("last_checkin")
    if last:
        last_dt = datetime.fromisoformat(last)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=UTC)
        if now - last_dt < timedelta(days=7):
            return None
    _exec(get_client().table("users").update({"last_checkin": now.isoformat()}).eq("user_id", user_id), "users.update_checkin")
    return mutate_balance(user_id, bonus_sen, "checkin", f"checkin:{now.date().isoformat()}")


# ── Referral ───────────────────────────────────────────────────────────────────

def settle_referral(referred_id: int, bonus_sen: int) -> None:
    """Credit referral bonus to both parties if not yet paid."""
    sb = get_client()
    ref = _exec(sb.table("referrals").select("*").eq("referred_id", referred_id), "referrals.select")
    if not ref.data or ref.data[0]["bonus_paid"]:
        return
    row = ref.data[0]
    _exec(sb.table("referrals").update({"bonus_paid": 1}).eq("referred_id", referred_id), "referrals.update")
    ref_id = f"referral:{referred_id}"
    mutate_balance(row["referrer_id"], bonus_sen, "referral_bonus", ref_id)
    mutate_balance(referred_id, bonus_sen, "referral_bonus", ref_id)


# ── Leaderboard / admin ────────────────────────────────────────────────────────

def leaderboard(limit: int = 10) -> list[dict]:
    sb = get_client()
    result = _exec(sb.rpc("leaderboard_top", {"p_limit": limit}), "rpc.leaderboard_top")
    if result.data:
        return result.data
    # Fallback: manual aggregation if RPC not present
    rows = _exec(
        sb.table("jobs")
        .select("user_id")
        .eq("status", "completed"),
        "jobs.select_completed",
    )
    counts: dict[int, int] = {}
    for r in rows.data:
        counts[r["user_id"]] = counts.get(r["user_id"], 0) + 1
    top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [{"user_id": uid, "completed": cnt} for uid, cnt in top]


def admin_stats() -> dict:
    sb = get_client()
    users = _exec(sb.table("users").select("user_id", count="exact"), "users.count")
    jobs_all = _exec(sb.table("jobs").select("id", count="exact"), "jobs.count_all")
    jobs_done = _exec(sb.table("jobs").select("id", count="exact").eq("status", "completed"), "jobs.count_done")
    spent_rows = _exec(sb.table("jobs").select("cost").eq("status", "completed"), "jobs.select_cost")
    total_spent = sum(r["cost"] for r in spent_rows.data)
    return {
        "users": users.count or 0,
        "jobs": jobs_all.count or 0,
        "completed": jobs_done.count or 0,
        "spent": total_spent,
    }


def all_user_ids() -> list[int]:
    sb = get_client()
    result = _exec(sb.table("users").select("user_id"), "users.select_all_ids")
    return [r["user_id"] for r in result.data]
