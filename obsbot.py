#!/usr/bin/env python3
# =============================================================
# OBS PRO BOT — ARQUIVO ÚNICO (RAILWAY READY)
#
# ✅ Web (Streamlit):
#   streamlit run dashboard.py --server.port $PORT --server.address 0.0.0.0
#
# ✅ Bot 24/7 (Worker):
#   python dashboard.py --bot
#
# Banco:
# - Se tiver DATABASE_URL => Postgres (Railway)
# - Senão => SQLite local (DB_PATH)
#
# Requirements (requirements.txt):
# streamlit
# pandas
# requests
# ccxt
# streamlit-autorefresh
# psycopg2-binary
#
# =============================================================

import os
import sys
import time
import hashlib
import logging
from datetime import datetime, timedelta

import pandas as pd
import requests

BOT_MODE = "--bot" in sys.argv

# =============================================================
# CONFIG (via ENV no Railway)
# =============================================================
DB_PATH = os.getenv("DB_PATH", "mvp_funds.db")

DEFAULT_ADMIN_USER = os.getenv("DEFAULT_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASS = os.getenv("DEFAULT_ADMIN_PASS", "87347748")  # MUDE via Railway Variables

DEPOSIT_ADDRESS_FIXED = os.getenv("DEPOSIT_ADDRESS_FIXED", "0xBa4D5e87e8bcaA85bF29105AB3171b9fDb2eF9dd")
DEPOSIT_NETWORK_LABEL = os.getenv("DEPOSIT_NETWORK_LABEL", "ERC20")

WITHDRAW_FEE_RATE = float(os.getenv("WITHDRAW_FEE_RATE", "0.05"))

BOT_SYMBOL        = os.getenv("BOT_SYMBOL", "BTC/USDT")
TAKE_PROFIT       = float(os.getenv("TAKE_PROFIT", "0.004"))   # 0.4%
STOP_LOSS         = float(os.getenv("STOP_LOSS", "0.003"))     # 0.3%
FEE_RATE_EST      = float(os.getenv("FEE_RATE_EST", "0.001"))  # 0.1%
ORDER_USDT_FRAC   = float(os.getenv("ORDER_USDT_FRAC", "1.00"))
MIN_USDT_ORDER    = float(os.getenv("MIN_USDT_ORDER", "10.0"))
BOT_LOOP_INTERVAL = int(os.getenv("BOT_LOOP_INTERVAL", "15"))
MIN_HOLD_SECONDS  = int(os.getenv("MIN_HOLD_SECONDS", "0"))

SESSION_SECRET    = os.getenv("SESSION_SECRET", "CHANGE_ME_ON_RAILWAY")

# =============================================================
# DB LAYER (Postgres on Railway via DATABASE_URL, else SQLite)
# =============================================================
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
IS_POSTGRES = DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")

def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def make_code(username: str) -> str:
    return sha256(username + "|code")[:8]

def db_connect():
    """
    Returns a DB-API connection.
    Postgres: psycopg2
    SQLite: sqlite3
    """
    if IS_POSTGRES:
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

def db_exec(sql: str, params=None):
    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        conn.commit()
        return True
    finally:
        conn.close()

def db_one(sql: str, params=None):
    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur.fetchone()
    finally:
        conn.close()

def db_all(sql: str, params=None):
    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur.fetchall()
    finally:
        conn.close()

def init_db():
    conn = db_connect()
    try:
        cur = conn.cursor()

        if IS_POSTGRES:
            # Postgres schema
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            SERIAL PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL,
                pass_hash     TEXT NOT NULL,
                role          TEXT NOT NULL CHECK(role IN ('admin','user')),
                created_at    TEXT NOT NULL,
                referrer_code TEXT,
                my_code       TEXT UNIQUE
            )""")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS user_keys (
                user_id    INTEGER PRIMARY KEY,
                exchange   TEXT NOT NULL DEFAULT 'binance',
                api_key    TEXT NOT NULL,
                api_secret TEXT NOT NULL,
                testnet    INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )""")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS deposits (
                id              SERIAL PRIMARY KEY,
                user_id         INTEGER NOT NULL,
                amount_usdt     DOUBLE PRECISION NOT NULL,
                txid            TEXT,
                deposit_address TEXT,
                status          TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED')),
                created_at      TEXT NOT NULL,
                reviewed_at     TEXT,
                reviewed_by     INTEGER,
                note            TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )""")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id                  SERIAL PRIMARY KEY,
                user_id             INTEGER NOT NULL,
                amount_request_usdt DOUBLE PRECISION NOT NULL,
                fee_rate            DOUBLE PRECISION NOT NULL,
                fee_usdt            DOUBLE PRECISION NOT NULL,
                amount_net_usdt     DOUBLE PRECISION NOT NULL,
                network             TEXT,
                address             TEXT,
                paid_txid           TEXT,
                status              TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED','PAID')),
                created_at          TEXT NOT NULL,
                reviewed_at         TEXT,
                reviewed_by         INTEGER,
                note                TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )""")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS ledger (
                id          SERIAL PRIMARY KEY,
                user_id     INTEGER NOT NULL,
                kind        TEXT NOT NULL CHECK(kind IN ('DEPOSIT','WITHDRAWAL','ADJUST')),
                amount_usdt DOUBLE PRECISION NOT NULL,
                ref_table   TEXT,
                ref_id      INTEGER,
                created_at  TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )""")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                user_id      INTEGER PRIMARY KEY,
                enabled      INTEGER NOT NULL DEFAULT 0,
                usdt         DOUBLE PRECISION NOT NULL DEFAULT 0,
                asset        DOUBLE PRECISION NOT NULL DEFAULT 0,
                in_position  INTEGER NOT NULL DEFAULT 0,
                entry_price  DOUBLE PRECISION,
                entry_qty    DOUBLE PRECISION,
                entry_time   TEXT,
                last_step_ts TEXT,
                last_error   TEXT,
                updated_at   TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )""")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_trades (
                id            SERIAL PRIMARY KEY,
                user_id       INTEGER NOT NULL,
                time          TEXT NOT NULL,
                symbol        TEXT NOT NULL,
                side          TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
                price         DOUBLE PRECISION NOT NULL,
                qty           DOUBLE PRECISION NOT NULL,
                fee_usdt      DOUBLE PRECISION NOT NULL,
                usdt_balance  DOUBLE PRECISION NOT NULL,
                asset_balance DOUBLE PRECISION NOT NULL,
                reason        TEXT,
                pnl_usdt      DOUBLE PRECISION,
                order_id      TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )""")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )""")

        else:
            # SQLite schema (your original)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL,
                pass_hash     TEXT NOT NULL,
                role          TEXT NOT NULL CHECK(role IN ('admin','user')),
                created_at    TEXT NOT NULL,
                referrer_code TEXT,
                my_code       TEXT UNIQUE
            )""")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS user_keys (
                user_id    INTEGER PRIMARY KEY,
                exchange   TEXT NOT NULL DEFAULT 'binance',
                api_key    TEXT NOT NULL,
                api_secret TEXT NOT NULL,
                testnet    INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )""")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS deposits (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                amount_usdt     REAL NOT NULL,
                txid            TEXT,
                deposit_address TEXT,
                status          TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED')),
                created_at      TEXT NOT NULL,
                reviewed_at     TEXT,
                reviewed_by     INTEGER,
                note            TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )""")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             INTEGER NOT NULL,
                amount_request_usdt REAL NOT NULL,
                fee_rate            REAL NOT NULL,
                fee_usdt            REAL NOT NULL,
                amount_net_usdt     REAL NOT NULL,
                network             TEXT,
                address             TEXT,
                paid_txid           TEXT,
                status              TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED','PAID')),
                created_at          TEXT NOT NULL,
                reviewed_at         TEXT,
                reviewed_by         INTEGER,
                note                TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )""")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS ledger (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                kind        TEXT NOT NULL CHECK(kind IN ('DEPOSIT','WITHDRAWAL','ADJUST')),
                amount_usdt REAL NOT NULL,
                ref_table   TEXT,
                ref_id      INTEGER,
                created_at  TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )""")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                user_id      INTEGER PRIMARY KEY,
                enabled      INTEGER NOT NULL DEFAULT 0,
                usdt         REAL NOT NULL DEFAULT 0,
                asset        REAL NOT NULL DEFAULT 0,
                in_position  INTEGER NOT NULL DEFAULT 0,
                entry_price  REAL,
                entry_qty    REAL,
                entry_time   TEXT,
                last_step_ts TEXT,
                last_error   TEXT,
                updated_at   TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )""")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_trades (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                time          TEXT NOT NULL,
                symbol        TEXT NOT NULL,
                side          TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
                price         REAL NOT NULL,
                qty           REAL NOT NULL,
                fee_usdt      REAL NOT NULL,
                usdt_balance  REAL NOT NULL,
                asset_balance REAL NOT NULL,
                reason        TEXT,
                pnl_usdt      REAL,
                order_id      TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )""")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )""")

        conn.commit()

        # create default admin if not exists
        cur.execute("SELECT id FROM users WHERE username=%s" if IS_POSTGRES else "SELECT id FROM users WHERE username=?",
                    (DEFAULT_ADMIN_USER,))
        if cur.fetchone() is None:
            cur.execute(
                ("INSERT INTO users (username, pass_hash, role, created_at, my_code) VALUES (%s,%s,%s,%s,%s)"
                 if IS_POSTGRES else
                 "INSERT INTO users (username, pass_hash, role, created_at, my_code) VALUES (?,?,?,?,?)"),
                (DEFAULT_ADMIN_USER, sha256(DEFAULT_ADMIN_PASS), "admin", _now(), make_code(DEFAULT_ADMIN_USER))
            )
            conn.commit()

    finally:
        conn.close()

