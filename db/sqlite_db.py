"""SQLite connection and schema initialisation."""
from __future__ import annotations

import os
import sqlite3
import threading

DB_PATH = os.environ.get("DATABASE_PATH", "data/jagovideo.sqlite3")

_local = threading.local()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def get_connection() -> sqlite3.Connection:
    """Return a per-thread SQLite connection (created on first use)."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = _connect()
    return _local.conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    username     TEXT,
    first_name   TEXT NOT NULL,
    balance      INTEGER NOT NULL DEFAULT 0,
    referred_by  INTEGER,
    last_checkin TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id           TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(user_id),
    amount       INTEGER NOT NULL,
    type         TEXT NOT NULL,
    reference_id TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(user_id),
    model_key       TEXT NOT NULL,
    job_type        TEXT NOT NULL,
    prompt          TEXT NOT NULL,
    cost            INTEGER NOT NULL,
    input_image_url TEXT,
    fal_request_id  TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    output_url      TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS credit_packages (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    price_rm       REAL NOT NULL,
    bonus_percent  INTEGER NOT NULL DEFAULT 0,
    credits_sen    INTEGER NOT NULL,
    is_active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS payment_settings (
    id                     INTEGER PRIMARY KEY DEFAULT 1,
    payment_instructions   TEXT,
    qr_image_url           TEXT,
    payment_expiry_minutes INTEGER NOT NULL DEFAULT 30
);

CREATE TABLE IF NOT EXISTS topup_requests (
    id              TEXT PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(user_id),
    package_id      INTEGER NOT NULL REFERENCES credit_packages(id),
    amount_rm       REAL NOT NULL,
    bonus_percent   INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'awaiting_receipt',
    receipt_file_id TEXT,
    admin_id        INTEGER,
    admin_note      TEXT,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    processed_at    TEXT
);

CREATE TABLE IF NOT EXISTS conversation_state (
    user_id          INTEGER PRIMARY KEY REFERENCES users(user_id),
    step             TEXT,
    job_type         TEXT,
    model_key        TEXT,
    ratio            TEXT,
    prompt           TEXT,
    image_url        TEXT,
    bot_message_id   INTEGER,
    bot_chat_id      INTEGER,
    topup_request_id TEXT,
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS referrals (
    referrer_id INTEGER NOT NULL REFERENCES users(user_id),
    referred_id INTEGER NOT NULL PRIMARY KEY REFERENCES users(user_id),
    bonus_paid  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS app_settings (
    id                   INTEGER PRIMARY KEY DEFAULT 1,
    maintenance_mode     INTEGER NOT NULL DEFAULT 0,
    maintenance_message  TEXT    DEFAULT 'Bot dalam penyelenggaraan. Sila cuba lagi kemudian.',
    admin_away_mode      INTEGER NOT NULL DEFAULT 0,
    admin_away_message   TEXT    DEFAULT 'Admin sedang tidak berada. Semakan mungkin mengambil masa lebih lama.'
);

-- Ensure a settings row always exists
INSERT OR IGNORE INTO app_settings (id) VALUES (1);

CREATE TABLE IF NOT EXISTS broadcast_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    message      TEXT    NOT NULL,
    sent_count   INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = _connect()
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
