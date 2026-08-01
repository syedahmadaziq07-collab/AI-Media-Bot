-- JagoVideo Clone — Supabase schema
-- Run this entire script in your Supabase SQL editor before first deploy.

-- ── Tables ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    user_id     BIGINT PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    balance     INTEGER NOT NULL DEFAULT 0,
    language    TEXT NOT NULL DEFAULT 'ms',
    referred_by BIGINT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_checkin TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS transactions (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users(user_id),
    type         TEXT NOT NULL,
    amount       INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    reference_id TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(user_id),
    model_key       TEXT NOT NULL,
    job_type        TEXT NOT NULL,
    prompt          TEXT NOT NULL,
    input_image_url TEXT,
    fal_request_id  TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    output_url      TEXT,
    cost            INTEGER NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS referrals (
    referrer_id BIGINT NOT NULL REFERENCES users(user_id),
    referred_id BIGINT PRIMARY KEY REFERENCES users(user_id),
    bonus_paid  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS credit_packages (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    price_rm      NUMERIC(10,2) NOT NULL,
    credit_sen    INTEGER NOT NULL,
    bonus_percent INTEGER NOT NULL DEFAULT 0,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS payment_settings (
    id                      INTEGER PRIMARY KEY DEFAULT 1,
    qr_image_url            TEXT,
    payment_instructions    TEXT,
    payment_expiry_minutes  INTEGER NOT NULL DEFAULT 30
);

CREATE TABLE IF NOT EXISTS topup_requests (
    id              TEXT PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(user_id),
    package_id      INTEGER NOT NULL REFERENCES credit_packages(id),
    amount_rm       NUMERIC(10,2) NOT NULL,
    bonus_percent   INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'awaiting_receipt',
    receipt_file_id TEXT,
    admin_id        BIGINT,
    admin_note      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    processed_at    TIMESTAMPTZ
);

-- Stores per-user conversation step for stateless serverless operation.
CREATE TABLE IF NOT EXISTS conversation_state (
    user_id          BIGINT PRIMARY KEY REFERENCES users(user_id),
    step             TEXT,
    job_type         TEXT,
    model_key        TEXT,
    ratio            TEXT,
    prompt           TEXT,
    image_url        TEXT,
    bot_message_id   BIGINT,
    bot_chat_id      BIGINT,
    topup_request_id TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Indexes ────────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_user        ON jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_fal_req     ON jobs(fal_request_id);
CREATE INDEX IF NOT EXISTS idx_topup_user       ON topup_requests(user_id);

-- ── Seed data ──────────────────────────────────────────────────────────────────

INSERT INTO credit_packages (name, price_rm, credit_sen, bonus_percent, is_active)
VALUES
    ('Starter',  10.00,  1000, 0,  TRUE),
    ('Standard', 25.00,  2500, 10, TRUE),
    ('Pro',      50.00,  5000, 20, TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO payment_settings (id, payment_instructions, payment_expiry_minutes)
VALUES (1, 'Bayar jumlah yang ditetapkan dan hantar resit.', 30)
ON CONFLICT (id) DO NOTHING;

-- ── RPCs (required for atomic balance mutations) ───────────────────────────────

CREATE OR REPLACE FUNCTION deduct_credit(
    p_user_id     BIGINT,
    p_amount      INTEGER,
    p_type        TEXT,
    p_reference_id TEXT
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_balance     INTEGER;
    v_new_balance INTEGER;
BEGIN
    SELECT balance INTO v_balance FROM users WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'User % not found', p_user_id;
    END IF;
    IF v_balance < p_amount THEN
        RAISE EXCEPTION 'Baki tidak mencukupi';
    END IF;
    v_new_balance := v_balance - p_amount;
    UPDATE users SET balance = v_new_balance WHERE user_id = p_user_id;
    INSERT INTO transactions (user_id, type, amount, balance_after, reference_id, created_at)
    VALUES (p_user_id, p_type, -p_amount, v_new_balance, p_reference_id, NOW());
    RETURN v_new_balance;
END;
$$;

CREATE OR REPLACE FUNCTION add_credit(
    p_user_id     BIGINT,
    p_amount      INTEGER,
    p_type        TEXT,
    p_reference_id TEXT
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_new_balance INTEGER;
BEGIN
    UPDATE users SET balance = balance + p_amount
    WHERE user_id = p_user_id
    RETURNING balance INTO v_new_balance;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'User % not found', p_user_id;
    END IF;
    INSERT INTO transactions (user_id, type, amount, balance_after, reference_id, created_at)
    VALUES (p_user_id, p_type, p_amount, v_new_balance, p_reference_id, NOW());
    RETURN v_new_balance;
END;
$$;

-- Optional: leaderboard RPC (used in db/queries.py with fallback)
CREATE OR REPLACE FUNCTION leaderboard_top(p_limit INTEGER DEFAULT 10)
RETURNS TABLE(user_id BIGINT, completed BIGINT)
LANGUAGE sql
AS $$
    SELECT user_id, COUNT(*) AS completed
    FROM jobs
    WHERE status = 'completed'
    GROUP BY user_id
    ORDER BY completed DESC
    LIMIT p_limit;
$$;