# =============================================================
# USERS / AUTH
# =============================================================
def get_user_by_username(username: str):
    username = (username or "").strip()
    if not username:
        return None
    sql = """SELECT id, username, pass_hash, role, created_at, referrer_code, my_code
             FROM users WHERE username=%s""" if IS_POSTGRES else \
          """SELECT id, username, pass_hash, role, created_at, referrer_code, my_code
             FROM users WHERE username=?"""
    return db_one(sql, (username,))

def get_user_by_id(user_id: int):
    sql = """SELECT id, username, pass_hash, role, created_at, referrer_code, my_code
             FROM users WHERE id=%s""" if IS_POSTGRES else \
          """SELECT id, username, pass_hash, role, created_at, referrer_code, my_code
             FROM users WHERE id=?"""
    return db_one(sql, (int(user_id),))

def auth(username: str, password: str):
    u = get_user_by_username(username)
    return u if u and sha256(password or "") == u[2] else None

def create_user(username: str, password: str, role: str, referrer_code=None):
    username = (username or "").strip()
    password = password or ""
    if not username or not password:
        raise ValueError("Preencha usuário e senha.")
    if role not in ("admin", "user"):
        raise ValueError("Role inválida.")
    if referrer_code:
        sql = "SELECT id FROM users WHERE my_code=%s" if IS_POSTGRES else "SELECT id FROM users WHERE my_code=?"
        if not db_one(sql, (referrer_code.strip(),)):
            raise ValueError("Código de indicação inválido.")

    try:
        sql = ("INSERT INTO users (username, pass_hash, role, created_at, referrer_code, my_code) "
               "VALUES (%s,%s,%s,%s,%s,%s)") if IS_POSTGRES else \
              ("INSERT INTO users (username, pass_hash, role, created_at, referrer_code, my_code) "
               "VALUES (?,?,?,?,?,?)")
        db_exec(sql, (username, sha256(password), role, _now(),
                     referrer_code.strip() if referrer_code else None,
                     make_code(username)))
    except Exception as e:
        msg = str(e).lower()
        if "unique" in msg or "duplicate" in msg or "integrity" in msg:
            raise ValueError("Usuário já existe.")
        raise

def list_users():
    sql = "SELECT id, username, role, created_at, my_code FROM users ORDER BY id"
    return db_all(sql)

# =============================================================
# SESSIONS (persistent)
# =============================================================
def create_session(user_id: int) -> str:
    token = sha256(f"{user_id}|{time.time()}|{SESSION_SECRET}")
    expires = (datetime.now() + timedelta(days=30)).isoformat(sep=" ", timespec="seconds")

    # one active session per user
    sql_del = "DELETE FROM sessions WHERE user_id=%s" if IS_POSTGRES else "DELETE FROM sessions WHERE user_id=?"
    db_exec(sql_del, (int(user_id),))

    sql_ins = ("INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (%s,%s,%s,%s)"
               if IS_POSTGRES else
               "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)")
    db_exec(sql_ins, (token, int(user_id), _now(), expires))
    return token

def get_session_user(token: str):
    token = (token or "").strip()
    if not token:
        return None
    sql = "SELECT user_id, expires_at FROM sessions WHERE token=%s" if IS_POSTGRES else \
          "SELECT user_id, expires_at FROM sessions WHERE token=?"
    row = db_one(sql, (token,))
    if not row:
        return None
    user_id, expires_at = row
    try:
        if datetime.fromisoformat(expires_at) < datetime.now():
            return None
    except Exception:
        return None
    return get_user_by_id(int(user_id))

def delete_session(token: str):
    token = (token or "").strip()
    if not token:
        return
    sql = "DELETE FROM sessions WHERE token=%s" if IS_POSTGRES else "DELETE FROM sessions WHERE token=?"
    db_exec(sql, (token,))

# =============================================================
# API KEYS
# =============================================================
def save_user_keys(user_id: int, api_key: str, api_secret: str, testnet: bool = False):
    api_key = (api_key or "").strip()
    api_secret = (api_secret or "").strip()
    if not api_key or not api_secret:
        raise ValueError("API Key e Secret são obrigatórios.")

    sql_sel = "SELECT user_id FROM user_keys WHERE user_id=%s" if IS_POSTGRES else \
              "SELECT user_id FROM user_keys WHERE user_id=?"
    exists = db_one(sql_sel, (int(user_id),)) is not None

    if exists:
        sql_upd = ("UPDATE user_keys SET api_key=%s, api_secret=%s, testnet=%s, updated_at=%s WHERE user_id=%s"
                   if IS_POSTGRES else
                   "UPDATE user_keys SET api_key=?, api_secret=?, testnet=?, updated_at=? WHERE user_id=?")
        db_exec(sql_upd, (api_key, api_secret, int(testnet), _now(), int(user_id)))
    else:
        sql_ins = ("INSERT INTO user_keys (user_id, exchange, api_key, api_secret, testnet, updated_at) "
                   "VALUES (%s,%s,%s,%s,%s,%s)") if IS_POSTGRES else \
                  ("INSERT INTO user_keys (user_id, exchange, api_key, api_secret, testnet, updated_at) "
                   "VALUES (?,?,?,?,?,?)")
        db_exec(sql_ins, (int(user_id), "binance", api_key, api_secret, int(testnet), _now()))

def get_user_keys(user_id: int):
    sql = "SELECT api_key, api_secret, testnet FROM user_keys WHERE user_id=%s" if IS_POSTGRES else \
          "SELECT api_key, api_secret, testnet FROM user_keys WHERE user_id=?"
    return db_one(sql, (int(user_id),))

# =============================================================
# LEDGER / BALANCE
# =============================================================
def add_ledger(user_id: int, kind: str, amount_usdt: float, ref_table=None, ref_id=None):
    sql = ("INSERT INTO ledger (user_id, kind, amount_usdt, ref_table, ref_id, created_at) "
           "VALUES (%s,%s,%s,%s,%s,%s)") if IS_POSTGRES else \
          ("INSERT INTO ledger (user_id, kind, amount_usdt, ref_table, ref_id, created_at) "
           "VALUES (?,?,?,?,?,?)")
    db_exec(sql, (int(user_id), kind, float(amount_usdt), ref_table, ref_id, _now()))

def user_balance(user_id: int) -> float:
    sql = "SELECT COALESCE(SUM(amount_usdt),0) FROM ledger WHERE user_id=%s" if IS_POSTGRES else \
          "SELECT COALESCE(SUM(amount_usdt),0) FROM ledger WHERE user_id=?"
    row = db_one(sql, (int(user_id),))
    return float(row[0] or 0.0) if row else 0.0

# =============================================================
# DEPOSITS
# =============================================================
def create_deposit(user_id: int, amount_usdt: float, txid: str):
    txid = (txid or "").strip()
    if not txid:
        raise ValueError("TXID é obrigatório.")
    sql = ("INSERT INTO deposits (user_id, amount_usdt, txid, deposit_address, status, created_at) "
           "VALUES (%s,%s,%s,%s,%s,%s)") if IS_POSTGRES else \
          ("INSERT INTO deposits (user_id, amount_usdt, txid, deposit_address, status, created_at) "
           "VALUES (?,?,?,?,?,?)")
    db_exec(sql, (int(user_id), float(amount_usdt), txid, DEPOSIT_ADDRESS_FIXED, "PENDING", _now()))

def list_deposits(user_id=None):
    if user_id is None:
        sql = ("""SELECT d.id, u.username, d.amount_usdt, d.txid, d.status,
                         d.created_at, d.reviewed_at, d.note
                  FROM deposits d JOIN users u ON u.id=d.user_id
                  ORDER BY d.id DESC""")
        return db_all(sql)
    else:
        sql = ("""SELECT d.id, d.amount_usdt, d.txid, d.status,
                         d.created_at, d.reviewed_at, d.note
                  FROM deposits d WHERE d.user_id=%s
                  ORDER BY d.id DESC""" if IS_POSTGRES else
               """SELECT d.id, d.amount_usdt, d.txid, d.status,
                         d.created_at, d.reviewed_at, d.note
                  FROM deposits d WHERE d.user_id=?
                  ORDER BY d.id DESC""")
        return db_all(sql, (int(user_id),))

def admin_review_deposit(deposit_id: int, approve: bool, admin_id: int, note: str = ""):
    sql = "SELECT user_id, amount_usdt, status FROM deposits WHERE id=%s" if IS_POSTGRES else \
          "SELECT user_id, amount_usdt, status FROM deposits WHERE id=?"
    row = db_one(sql, (int(deposit_id),))
    if not row:
        raise ValueError("Depósito não encontrado.")
    user_id, amt, status = row
    if status != "PENDING":
        raise ValueError("Já revisado.")
    new_status = "APPROVED" if approve else "REJECTED"

    sql_upd = ("UPDATE deposits SET status=%s, reviewed_at=%s, reviewed_by=%s, note=%s WHERE id=%s"
               if IS_POSTGRES else
               "UPDATE deposits SET status=?, reviewed_at=?, reviewed_by=?, note=? WHERE id=?")
    db_exec(sql_upd, (new_status, _now(), int(admin_id), note, int(deposit_id)))

    if approve:
        add_ledger(int(user_id), "DEPOSIT", float(amt), "deposits", int(deposit_id))

# =============================================================
# WITHDRAWALS
# =============================================================
def create_withdrawal(user_id: int, amount_usdt: float, network: str, address: str):
    bal = user_balance(int(user_id))
    if amount_usdt <= 0:
        raise ValueError("Valor inválido.")
    if amount_usdt > bal:
        raise ValueError(f"Saldo insuficiente: {bal:.2f} USDT")
    network = (network or "").strip()
    address = (address or "").strip()
    if not network or not address:
        raise ValueError("Rede e endereço obrigatórios.")

    fee = float(amount_usdt) * WITHDRAW_FEE_RATE
    net = float(amount_usdt) - fee

    sql = ("""INSERT INTO withdrawals
              (user_id,amount_request_usdt,fee_rate,fee_usdt,amount_net_usdt,network,address,status,created_at)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""" if IS_POSTGRES else
           """INSERT INTO withdrawals
              (user_id,amount_request_usdt,fee_rate,fee_usdt,amount_net_usdt,network,address,status,created_at)
              VALUES (?,?,?,?,?,?,?,?,?)""")
    db_exec(sql, (int(user_id), float(amount_usdt), float(WITHDRAW_FEE_RATE), float(fee),
                  float(net), network, address, "PENDING", _now()))

def list_withdrawals(user_id=None):
    if user_id is None:
        sql = ("""SELECT w.id, u.username, w.amount_request_usdt, w.fee_usdt, w.amount_net_usdt,
                         w.network, w.address, w.paid_txid, w.status, w.created_at, w.reviewed_at, w.note
                  FROM withdrawals w JOIN users u ON u.id=w.user_id
                  ORDER BY w.id DESC""")
        return db_all(sql)
    else:
        sql = ("""SELECT w.id, w.amount_request_usdt, w.fee_usdt, w.amount_net_usdt,
                         w.network, w.address, w.paid_txid, w.status, w.created_at, w.reviewed_at, w.note
                  FROM withdrawals w WHERE w.user_id=%s
                  ORDER BY w.id DESC""" if IS_POSTGRES else
               """SELECT w.id, w.amount_request_usdt, w.fee_usdt, w.amount_net_usdt,
                         w.network, w.address, w.paid_txid, w.status, w.created_at, w.reviewed_at, w.note
                  FROM withdrawals w WHERE w.user_id=?
                  ORDER BY w.id DESC""")
        return db_all(sql, (int(user_id),))

def admin_review_withdrawal(wid: int, approve: bool, admin_id: int, note: str = ""):
    sql = "SELECT user_id, amount_request_usdt, status FROM withdrawals WHERE id=%s" if IS_POSTGRES else \
          "SELECT user_id, amount_request_usdt, status FROM withdrawals WHERE id=?"
    row = db_one(sql, (int(wid),))
    if not row:
        raise ValueError("Saque não encontrado.")
    user_id, amt, status = row
    if status != "PENDING":
        raise ValueError("Já revisado.")
    new_status = "APPROVED" if approve else "REJECTED"

    sql_upd = ("UPDATE withdrawals SET status=%s, reviewed_at=%s, reviewed_by=%s, note=%s WHERE id=%s"
               if IS_POSTGRES else
               "UPDATE withdrawals SET status=?, reviewed_at=?, reviewed_by=?, note=? WHERE id=?")
    db_exec(sql_upd, (new_status, _now(), int(admin_id), note, int(wid)))

    if approve:
        add_ledger(int(user_id), "WITHDRAWAL", -float(amt), "withdrawals", int(wid))

def admin_mark_withdraw_paid(wid: int, admin_id: int, paid_txid: str, note: str = ""):
    paid_txid = (paid_txid or "").strip()
    if not paid_txid:
        raise ValueError("TXID do pagamento é obrigatório.")

    sql = "SELECT status FROM withdrawals WHERE id=%s" if IS_POSTGRES else \
          "SELECT status FROM withdrawals WHERE id=?"
    row = db_one(sql, (int(wid),))
    if not row:
        raise ValueError("Saque não encontrado.")
    if row[0] != "APPROVED":
        raise ValueError("Precisa estar APPROVED.")

    sql_upd = ("UPDATE withdrawals SET status='PAID', paid_txid=%s, reviewed_at=%s, reviewed_by=%s, note=%s WHERE id=%s"
               if IS_POSTGRES else
               "UPDATE withdrawals SET status='PAID', paid_txid=?, reviewed_at=?, reviewed_by=?, note=? WHERE id=?")
    db_exec(sql_upd, (paid_txid, _now(), int(admin_id), note, int(wid)))

# =============================================================
# BOT STATE / TRADES
# =============================================================
def get_bot_state(user_id: int) -> dict:
    sql = ("""SELECT user_id, enabled, usdt, asset, in_position,
                     entry_price, entry_qty, entry_time, last_step_ts, last_error, updated_at
              FROM bot_state WHERE user_id=%s""" if IS_POSTGRES else
           """SELECT user_id, enabled, usdt, asset, in_position,
                     entry_price, entry_qty, entry_time, last_step_ts, last_error, updated_at
              FROM bot_state WHERE user_id=?""")
    row = db_one(sql, (int(user_id),))
    if not row:
        return {}
    keys = ["user_id","enabled","usdt","asset","in_position",
            "entry_price","entry_qty","entry_time","last_step_ts","last_error","updated_at"]
    return dict(zip(keys, row))

def upsert_bot_state(user_id, enabled, usdt, asset, in_position,
                     entry_price, entry_qty, entry_time, last_step_ts, last_error=None):
    exists = db_one(("SELECT user_id FROM bot_state WHERE user_id=%s" if IS_POSTGRES else
                     "SELECT user_id FROM bot_state WHERE user_id=?"), (int(user_id),)) is not None

    if exists:
        sql = ("""UPDATE bot_state SET enabled=%s, usdt=%s, asset=%s, in_position=%s,
                  entry_price=%s, entry_qty=%s, entry_time=%s, last_step_ts=%s,
                  last_error=%s, updated_at=%s WHERE user_id=%s""" if IS_POSTGRES else
               """UPDATE bot_state SET enabled=?, usdt=?, asset=?, in_position=?,
                  entry_price=?, entry_qty=?, entry_time=?, last_step_ts=?,
                  last_error=?, updated_at=? WHERE user_id=?""")
        db_exec(sql, (int(enabled), float(usdt), float(asset), int(in_position),
                      entry_price, entry_qty, entry_time, last_step_ts,
                      last_error, _now(), int(user_id)))
    else:
        sql = ("""INSERT INTO bot_state
                  (user_id,enabled,usdt,asset,in_position,entry_price,entry_qty,
                   entry_time,last_step_ts,last_error,updated_at)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""" if IS_POSTGRES else
               """INSERT INTO bot_state
                  (user_id,enabled,usdt,asset,in_position,entry_price,entry_qty,
                   entry_time,last_step_ts,last_error,updated_at)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?)""")
        db_exec(sql, (int(user_id), int(enabled), float(usdt), float(asset), int(in_position),
                      entry_price, entry_qty, entry_time, last_step_ts, last_error, _now()))

def insert_bot_trade(user_id, side, price, qty, fee_usdt,
                     usdt_balance, asset_balance, reason, pnl_usdt, order_id=None):
    sql = ("""INSERT INTO bot_trades
              (user_id,time,symbol,side,price,qty,fee_usdt,usdt_balance,asset_balance,reason,pnl_usdt,order_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""" if IS_POSTGRES else
           """INSERT INTO bot_trades
              (user_id,time,symbol,side,price,qty,fee_usdt,usdt_balance,asset_balance,reason,pnl_usdt,order_id)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""")
    db_exec(sql, (int(user_id), _now(), BOT_SYMBOL, side, float(price), float(qty), float(fee_usdt),
                  float(usdt_balance), float(asset_balance), reason, pnl_usdt, order_id))

def load_bot_trades(user_id: int, limit: int = 300) -> pd.DataFrame:
    conn = db_connect()
    try:
        if IS_POSTGRES:
            df = pd.read_sql_query(
                """SELECT time, symbol, side, price, qty, fee_usdt,
                          usdt_balance, asset_balance, reason, pnl_usdt, order_id
                   FROM bot_trades WHERE user_id=%s ORDER BY time DESC LIMIT %s""",
                conn, params=(int(user_id), int(limit))
            )
        else:
            df = pd.read_sql_query(
                """SELECT time, symbol, side, price, qty, fee_usdt,
                          usdt_balance, asset_balance, reason, pnl_usdt, order_id
                   FROM bot_trades WHERE user_id=? ORDER BY time DESC LIMIT ?""",
                conn, params=(int(user_id), int(limit))
            )
    finally:
        conn.close()

    if not df.empty:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.sort_values("time").reset_index(drop=True)
    return df

def compute_metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"sells": 0, "wins": 0, "losses": 0, "winrate": 0.0, "pnl": 0.0}
    sells = df[df["side"].str.upper() == "SELL"].copy()
    sells["pnl_usdt"] = pd.to_numeric(sells["pnl_usdt"], errors="coerce")
    wins   = int((sells["pnl_usdt"] > 0).sum())
    losses = int((sells["pnl_usdt"] < 0).sum())
    total  = wins + losses
    return {
        "sells": total,
        "wins": wins,
        "losses": losses,
        "winrate": wins / total * 100 if total else 0.0,
        "pnl": float(sells["pnl_usdt"].sum()) if not sells.empty else 0.0,
    }

def get_all_active_bot_users():
    sql = ("""SELECT bs.user_id FROM bot_state bs
              JOIN user_keys uk ON uk.user_id = bs.user_id
              WHERE bs.enabled = 1""")
    rows = db_all(sql)
    return [int(r[0]) for r in rows]

# =============================================================
# BOT RUNNER
# =============================================================
def _save_error(user_id: int, msg: str):
    s = get_bot_state(user_id)
    if not s:
        return
    upsert_bot_state(
        user_id,
        int(s.get("enabled") or 1),
        float(s.get("usdt") or 0),
        float(s.get("asset") or 0),
        int(s.get("in_position") or 0),
        s.get("entry_price"),
        s.get("entry_qty"),
        s.get("entry_time"),
        _now(),
        last_error=(msg or "")[:500],
    )

def bot_step(user_id: int):
    try:
        import ccxt
    except ImportError:
        logging.error("ccxt não instalado!"); return

    keys = get_user_keys(user_id)
    if not keys:
        logging.warning(f"[user {user_id}] Sem chaves API."); return

    api_key, api_secret, testnet = keys
    try:
        exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "options": {"defaultType": "spot"},
            "enableRateLimit": True,
        })
        if int(testnet) == 1:
            exchange.set_sandbox_mode(True)
    except Exception as e:
        logging.error(f"[user {user_id}] Falha exchange: {e}")
        _save_error(user_id, str(e)); return

    s = get_bot_state(user_id)
    now = datetime.now()

    if not s:
        try:
            bal   = exchange.fetch_balance()
            u_bal = float(bal["free"].get("USDT", 0))
            a_bal = float(bal["free"].get("BTC",  0))
        except Exception:
            u_bal, a_bal = 0.0, 0.0
        upsert_bot_state(user_id, 1, u_bal, a_bal, 0, None, None, None, None, None)
        return

    if not int(s.get("enabled") or 0):
        return

    usdt        = float(s.get("usdt")  or 0.0)
    asset       = float(s.get("asset") or 0.0)
    in_pos      = int(s.get("in_position") or 0)
    entry_price = s.get("entry_price")
    entry_qty   = s.get("entry_qty")
    entry_time  = s.get("entry_time")

    try:
        price = float(exchange.fetch_ticker(BOT_SYMBOL)["last"])
    except Exception as e:
        logging.warning(f"[user {user_id}] Sem preço: {e}")
        _save_error(user_id, str(e)); return

    if in_pos == 0:
        if usdt < MIN_USDT_ORDER:
            upsert_bot_state(user_id, 1, usdt, 0.0, 0, None, None, None, _now(), None)
            return
        try:
            buy_usdt = usdt * ORDER_USDT_FRAC
            qty_est  = exchange.amount_to_precision(BOT_SYMBOL, buy_usdt / price)
            order    = exchange.create_market_buy_order(BOT_SYMBOL, float(qty_est))

            oid = str(order.get("id", ""))
            fp  = float(order.get("average") or order.get("price") or price)
            fq  = float(order.get("filled")  or qty_est)
            fee_r = fp * fq * FEE_RATE_EST

            bal = exchange.fetch_balance()
            un  = float(bal["free"].get("USDT", 0))
            an  = float(bal["free"].get("BTC",  0))

            upsert_bot_state(
                user_id, 1, un, an, 1, fp, fq,
                now.isoformat(sep=" ", timespec="seconds"),
                _now(), None
            )
            insert_bot_trade(user_id, "BUY", fp, fq, fee_r, un, an, "BUY_AUTO", None, oid)
            logging.info(f"[user {user_id}] ✅ BUY @ {fp:.2f} | qty={fq:.8f}")
        except Exception as e:
            logging.error(f"[user {user_id}] Erro ao comprar: {e}")
            _save_error(user_id, str(e))
        return

    if in_pos == 1 and entry_price and entry_qty:
        ep_f = float(entry_price)
        eq_f = float(entry_qty)
        tp   = ep_f * (1 + TAKE_PROFIT)
        sl   = ep_f * (1 - STOP_LOSS)

        held_ok = True
        if entry_time and MIN_HOLD_SECONDS > 0:
            try:
                et = datetime.fromisoformat(entry_time)
                held_ok = (now - et).total_seconds() >= MIN_HOLD_SECONDS
            except Exception:
                pass

        exit_reason = None
        if held_ok and price >= tp:
            exit_reason = "TAKE_PROFIT"
        elif price <= sl:
            exit_reason = "STOP_LOSS"

        if exit_reason:
            try:
                qs    = exchange.amount_to_precision(BOT_SYMBOL, asset)
                order = exchange.create_market_sell_order(BOT_SYMBOL, float(qs))

                oid   = str(order.get("id", ""))
                sp    = float(order.get("average") or order.get("price") or price)
                sq    = float(order.get("filled")  or asset)
                gross = sp * sq
                fee_r = gross * FEE_RATE_EST
                pnl   = (gross - fee_r) - (ep_f * eq_f)

                bal   = exchange.fetch_balance()
                un    = float(bal["free"].get("USDT", 0))
                an    = float(bal["free"].get("BTC",  0))

                upsert_bot_state(user_id, 1, un, an, 0, None, None, None, _now(), None)
                insert_bot_trade(user_id, "SELL", sp, sq, fee_r, un, an, exit_reason, pnl, oid)
                logging.info(f"[user {user_id}] {'🟢' if pnl>0 else '🔴'} SELL ({exit_reason}) @ {sp:.2f} | pnl={pnl:.4f}")
            except Exception as e:
                logging.error(f"[user {user_id}] Erro ao vender: {e}")
                _save_error(user_id, str(e))
        else:
            upsert_bot_state(user_id, 1, usdt, asset, 1, entry_price, entry_qty,
                             entry_time, _now(), s.get("last_error"))

def run_bot_loop():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler()]
    )
    init_db()
    log = logging.getLogger("obspro")
    log.info("=" * 55)
    log.info("OBS PRO BOT — RUNNER (Railway Worker)")
    log.info(f"Par: {BOT_SYMBOL} | TP: {TAKE_PROFIT*100:.2f}% | SL: {STOP_LOSS*100:.2f}%")
    log.info(f"Intervalo: {BOT_LOOP_INTERVAL}s")
    log.info("=" * 55)

    while True:
        try:
            ativos = get_all_active_bot_users()
            if ativos:
                log.info(f"Ciclo — {len(ativos)} usuário(s): {ativos}")
                for uid in ativos:
                    try:
                        bot_step(uid)
                    except Exception as e:
                        log.error(f"[user {uid}] {e}", exc_info=True)
            else:
                log.info("Nenhum bot ativo.")
        except Exception as e:
            log.critical(f"Erro fatal: {e}", exc_info=True)

        time.sleep(BOT_LOOP_INTERVAL)

if BOT_MODE:
    run_bot_loop()
    sys.exit(0)

# =============================================================
# STREAMLIT WEB
# =============================================================
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except Exception:
    HAS_AUTOREFRESH = False

init_db()
st.set_page_config(page_title="OBS PRO — BOT", layout="wide")
st.set_option("client.showErrorDetails", True)

def fetch_price_display(symbol: str):
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": symbol.replace("/", "").upper()},
            timeout=6
        )
        if r.status_code == 200:
            return float(r.json()["price"])
    except Exception:
        pass
    return None

# query params compatibility
def _get_sid():
    try:
        sid = st.query_params.get("sid", "")
    except Exception:
        sid = st.experimental_get_query_params().get("sid", [""])[0]
    if isinstance(sid, list):
        sid = sid[0] if sid else ""
    return (sid or "").strip()

def _set_sid(token: str):
    try:
        st.query_params["sid"] = token
    except Exception:
        st.experimental_set_query_params(sid=token)

def _clear_sid():
    try:
        st.query_params.clear()
    except Exception:
        st.experimental_set_query_params()

def do_login(user):
    token = create_session(user[0])
    st.session_state.user = user
    st.session_state.token = token
    _set_sid(token)

def do_logout():
    token = st.session_state.get("token", "")
    if token:
        delete_session(token)
    st.session_state.user = None
    st.session_state.token = ""
    _clear_sid()
    st.rerun()

# init state
st.session_state.setdefault("user", None)
st.session_state.setdefault("token", "")

# recover session from URL
if st.session_state.user is None:
    sid = _get_sid()
    if sid:
        recovered = get_session_user(sid)
        if recovered:
            st.session_state.user = recovered
            st.session_state.token = sid
        else:
            _clear_sid()

# ── Sidebar: login/register only ─────────────────────────────
with st.sidebar:
    st.header("🔐 Login")
    if st.session_state.user:
        st.success(f"Logado: {st.session_state.user[1]} ({st.session_state.user[3]})")
        if st.button("Sair", use_container_width=True):
            do_logout()
    else:
        lu = st.text_input("Usuário", key="li_u")
        lp = st.text_input("Senha", type="password", key="li_p")
        if st.button("Entrar", use_container_width=True):
            user = auth(lu, lp)
            if user:
                do_login(user)
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos.")

    st.divider()
    st.header("🧾 Cadastro")
    nu  = st.text_input("Novo usuário", key="reg_u")
    np_ = st.text_input("Nova senha", type="password", key="reg_p")
    rc  = st.text_input("Código indicação (opcional)", key="reg_c")
    if st.button("Criar conta", use_container_width=True):
        try:
            create_user(nu, np_, "user", rc or None)
            st.success("Conta criada! Faça login.")
        except Exception as e:
            st.error(str(e))

st.title("OBS PRO — BOT 🤖")
st.caption(f"{BOT_SYMBOL} | TP {TAKE_PROFIT*100:.2f}% | SL {STOP_LOSS*100:.2f}%")

if not st.session_state.user:
    st.info("Faça login na barra lateral.")
    st.stop()

# ✅ auto-refresh só quando logado (evita tela branca)
if HAS_AUTOREFRESH:
    st.session_state.setdefault("auto_ref", True)
    st.session_state.setdefault("ref_sec", 15)

    with st.sidebar:
        st.divider()
        st.caption("🔁 Auto atualização (logado)")
        st.session_state.auto_ref = st.checkbox("Ativar", value=st.session_state.auto_ref, key="auto_ref_chk")
        st.session_state.ref_sec  = st.slider("Intervalo (s)", 5, 60, int(st.session_state.ref_sec), key="ref_sec_sld")

    if st.session_state.auto_ref:
        st_autorefresh(interval=int(st.session_state.ref_sec) * 1000, key="ar_logged")

user = st.session_state.user
user_id, username, _, role, created_at, referrer_code, my_code = user

tab_names = ["📊 Painel BOT","👤 Minha Conta","🔑 Chaves API","💰 Aporte","💸 Saque","📄 Extrato"]
if role == "admin":
    tab_names.append("⚙️ Administração")
tabs = st.tabs(tab_names)

# =============================================================
# TAB 0 — PAINEL BOT
# =============================================================
with tabs[0]:
    has_keys = get_user_keys(user_id) is not None
    s = get_bot_state(user_id)

    if not has_keys:
        st.warning("⚠️ Cadastre suas chaves API na aba **🔑 Chaves API** antes de operar.")

    bot_on = bool(int(s.get("enabled") or 0)) if s else False
    new_on = st.toggle("🟢 Operar na Binance (REAL)", value=bot_on, disabled=not has_keys)

    if s and int(s.get("enabled") or 0) != int(new_on):
        upsert_bot_state(
            user_id, int(new_on),
            float(s.get("usdt") or 0),
            float(s.get("asset") or 0),
            int(s.get("in_position") or 0),
            s.get("entry_price"), s.get("entry_qty"), s.get("entry_time"),
            s.get("last_step_ts"), s.get("last_error")
        )
        st.rerun()
    elif not s and new_on:
        upsert_bot_state(user_id, 1, 0.0, 0.0, 0, None, None, None, None, None)
        st.rerun()

    if not s:
        st.info("Ative o bot para iniciar.")
        st.stop()

    s = get_bot_state(user_id)
    if s.get("last_error"):
        st.error(f"🚨 Último erro: {s.get('last_error')}")

    if s.get("last_step_ts"):
        st.caption(f"⏱ Último ciclo do runner: `{s.get('last_step_ts')}`")

    price_now = fetch_price_display(BOT_SYMBOL)
    bot_usdt  = float(s.get("usdt") or 0.0)
    bot_asset = float(s.get("asset") or 0.0)
    in_pos    = int(s.get("in_position") or 0)
    entry_price = s.get("entry_price")
    entry_time  = s.get("entry_time")

    pos_txt = "🟡 COMPRADO" if in_pos else "⚪ FLAT"
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("USDT (exchange)", f"{bot_usdt:.2f}")
    c2.metric("BTC em carteira", f"{bot_asset:.6f}")
    c3.metric("Posição", pos_txt)
    c4.metric("Preço atual", f"{price_now:.2f}" if price_now else "—")

    if in_pos and entry_price:
        ep = float(entry_price)
        tp_p = ep * (1 + TAKE_PROFIT)
        sl_p = ep * (1 - STOP_LOSS)

        st.divider()
        a,b,c_,d = st.columns(4)
        a.metric("Entrada", f"{ep:.2f}")
        b.metric("Take Profit", f"{tp_p:.2f}")
        c_.metric("Stop Loss", f"{sl_p:.2f}")

        if price_now:
            pct = (price_now / ep - 1) * 100
            d.metric("P&L atual", f"{pct:+.3f}%")

        if entry_time:
            try:
                secs = int((datetime.now() - datetime.fromisoformat(entry_time)).total_seconds())
                st.caption(f"⏱ Em posição há {secs}s")
            except Exception:
                pass

    st.divider()
    st.subheader("📈 Performance")
    df_tr = load_bot_trades(user_id, 500)
    m = compute_metrics(df_tr)

    m1,m2,m3,m4 = st.columns(4)
    m1.metric("Total vendas", f"{m['sells']}")
    m2.metric("Winrate", f"{m['winrate']:.1f}%")
    m3.metric("PnL realizado", f"{m['pnl']:.4f} USDT")
    m4.metric("Ganhos/Perdas", f"{m['wins']}W / {m['losses']}L")

    st.subheader("📋 Histórico")
    if df_tr.empty:
        st.info("Sem operações. Rode o Worker: `python dashboard.py --bot`")
    else:
        st.dataframe(df_tr.tail(200), use_container_width=True)

# =============================================================
# TAB 1 — MINHA CONTA
# =============================================================
with tabs[1]:
    bal = user_balance(user_id)
    c1,c2,c3 = st.columns(3)
    c1.metric("Usuário", username)
    c2.metric("Saldo ledger", f"{bal:.2f} USDT")
    c3.metric("Meu código", my_code)
    if referrer_code:
        st.caption(f"Indicado por: `{referrer_code}`")

# =============================================================
# TAB 2 — CHAVES API
# =============================================================
with tabs[2]:
    st.subheader("🔑 Chaves API Binance")
    st.warning("⚠️ Use chaves com permissão apenas de **Spot Trading**. NUNCA habilite saque.")

    ex = get_user_keys(user_id)
    if ex:
        st.success(f"✅ Chaves cadastradas | Key: `{ex[0][:8]}...` | Testnet: {'Sim' if int(ex[2]) else 'Não'}")

    with st.form("form_keys"):
        nk  = st.text_input("API Key", type="password")
        ns  = st.text_input("API Secret", type="password")
        tn  = st.checkbox("Usar Testnet (recomendado p/ testes)", value=False)
        if st.form_submit_button("💾 Salvar chaves"):
            try:
                save_user_keys(user_id, nk, ns, tn)
                st.success("✅ Chaves salvas!")
                st.rerun()
            except Exception as e:
                st.error(str(e))

# =============================================================
# TAB 3 — APORTE
# =============================================================
with tabs[3]:
    st.subheader("💰 Aporte em USDT")
    st.markdown(f"**Rede:** `{DEPOSIT_NETWORK_LABEL}`")
    st.code(DEPOSIT_ADDRESS_FIXED)
    st.caption("Envie USDT e cole o TXID. O admin confirmará o crédito.")

    amt_d  = st.number_input("Valor (USDT)", min_value=0.0, step=10.0, format="%.2f")
    txid_d = st.text_input("TXID / Hash da transação")
    if st.button("📤 Enviar comprovante", use_container_width=True):
        try:
            if amt_d <= 0:
                st.error("Informe um valor.")
            else:
                create_deposit(user_id, amt_d, txid_d)
                st.success("Enviado! Aguarde aprovação.")
        except Exception as e:
            st.error(str(e))

    st.divider()
    rows = list_deposits(user_id=user_id)
    if rows:
        st.dataframe(pd.DataFrame(rows, columns=["id","valor","txid","status","criado","revisado","nota"]),
                     use_container_width=True)
    else:
        st.info("Sem aportes ainda.")

# =============================================================
# TAB 4 — SAQUE
# =============================================================
with tabs[4]:
    st.subheader("💸 Solicitar saque")
    bal = user_balance(user_id)
    st.metric("Saldo disponível", f"{bal:.2f} USDT")

    amt_w = st.number_input("Valor (USDT)", min_value=0.0, step=10.0, format="%.2f", key="amt_w")
    net_w = st.selectbox("Rede", ["TRC20","BEP20","ERC20"])
    adr_w = st.text_input("Endereço destino")

    fee_w = amt_w * WITHDRAW_FEE_RATE
    liq_w = amt_w - fee_w
    c1,c2,c3 = st.columns(3)
    c1.metric("Taxa", f"{WITHDRAW_FEE_RATE*100:.0f}%")
    c2.metric("Taxa (USDT)", f"{fee_w:.2f}")
    c3.metric("Você recebe", f"{liq_w:.2f}")

    if st.button("📤 Solicitar saque", use_container_width=True):
        try:
            if amt_w <= 0:
                st.error("Informe um valor.")
            else:
                create_withdrawal(user_id, amt_w, net_w, adr_w)
                st.success("Solicitado! Aguarde aprovação.")
        except Exception as e:
            st.error(str(e))

    st.divider()
    rows = list_withdrawals(user_id=user_id)
    if rows:
        st.dataframe(pd.DataFrame(rows, columns=["id","valor","taxa","liquido","rede","endereco","txid_pago","status","criado","revisado","nota"]),
                     use_container_width=True)
    else:
        st.info("Sem saques ainda.")

# =============================================================
# TAB 5 — EXTRATO
# =============================================================
with tabs[5]:
    st.subheader("📄 Extrato")
    conn = db_connect()
    try:
        if IS_POSTGRES:
            df_led = pd.read_sql_query(
                """SELECT created_at, kind, amount_usdt, ref_table, ref_id
                   FROM ledger WHERE user_id=%s ORDER BY created_at DESC LIMIT 500""",
                conn, params=(int(user_id),)
            )
        else:
            df_led = pd.read_sql_query(
                """SELECT created_at, kind, amount_usdt, ref_table, ref_id
                   FROM ledger WHERE user_id=? ORDER BY created_at DESC LIMIT 500""",
                conn, params=(int(user_id),)
            )
    finally:
        conn.close()

    if df_led.empty:
        st.info("Sem movimentações.")
    else:
        st.dataframe(df_led, use_container_width=True)
        st.download_button("⬇️ Baixar CSV", df_led.to_csv(index=False).encode("utf-8"),
                           "extrato.csv", "text/csv", use_container_width=True)

# =============================================================
# TAB 6 — ADMIN
# =============================================================
if role == "admin":
    with tabs[6]:
        st.subheader("⚙️ Administração")

        st.markdown("### 👥 Usuários")
        ul = list_users()
        if ul:
            st.dataframe(pd.DataFrame(ul, columns=["id","username","role","criado","codigo"]),
                         use_container_width=True)

        st.divider()
        st.markdown("### 💰 Aportes pendentes")
        dep_all = list_deposits()
        dep_df = pd.DataFrame(dep_all, columns=["id","username","valor","txid","status","criado","revisado","nota"])
        pend_d = dep_df[dep_df["status"] == "PENDING"]
        if pend_d.empty:
            st.info("Nenhum aporte pendente.")
        else:
            st.dataframe(pend_d, use_container_width=True)
            did = st.number_input("ID do depósito", min_value=1, step=1, key="did")
            dn  = st.text_input("Nota", key="dn")
            c1,c2 = st.columns(2)
            with c1:
                if st.button("✅ Aprovar", use_container_width=True):
                    try:
                        admin_review_deposit(int(did), True, user_id, dn)
                        st.success("Aprovado!")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with c2:
                if st.button("❌ Rejeitar", use_container_width=True):
                    try:
                        admin_review_deposit(int(did), False, user_id, dn)
                        st.warning("Rejeitado.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

        st.divider()
        st.markdown("### 💸 Saques pendentes")
        w_all = list_withdrawals()
        w_df = pd.DataFrame(w_all, columns=["id","username","valor_req","taxa","liquido","rede","endereco","txid_pago","status","criado","revisado","nota"])
        pend_w = w_df[w_df["status"] == "PENDING"]
        if pend_w.empty:
            st.info("Nenhum saque pendente.")
        else:
            st.dataframe(pend_w, use_container_width=True)
            wid = st.number_input("ID do saque", min_value=1, step=1, key="wid")
            wn  = st.text_input("Nota", key="wn")
            c1,c2 = st.columns(2)
            with c1:
                if st.button("✅ Aprovar saque", use_container_width=True):
                    try:
                        admin_review_withdrawal(int(wid), True, user_id, wn)
                        st.success("Aprovado!")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with c2:
                if st.button("❌ Rejeitar saque", use_container_width=True):
                    try:
                        admin_review_withdrawal(int(wid), False, user_id, wn)
                        st.warning("Rejeitado.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

        st.divider()
        st.markdown("### ✅ Marcar saque como PAGO")
        aprov_w = w_df[w_df["status"] == "APPROVED"]
        if aprov_w.empty:
            st.info("Nenhum saque aprovado aguardando pagamento.")
        else:
            st.dataframe(aprov_w, use_container_width=True)
            wid2 = st.number_input("ID saque aprovado", min_value=1, step=1, key="wid2")
            ptxid = st.text_input("TXID do pagamento (obrigatório)", key="ptxid")
            pn = st.text_input("Nota", key="pn")
            if st.button("💳 Marcar como PAGO", use_container_width=True):
                try:
                    admin_mark_withdraw_paid(int(wid2), user_id, ptxid, pn)
                    st.success("Marcado como PAGO!")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

        st.divider()
        st.markdown("### 🤖 Status dos bots")
        conn = db_connect()
        try:
            q = """
                SELECT u.username, bs.enabled, bs.usdt, bs.asset, bs.in_position,
                       bs.entry_price, bs.last_step_ts, bs.last_error,
                       CASE WHEN uk.user_id IS NOT NULL THEN 'Sim' ELSE 'Não' END as tem_chave
                FROM bot_state bs
                JOIN users u ON u.id = bs.user_id
                LEFT JOIN user_keys uk ON uk.user_id = bs.user_id
                ORDER BY u.username
            """
            df_bots = pd.read_sql_query(q, conn)
        finally:
            conn.close()

        if not df_bots.empty:
            st.dataframe(df_bots, use_container_width=True)
        else:
            st.info("Nenhum bot ativo ainda.")