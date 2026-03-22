#!/usr/bin/env python3
# =============================================================
# OBS PRO BOT — VERSÃO 5.0.0 — TODAS AS CORREÇÕES
#
# CORREÇÕES v5.0.0:
#   ✅ Taxa cobrada na VENDA (não na compra)
#   ✅ Saldo mínimo desativado (MIN_DEPOSIT_TO_ACTIVATE = 0)
#   ✅ Exchange com cache — sem MemoryError a cada 15s
#   ✅ Log com rotação automática (5MB)
# =============================================================

import os
import sys
import logging.handlers

import sys

_raw_argv = sys.argv[1:]
BOT_MODE = "--bot" in _raw_argv and not any("streamlit" in a for a in _raw_argv)

import sqlite3
import hashlib
import time
import secrets
import logging
import threading
import requests
import bcrypt
from datetime import datetime, timedelta
import pandas as pd

_DB_LOCK = threading.Lock()

# =============================================================
# ★ CONFIG — EDITE AQUI ★
# =============================================================
DB_PATH = "mvp_funds.db"
DB_PATH = os.environ.get("DB_PATH", DB_PATH)
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = os.environ.get("DEFAULT_ADMIN_PASS", "")
DEPOSIT_ADDRESS_FIXED = "TMYvfwaT8XX998h6dP9JVWxgdPxY88cLmt"
DEPOSIT_NETWORK_LABEL = "TRC20"
WITHDRAW_FEE_RATE = 0.05

ALL_SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
]

BOT_SYMBOLS = ALL_SYMBOLS
BOT_SYMBOL = ALL_SYMBOLS[0]

SYMBOL_ASSET = {
    "BTC/USDT": "BTC",
    "ETH/USDT": "ETH",
}

BANCA_FRAC_POR_PAR = 0.45
MAX_PARES_SIMULTANEOS = 2

TAKE_PROFIT = 0.0075
STOP_LOSS   = 0.0045

FEE_RATE_EST = 0.001
ORDER_USDT_FRAC = 0.95
MIN_USDT_ORDER = 10.0
USDT_PER_SYMBOL = 20.0
MIN_DEPOSIT_TO_ACTIVATE = 0.0   # v5.0.0: desativado — sem bloqueio por saldo
TRADE_FEE = 0.50                # taxa por operação cobrada na VENDA
BOT_LOOP_INTERVAL = 15
MIN_HOLD_SECONDS = 420

RSI_PERIOD = 14
EMA_FAST = 9
EMA_SLOW = 21
EMA_TREND = 200
RSI_MIN = 46
RSI_MAX = 60
CANDLE_INTERVAL = "5m"
CANDLE_INTERVAL_H1 = "1h"
CANDLE_LIMIT = 50
CANDLE_LIMIT_H1 = 210
COOLDOWN_AFTER_SL = 1200

ATR_PERIOD = 14
ATR_MIN_PCT = 0.0015
EMA_TREND_4H = 50
USE_ATR_FILTER = True
USE_4H_FILTER = True

# ── v4.9.3 — filtros de entrada relaxados ────────────────────
MACD_LINE_MIN = -2.0
USE_RSI_ENTRY = True
RSI_ENTRY_MIN = 47
RSI_ENTRY_MAX = 62

# ── v4.9.4 ───────────────────────────────────────────────────
USE_EMA_EXIT = False
USE_TIME_FILTER = False
TRADE_HOUR_START = 1
TRADE_HOUR_END = 15

USE_TRAILING_STOP = True
TRAILING_ACTIVATION = 0.0045
TRAILING_DISTANCE = 0.0020

RSI_EXIT = 70
USE_RSI_EXIT = True

USE_ENGULFING_PATTERN = False
USE_DOUBLE_ENGULFING_PATTERN = False
USE_OUTSIDE_BAR_PATTERN = False
USE_CANDLESTICK_CONFIRM = False

SESSION_SECRET = os.environ.get("SESSION_SECRET", "")

# ── v5.0.0 — cache de exchange ────────────────────────────────
EXCHANGE_REBUILD_INTERVAL = 3600  # reconstrói a cada 1h


# =============================================================
# DATABASE
# =============================================================
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def sha256(s): return hashlib.sha256(s.encode()).hexdigest()
def make_code(u): return sha256(u + "|code")[:8]
def _now(): return datetime.now().isoformat(sep=" ", timespec="seconds")


def _is_production_env():
    env = (os.environ.get("APP_ENV") or os.environ.get("ENV") or "").strip().lower()
    return env in {"prod", "production"}


def _resolve_initial_admin_password():
    if DEFAULT_ADMIN_PASS:
        return DEFAULT_ADMIN_PASS
    if _is_production_env():
        raise RuntimeError("DEFAULT_ADMIN_PASS é obrigatório em produção.")
    generated = secrets.token_urlsafe(24)
    logging.warning("DEFAULT_ADMIN_PASS não definido; senha admin inicial temporária gerada para ambiente não-produção.")
    return generated


def is_bcrypt_hash(pass_hash):
    return isinstance(pass_hash, str) and pass_hash.startswith(("$2a$", "$2b$", "$2y$"))


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password, stored_hash):
    if is_bcrypt_hash(stored_hash):
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    return sha256(password) == stored_hash


def init_db():
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()

        cur.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
            pass_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','user')),
            created_at TEXT NOT NULL, referrer_code TEXT, my_code TEXT UNIQUE)""")

        cur.execute("""CREATE TABLE IF NOT EXISTS user_keys (
            user_id INTEGER PRIMARY KEY, exchange TEXT NOT NULL DEFAULT 'binance',
            api_key TEXT NOT NULL, api_secret TEXT NOT NULL, testnet INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id))""")

        cur.execute("""CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            amount_usdt REAL NOT NULL, txid TEXT, deposit_address TEXT,
            status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED')),
            created_at TEXT NOT NULL, reviewed_at TEXT, reviewed_by INTEGER, note TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id))""")

        cur.execute("""CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            amount_request_usdt REAL NOT NULL, fee_rate REAL NOT NULL, fee_usdt REAL NOT NULL,
            amount_net_usdt REAL NOT NULL, network TEXT, address TEXT, paid_txid TEXT,
            status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED','PAID')),
            created_at TEXT NOT NULL, reviewed_at TEXT, reviewed_by INTEGER, note TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id))""")

        cur.execute("""CREATE TABLE IF NOT EXISTS ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('DEPOSIT','WITHDRAWAL','ADJUST')),
            amount_usdt REAL NOT NULL, ref_table TEXT, ref_id INTEGER,
            created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id))""")

        cur.execute("""CREATE TABLE IF NOT EXISTS bot_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, symbol TEXT NOT NULL DEFAULT 'BTC/USDT',
            enabled INTEGER NOT NULL DEFAULT 0,
            usdt REAL NOT NULL DEFAULT 0, asset REAL NOT NULL DEFAULT 0,
            in_position INTEGER NOT NULL DEFAULT 0, entry_price REAL, entry_qty REAL,
            entry_time TEXT, last_step_ts TEXT, last_error TEXT, last_sl_time TEXT,
            daily_losses INTEGER NOT NULL DEFAULT 0, daily_loss_date TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, symbol),
            FOREIGN KEY(user_id) REFERENCES users(id))""")

        cur.execute("""CREATE TABLE IF NOT EXISTS bot_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            time TEXT NOT NULL, symbol TEXT NOT NULL,
            side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
            price REAL NOT NULL, qty REAL NOT NULL, fee_usdt REAL NOT NULL,
            usdt_balance REAL NOT NULL, asset_balance REAL NOT NULL,
            reason TEXT, pnl_usdt REAL, order_id TEXT,
            rsi_entry REAL, ema_signal TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id))""")

        cur.execute("""CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id))""")

        conn.commit()

        for m in [
            "ALTER TABLE bot_state ADD COLUMN last_error TEXT",
            "ALTER TABLE bot_state ADD COLUMN last_sl_time TEXT",
            "ALTER TABLE bot_state ADD COLUMN daily_losses INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE bot_state ADD COLUMN daily_loss_date TEXT",
            "ALTER TABLE bot_trades ADD COLUMN order_id TEXT",
            "ALTER TABLE bot_trades ADD COLUMN rsi_entry REAL",
            "ALTER TABLE bot_trades ADD COLUMN ema_signal TEXT",
            "ALTER TABLE bot_state ADD COLUMN symbol TEXT NOT NULL DEFAULT 'BTC/USDT'",
            "ALTER TABLE bot_state ADD COLUMN id INTEGER",
        ]:
            try:
                conn.execute(m); conn.commit()
            except:
                pass

        needs_migration = False
        try:
            cur2 = conn.cursor()
            cur2.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='bot_state'")
            ddl = (cur2.fetchone() or ("",))[0] or ""
            if "UNIQUE(user_id, symbol)" not in ddl and "user_id, symbol" not in ddl:
                needs_migration = True
        except:
            needs_migration = True

        if needs_migration:
            try:
                conn.execute("""CREATE TABLE IF NOT EXISTS bot_state_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL, symbol TEXT NOT NULL DEFAULT 'BTC/USDT',
                    enabled INTEGER NOT NULL DEFAULT 0,
                    usdt REAL NOT NULL DEFAULT 0, asset REAL NOT NULL DEFAULT 0,
                    in_position INTEGER NOT NULL DEFAULT 0, entry_price REAL, entry_qty REAL,
                    entry_time TEXT, last_step_ts TEXT, last_error TEXT, last_sl_time TEXT,
                    daily_losses INTEGER NOT NULL DEFAULT 0, daily_loss_date TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, symbol))""")
                conn.execute("""INSERT OR IGNORE INTO bot_state_new
                    (user_id, symbol, enabled, usdt, asset, in_position, entry_price, entry_qty,
                     entry_time, last_step_ts, last_error, last_sl_time, daily_losses, daily_loss_date, updated_at)
                    SELECT user_id, 'BTC/USDT', enabled, usdt, asset, in_position, entry_price, entry_qty,
                           entry_time, last_step_ts, last_error, last_sl_time,
                           COALESCE(daily_losses,0), daily_loss_date, updated_at
                    FROM bot_state""")
                conn.execute("DROP TABLE bot_state")
                conn.execute("ALTER TABLE bot_state_new RENAME TO bot_state")
                conn.commit()
                logging.info("✅ Migração v4.0: bot_state atualizado para multi-par!")
            except Exception as e:
                logging.warning(f"Migração bot_state: {e}")

        cur.execute("SELECT id FROM users WHERE username=?", (DEFAULT_ADMIN_USER,))
        if not cur.fetchone():
            admin_pass = _resolve_initial_admin_password()
            cur.execute("INSERT INTO users (username,pass_hash,role,created_at,my_code) VALUES (?,?,?,?,?)",
                        (DEFAULT_ADMIN_USER, hash_password(admin_pass), "admin", _now(),
                         make_code(DEFAULT_ADMIN_USER)))
            conn.commit()
        conn.close()


def get_user_by_username(username):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT id,username,pass_hash,role,created_at,referrer_code,my_code FROM users WHERE username=?",
                    (username,))
        row = cur.fetchone(); conn.close(); return row


def get_user_by_id(user_id):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT id,username,pass_hash,role,created_at,referrer_code,my_code FROM users WHERE id=?",
                    (user_id,))
        row = cur.fetchone(); conn.close(); return row


def auth(username, password):
    username = username.strip()
    if not username or password is None:
        return None
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT id,username,pass_hash,role,created_at,referrer_code,my_code FROM users WHERE username=?",
                    (username,))
        u = cur.fetchone()
        if not u:
            conn.close(); return None
        if not verify_password(password, u[2]):
            conn.close(); return None
        if not is_bcrypt_hash(u[2]):
            new_hash = hash_password(password)
            cur.execute("UPDATE users SET pass_hash=? WHERE id=?", (new_hash, u[0]))
            conn.commit()
            u = (u[0], u[1], new_hash, u[3], u[4], u[5], u[6])
        conn.close()
        return u


def create_user(username, password, role, referrer_code=None):
    username = username.strip()
    if not username or not password: raise ValueError("Preencha usuário e senha.")
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        if referrer_code:
            cur.execute("SELECT id FROM users WHERE my_code=?", (referrer_code.strip(),))
            if not cur.fetchone(): conn.close(); raise ValueError("Código de indicação inválido.")
        try:
            cur.execute(
                "INSERT INTO users (username,pass_hash,role,created_at,referrer_code,my_code) VALUES (?,?,?,?,?,?)",
                (username, hash_password(password), role, _now(),
                 referrer_code.strip() if referrer_code else None, make_code(username)))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close(); raise ValueError("Usuário já existe.")
        conn.close()


def list_users():
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT id,username,role,created_at,my_code FROM users ORDER BY id")
        rows = cur.fetchall(); conn.close(); return rows


def create_session(user_id):
    token = secrets.token_urlsafe(48)
    expires = (datetime.now() + timedelta(days=30)).isoformat(sep=" ", timespec="seconds")
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        cur.execute("INSERT INTO sessions (token,user_id,created_at,expires_at) VALUES (?,?,?,?)",
                    (token, user_id, _now(), expires))
        conn.commit(); conn.close()
    return token


def get_session_user(token):
    if not token: return None
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT user_id,expires_at FROM sessions WHERE token=?", (token,))
        row = cur.fetchone(); conn.close()
    if not row: return None
    user_id, expires_at = row
    try:
        if datetime.fromisoformat(expires_at) < datetime.now(): return None
    except:
        return None
    return get_user_by_id(user_id)


def delete_session(token):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit(); conn.close()


def save_user_keys(user_id, api_key, api_secret, testnet=False):
    if not api_key.strip() or not api_secret.strip(): raise ValueError("API Key e Secret são obrigatórios.")
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT user_id FROM user_keys WHERE user_id=?", (user_id,))
        if cur.fetchone():
            cur.execute("UPDATE user_keys SET api_key=?,api_secret=?,testnet=?,updated_at=? WHERE user_id=?",
                        (api_key.strip(), api_secret.strip(), int(testnet), _now(), user_id))
        else:
            cur.execute(
                "INSERT INTO user_keys (user_id,exchange,api_key,api_secret,testnet,updated_at) VALUES (?,?,?,?,?,?)",
                (user_id, "binance", api_key.strip(), api_secret.strip(), int(testnet), _now()))
        conn.commit(); conn.close()


def get_user_keys(user_id):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT api_key,api_secret,testnet FROM user_keys WHERE user_id=?", (user_id,))
        row = cur.fetchone(); conn.close(); return row


def add_ledger(user_id, kind, amount_usdt, ref_table=None, ref_id=None):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("INSERT INTO ledger (user_id,kind,amount_usdt,ref_table,ref_id,created_at) VALUES (?,?,?,?,?,?)",
                    (user_id, kind, float(amount_usdt), ref_table, ref_id, _now()))
        conn.commit(); conn.close()


def _add_ledger_tx(cur, user_id, kind, amount_usdt, ref_table=None, ref_id=None):
    cur.execute("INSERT INTO ledger (user_id,kind,amount_usdt,ref_table,ref_id,created_at) VALUES (?,?,?,?,?,?)",
                (user_id, kind, float(amount_usdt), ref_table, ref_id, _now()))


def user_balance(user_id):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(amount_usdt),0) FROM ledger WHERE user_id=?", (user_id,))
        bal = float(cur.fetchone()[0] or 0); conn.close(); return bal


def create_deposit(user_id, amount_usdt, txid):
    if not txid or not txid.strip(): raise ValueError("TXID é obrigatório.")
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO deposits (user_id,amount_usdt,txid,deposit_address,status,created_at) VALUES (?,?,?,?,?,?)",
            (user_id, float(amount_usdt), txid.strip(), DEPOSIT_ADDRESS_FIXED, "PENDING", _now()))
        conn.commit(); conn.close()


def list_deposits(user_id=None):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        if user_id is None:
            cur.execute("""SELECT d.id,u.username,d.amount_usdt,d.txid,d.status,d.created_at,d.reviewed_at,d.note
                           FROM deposits d JOIN users u ON u.id=d.user_id ORDER BY d.id DESC""")
        else:
            cur.execute("""SELECT d.id,d.amount_usdt,d.txid,d.status,d.created_at,d.reviewed_at,d.note
                           FROM deposits d WHERE d.user_id=? ORDER BY d.id DESC""", (user_id,))
        rows = cur.fetchall(); conn.close(); return rows


def ativar_bot_usuario(user_id):
    for sym in ALL_SYMBOLS:
        s = get_bot_state(user_id, sym)
        if s:
            upsert_bot_state(user_id, 1,
                             float(s.get("usdt") or 0), float(s.get("asset") or 0),
                             int(s.get("in_position") or 0),
                             s.get("entry_price"), s.get("entry_qty"), s.get("entry_time"),
                             s.get("last_step_ts"), s.get("last_error"), s.get("last_sl_time"),
                             int(s.get("daily_losses") or 0), s.get("daily_loss_date"), symbol=sym)
        else:
            upsert_bot_state(user_id, 1, 0.0, 0.0, 0, None, None, None, None, symbol=sym)


def desativar_bot_usuario(user_id):
    for sym in ALL_SYMBOLS:
        s = get_bot_state(user_id, sym)
        if s:
            upsert_bot_state(user_id, 0,
                             float(s.get("usdt") or 0), float(s.get("asset") or 0),
                             int(s.get("in_position") or 0),
                             s.get("entry_price"), s.get("entry_qty"), s.get("entry_time"),
                             s.get("last_step_ts"), s.get("last_error"), s.get("last_sl_time"),
                             int(s.get("daily_losses") or 0), s.get("daily_loss_date"), symbol=sym)


def admin_review_deposit(deposit_id, approve, admin_id, note=""):
    should_activate = False
    bal_total = 0.0
    user_id = None
    with _DB_LOCK:
        conn = db()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("SELECT user_id,amount_usdt,status FROM deposits WHERE id=?", (deposit_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError("Depósito não encontrado.")
            user_id, amt, status = row
            if status != "PENDING":
                raise ValueError("Já revisado.")
            new_status = "APPROVED" if approve else "REJECTED"
            cur.execute("UPDATE deposits SET status=?,reviewed_at=?,reviewed_by=?,note=? WHERE id=?",
                        (new_status, _now(), admin_id, note, deposit_id))
            if approve:
                _add_ledger_tx(cur, user_id, "DEPOSIT", float(amt), "deposits", deposit_id)
                cur.execute("SELECT COALESCE(SUM(amount_usdt),0) FROM ledger WHERE user_id=?", (user_id,))
                bal_total = float(cur.fetchone()[0] or 0)
                cur.execute("SELECT 1 FROM user_keys WHERE user_id=?", (user_id,))
                should_activate = cur.fetchone() is not None
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    if approve and should_activate:
        ativar_bot_usuario(user_id)
        logging.info(f"[admin] Bot ativado automaticamente para user {user_id} | saldo={bal_total:.2f}")


def create_withdrawal(user_id, amount_usdt, network, address):
    if amount_usdt <= 0: raise ValueError("Valor inválido.")
    if not network.strip() or not address.strip(): raise ValueError("Rede e endereço obrigatórios.")
    fee = amount_usdt * WITHDRAW_FEE_RATE
    net = amount_usdt - fee
    with _DB_LOCK:
        conn = db()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("SELECT COALESCE(SUM(amount_usdt),0) FROM ledger WHERE user_id=?", (user_id,))
            bal = float(cur.fetchone()[0] or 0)
            cur.execute("SELECT COALESCE(SUM(amount_request_usdt),0) FROM withdrawals WHERE user_id=? AND status='PENDING'",
                        (user_id,))
            pending = float(cur.fetchone()[0] or 0)
            available = bal - pending
            if amount_usdt > available:
                raise ValueError(f"Saldo insuficiente: {available:.2f} USDT")
            cur.execute("""INSERT INTO withdrawals
                (user_id,amount_request_usdt,fee_rate,fee_usdt,amount_net_usdt,network,address,status,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                        (user_id, float(amount_usdt), float(WITHDRAW_FEE_RATE), float(fee),
                         float(net), network.strip(), address.strip(), "PENDING", _now()))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def list_withdrawals(user_id=None):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        if user_id is None:
            cur.execute("""SELECT w.id,u.username,w.amount_request_usdt,w.fee_usdt,w.amount_net_usdt,
                                  w.network,w.address,w.paid_txid,w.status,w.created_at,w.reviewed_at,w.note
                           FROM withdrawals w JOIN users u ON u.id=w.user_id ORDER BY w.id DESC""")
        else:
            cur.execute("""SELECT w.id,w.amount_request_usdt,w.fee_usdt,w.amount_net_usdt,
                                  w.network,w.address,w.paid_txid,w.status,w.created_at,w.reviewed_at,w.note
                           FROM withdrawals w WHERE w.user_id=? ORDER BY w.id DESC""", (user_id,))
        rows = cur.fetchall(); conn.close(); return rows


def admin_review_withdrawal(wid, approve, admin_id, note=""):
    with _DB_LOCK:
        conn = db()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("SELECT user_id,amount_request_usdt,status FROM withdrawals WHERE id=?", (wid,))
            row = cur.fetchone()
            if not row:
                raise ValueError("Saque não encontrado.")
            user_id, amt, status = row
            if status != "PENDING":
                raise ValueError("Já revisado.")
            new_status = "APPROVED" if approve else "REJECTED"
            cur.execute("UPDATE withdrawals SET status=?,reviewed_at=?,reviewed_by=?,note=? WHERE id=?",
                        (new_status, _now(), admin_id, note, wid))
            if approve:
                _add_ledger_tx(cur, user_id, "WITHDRAWAL", -float(amt), "withdrawals", wid)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def admin_mark_withdraw_paid(wid, admin_id, paid_txid, note=""):
    if not paid_txid.strip(): raise ValueError("TXID do pagamento é obrigatório.")
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT status FROM withdrawals WHERE id=?", (wid,))
        row = cur.fetchone()
        if not row: conn.close(); raise ValueError("Saque não encontrado.")
        if row[0] != "APPROVED": conn.close(); raise ValueError("Precisa estar APPROVED.")
        cur.execute("UPDATE withdrawals SET status='PAID',paid_txid=?,reviewed_at=?,reviewed_by=?,note=? WHERE id=?",
                    (paid_txid.strip(), _now(), admin_id, note, wid))
        conn.commit(); conn.close()


def get_bot_state(user_id, symbol="BTC/USDT"):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("""SELECT user_id,symbol,enabled,usdt,asset,in_position,entry_price,entry_qty,
                              entry_time,last_step_ts,last_error,last_sl_time,
                              daily_losses,daily_loss_date,updated_at
                       FROM bot_state WHERE user_id=? AND symbol=?""", (user_id, symbol))
        row = cur.fetchone(); conn.close()
    if not row: return {}
    keys = ["user_id","symbol","enabled","usdt","asset","in_position","entry_price","entry_qty",
            "entry_time","last_step_ts","last_error","last_sl_time",
            "daily_losses","daily_loss_date","updated_at"]
    return dict(zip(keys, row))


def get_all_bot_states(user_id):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("""SELECT user_id,symbol,enabled,usdt,asset,in_position,entry_price,entry_qty,
                              entry_time,last_step_ts,last_error,last_sl_time,
                              daily_losses,daily_loss_date,updated_at
                       FROM bot_state WHERE user_id=? ORDER BY symbol""", (user_id,))
        rows = cur.fetchall(); conn.close()
    keys = ["user_id","symbol","enabled","usdt","asset","in_position","entry_price","entry_qty",
            "entry_time","last_step_ts","last_error","last_sl_time",
            "daily_losses","daily_loss_date","updated_at"]
    return [dict(zip(keys, row)) for row in rows]


def upsert_bot_state(user_id, enabled, usdt, asset, in_position,
                     entry_price, entry_qty, entry_time, last_step_ts,
                     last_error=None, last_sl_time=None,
                     daily_losses=0, daily_loss_date=None, symbol="BTC/USDT"):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT id FROM bot_state WHERE user_id=? AND symbol=?", (user_id, symbol))
        if cur.fetchone():
            cur.execute("""UPDATE bot_state SET enabled=?,usdt=?,asset=?,in_position=?,
                           entry_price=?,entry_qty=?,entry_time=?,last_step_ts=?,
                           last_error=?,last_sl_time=?,daily_losses=?,daily_loss_date=?,
                           updated_at=? WHERE user_id=? AND symbol=?""",
                        (enabled, float(usdt), float(asset), int(in_position),
                         entry_price, entry_qty, entry_time, last_step_ts,
                         last_error, last_sl_time, daily_losses, daily_loss_date,
                         _now(), user_id, symbol))
        else:
            cur.execute("""INSERT INTO bot_state
                           (user_id,symbol,enabled,usdt,asset,in_position,entry_price,entry_qty,
                            entry_time,last_step_ts,last_error,last_sl_time,
                            daily_losses,daily_loss_date,updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (user_id, symbol, enabled, float(usdt), float(asset), int(in_position),
                         entry_price, entry_qty, entry_time, last_step_ts,
                         last_error, last_sl_time, daily_losses, daily_loss_date, _now()))
        conn.commit(); conn.close()


def insert_bot_trade(user_id, side, price, qty, fee_usdt,
                     usdt_balance, asset_balance, reason, pnl_usdt,
                     order_id=None, rsi_entry=None, ema_signal=None, symbol="BTC/USDT"):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("""INSERT INTO bot_trades
            (user_id,time,symbol,side,price,qty,fee_usdt,usdt_balance,asset_balance,
             reason,pnl_usdt,order_id,rsi_entry,ema_signal)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (user_id, _now(), symbol, side, float(price), float(qty), float(fee_usdt),
                     float(usdt_balance), float(asset_balance), reason, pnl_usdt, order_id, rsi_entry, ema_signal))
        conn.commit(); conn.close()


def load_bot_trades(user_id, limit=300):
    with _DB_LOCK:
        conn = db()
        df = pd.read_sql_query(
            """SELECT time,symbol,side,price,qty,fee_usdt,usdt_balance,asset_balance,
                      reason,pnl_usdt,rsi_entry,ema_signal
               FROM bot_trades WHERE user_id=? ORDER BY time DESC LIMIT ?""",
            conn, params=(user_id, limit))
        conn.close()
    if not df.empty:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.sort_values("time").reset_index(drop=True)
    return df


def compute_metrics(df):
    if df.empty:
        return {"sells": 0, "wins": 0, "losses": 0, "winrate": 0.0, "pnl": 0.0}
    sells = df[df["side"].str.upper() == "SELL"].copy()
    sells["pnl_usdt"] = pd.to_numeric(sells["pnl_usdt"], errors="coerce")
    wins = int((sells["pnl_usdt"] > 0).sum())
    losses = int((sells["pnl_usdt"] < 0).sum())
    total = wins + losses
    return {"sells": total, "wins": wins, "losses": losses,
            "winrate": wins / total * 100 if total else 0.0,
            "pnl": float(sells["pnl_usdt"].sum()) if not sells.empty else 0.0}


def get_all_active_bot_users():
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("""SELECT DISTINCT bs.user_id FROM bot_state bs
                       JOIN user_keys uk ON uk.user_id=bs.user_id WHERE bs.enabled=1""")
        rows = cur.fetchall(); conn.close()
    return [r[0] for r in rows]


# =============================================================
# INDICADORES TÉCNICOS
# =============================================================
def calc_ema(closes, period):
    if len(closes) < period: return None
    k = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    for p in closes[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0: return 100.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 2)


def calc_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1: return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return atr


def calc_macd(closes, fast_period=12, slow_period=26, signal_period=9):
    if len(closes) < slow_period + signal_period: return None, None, None
    macd_line_series = []
    for i in range(len(closes)):
        if i >= slow_period - 1:
            fast_ema = calc_ema(closes[:i + 1], fast_period)
            slow_ema = calc_ema(closes[:i + 1], slow_period)
            if fast_ema is not None and slow_ema is not None:
                macd_line_series.append(fast_ema - slow_ema)
            else:
                macd_line_series.append(0)
        else:
            macd_line_series.append(0)
    macd_line = macd_line_series[-1]
    if len(macd_line_series) >= signal_period:
        signal_line = calc_ema(macd_line_series, signal_period)
    else:
        signal_line = None
    if signal_line is None:
        return macd_line, None, None
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def fetch_ema50_4h(exchange, symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, "4h", limit=60)
        if not ohlcv or len(ohlcv) < EMA_TREND_4H:
            return {"ok": False, "reason": f"Dados insuficientes 4H ({len(ohlcv) if ohlcv else 0} candles)"}
        closes = [float(c[4]) for c in ohlcv]
        closes = [c for c in closes if c > 0]
        if len(closes) < EMA_TREND_4H:
            return {"ok": False, "reason": "Closes zerados no 4H — par sem liquidez"}
        ema50 = calc_ema(closes, EMA_TREND_4H)
        if ema50 is None or ema50 == 0:
            return {"ok": False, "reason": "EMA50 4H zerada — par inválido"}
        price_now = closes[-1]
        above = price_now > ema50
        return {"ok": True, "ema50": ema50, "price": price_now, "above": above}
    except Exception as e:
        return {"ok": False, "reason": f"Erro EMA50 4H: {e}"}


def fetch_indicators_5m(exchange, symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, CANDLE_INTERVAL, limit=CANDLE_LIMIT)
        closes = [float(c[4]) for c in ohlcv]
        rsi = calc_rsi(closes, RSI_PERIOD)
        ema_fast = calc_ema(closes, EMA_FAST)
        ema_slow = calc_ema(closes, EMA_SLOW)
        macd_line, macd_signal, macd_hist = calc_macd(closes)
        if rsi is None or ema_fast is None or ema_slow is None or macd_line is None:
            return {"ok": False, "reason": "Dados insuficientes (5m)"}
        highs = [float(c[2]) for c in ohlcv]
        lows = [float(c[3]) for c in ohlcv]
        atr = calc_atr(highs, lows, closes, ATR_PERIOD)
        return {"ok": True, "rsi": rsi, "ema_fast": ema_fast, "ema_slow": ema_slow,
                "macd_line": macd_line, "macd_signal": macd_signal, "macd_hist": macd_hist,
                "closes": closes, "atr": atr}
    except Exception as e:
        return {"ok": False, "reason": f"Erro candles 5m: {e}"}


def fetch_ema200_h1(exchange, symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, CANDLE_INTERVAL_H1, limit=CANDLE_LIMIT_H1)
        closes = [float(c[4]) for c in ohlcv]
        ema200 = calc_ema(closes, EMA_TREND)
        if ema200 is None:
            return {"ok": False, "reason": "Dados insuficientes para EMA200 H1"}
        price_now = closes[-1]
        above = price_now > ema200
        return {"ok": True, "ema200": ema200, "price": price_now, "above": above}
    except Exception as e:
        return {"ok": False, "reason": f"Erro EMA200 H1: {e}"}


def check_entry_signal(exchange, symbol, log, user_id):
    if USE_TIME_FILTER:
        hora_atual = datetime.now().hour
        if not (TRADE_HOUR_START <= hora_atual < TRADE_HOUR_END):
            return False, f"⏰ Fora do horário de operação ({hora_atual}h — permitido {TRADE_HOUR_START}h-{TRADE_HOUR_END}h BRT)", None, None

    h1 = fetch_ema200_h1(exchange, symbol)
    if not h1.get("ok"):
        return False, f"EMA200 H1 indisponível: {h1.get('reason')}", None, None
    if not h1["above"]:
        return False, f"Preço({h1['price']:.6f}) < EMA200_H1({h1['ema200']:.6f}) — tendência de BAIXA", None, None

    if USE_4H_FILTER:
        h4 = fetch_ema50_4h(exchange, symbol)
        if not h4.get("ok"):
            return False, f"EMA50 4H indisponível: {h4.get('reason')}", None, None
        if not h4["above"]:
            return False, f"Preço({h4['price']:.0f}) < EMA50_4H({h4['ema50']:.0f}) — tendência 4H baixista", None, None

    ind = fetch_indicators_5m(exchange, symbol)
    if not ind.get("ok"):
        return False, f"Indicadores 5m: {ind.get('reason')}", None, None

    macd_line   = ind["macd_line"]
    macd_signal = ind["macd_signal"]
    macd_hist   = ind["macd_hist"]
    atr         = ind.get("atr")
    rsi         = ind.get("rsi")

    reasons = []

    if USE_ATR_FILTER and atr is not None:
        price_now = ind["closes"][-1]
        atr_pct = atr / price_now
        if atr_pct < ATR_MIN_PCT:
            reasons.append(f"ATR({atr_pct * 100:.3f}%) < mínimo({ATR_MIN_PCT * 100:.2f}%) — mercado LATERAL")

    if not (macd_line > 0):
        reasons.append(f"MACD linha({macd_line:.4f}) <= 0 — momentum insuficiente")

    if USE_RSI_ENTRY and rsi is not None:
        if not (RSI_ENTRY_MIN <= rsi <= RSI_ENTRY_MAX):
            reasons.append(f"RSI({rsi:.1f}) fora da faixa ({RSI_ENTRY_MIN}-{RSI_ENTRY_MAX})")

    macd_sig = f"MACD={macd_line:.4f} > 0" if macd_line > 0 else f"MACD={macd_line:.4f} <= 0"

    patterns = {}
    if USE_ENGULFING_PATTERN or USE_DOUBLE_ENGULFING_PATTERN or USE_OUTSIDE_BAR_PATTERN:
        patterns = check_candlestick_patterns(exchange, symbol)

    pattern_signals = []
    if USE_ENGULFING_PATTERN and patterns.get("engulfing_buy"):
        pattern_signals.append("Engulfing Bullish ✅")
    if USE_DOUBLE_ENGULFING_PATTERN and patterns.get("double_engulfing_buy"):
        pattern_signals.append("Double Engulfing ✅")
    if USE_OUTSIDE_BAR_PATTERN and patterns.get("outside_bar_buy"):
        pattern_signals.append("Outside Bar ✅")
    if USE_CANDLESTICK_CONFIRM and not pattern_signals:
        reasons.append("Nenhum padrão de vela bullish detectado")

    if reasons:
        return False, " | ".join(reasons), macd_line, macd_sig

    pattern_msg = " | " + " + ".join(pattern_signals) if pattern_signals else ""
    rsi_msg = f" | RSI={rsi:.1f}" if rsi is not None else ""
    log.info(f"[user {user_id}] ✅ ENTRADA | MACD={macd_line:.4f} | {macd_sig} | EMA200_H1 OK{rsi_msg}{pattern_msg}")
    return True, "Condições favoráveis", macd_line, macd_sig


def check_exit_signal(exchange, symbol, entry_price, log, user_id, entry_time=None):
    if entry_time and MIN_HOLD_SECONDS > 0:
        try:
            elapsed = (datetime.now() - datetime.fromisoformat(entry_time)).total_seconds()
            if elapsed < MIN_HOLD_SECONDS:
                return False, None
        except:
            pass

    ind = fetch_indicators_5m(exchange, symbol)
    if not ind.get("ok"):
        return False, None

    macd_line   = ind["macd_line"]
    macd_signal = ind["macd_signal"]

    if USE_EMA_EXIT and macd_line < macd_signal:
        log.info(f"[user {user_id}] 🔴 Saída MACD: linha({macd_line:.4f}) < sinal({macd_signal:.4f})")
        return True, "MACD_CROSS_DOWN"

    return False, None


# =============================================================
# PADRÕES DE VELAS
# =============================================================
def fetch_candles_for_patterns(exchange, symbol, interval="5m", limit=10):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, interval, limit=limit)
        if len(ohlcv) < 3: return None
        return {
            "opens":   [float(c[1]) for c in ohlcv],
            "highs":   [float(c[2]) for c in ohlcv],
            "lows":    [float(c[3]) for c in ohlcv],
            "closes":  [float(c[4]) for c in ohlcv],
            "volumes": [float(c[5]) for c in ohlcv],
        }
    except:
        return None


def is_engulfing_buy(candles):
    if not candles or len(candles["closes"]) < 2: return False
    c = candles["closes"]; o = candles["opens"]
    return (c[-2] < o[-2] and c[-1] > o[-1] and c[-1] > o[-2] and o[-1] <= c[-2])


def is_engulfing_sell(candles):
    if not candles or len(candles["closes"]) < 2: return False
    c = candles["closes"]; o = candles["opens"]
    return (c[-2] > o[-2] and c[-1] < o[-1] and c[-1] < o[-2] and o[-1] >= c[-2])


def is_double_engulfing_buy(candles):
    if not candles or len(candles["closes"]) < 3: return False
    c = candles["closes"]; o = candles["opens"]; h = candles["highs"]; l = candles["lows"]
    return (c[-3] < o[-3] and c[-2] < o[-2] and c[-1] > o[-1] and
            h[-1] > h[-2] and l[-1] < min(l[-3], l[-2]) and c[-1] > o[-2])


def is_double_engulfing_sell(candles):
    if not candles or len(candles["closes"]) < 3: return False
    c = candles["closes"]; o = candles["opens"]; h = candles["highs"]; l = candles["lows"]
    return (c[-3] > o[-3] and c[-2] > o[-2] and c[-1] < o[-1] and
            l[-1] < l[-2] and h[-1] > max(h[-3], h[-2]) and c[-1] < o[-2])


def is_outside_bar_buy(candles):
    if not candles or len(candles["closes"]) < 3: return False
    c = candles["closes"]; o = candles["opens"]; h = candles["highs"]; l = candles["lows"]
    return (h[-3] < h[-2] and h[-3] < h[-1] and h[-1] > h[-2] and
            l[-1] < l[-2] and o[-1] < c[-2] and c[-1] > o[-1])


def is_outside_bar_sell(candles):
    if not candles or len(candles["closes"]) < 3: return False
    c = candles["closes"]; o = candles["opens"]; h = candles["highs"]; l = candles["lows"]
    return (h[-3] > h[-2] and h[-3] > h[-1] and h[-1] > h[-2] and
            l[-1] < l[-2] and o[-1] > c[-2] and c[-1] < o[-1])


def check_candlestick_patterns(exchange, symbol, ohlcv_data=None):
    candles = fetch_candles_for_patterns(exchange, symbol, limit=10)
    if not candles:
        return {k: False for k in ["engulfing_buy","engulfing_sell","double_engulfing_buy",
                                    "double_engulfing_sell","outside_bar_buy","outside_bar_sell"]}
    return {
        "engulfing_buy":        is_engulfing_buy(candles),
        "engulfing_sell":       is_engulfing_sell(candles),
        "double_engulfing_buy": is_double_engulfing_buy(candles),
        "double_engulfing_sell":is_double_engulfing_sell(candles),
        "outside_bar_buy":      is_outside_bar_buy(candles),
        "outside_bar_sell":     is_outside_bar_sell(candles),
    }


# =============================================================
# BOT ENGINE
# =============================================================
def _save_error(user_id, msg, s=None, symbol="BTC/USDT"):
    if s is None: s = get_bot_state(user_id, symbol)
    if not s: return
    upsert_bot_state(user_id, int(s.get("enabled") or 1),
                     float(s.get("usdt") or 0), float(s.get("asset") or 0),
                     int(s.get("in_position") or 0),
                     s.get("entry_price"), s.get("entry_qty"), s.get("entry_time"),
                     _now(), last_error=str(msg)[:500],
                     last_sl_time=s.get("last_sl_time"),
                     daily_losses=int(s.get("daily_losses") or 0),
                     daily_loss_date=s.get("daily_loss_date"),
                     symbol=symbol)


def _get_server_time_offset():
    for url in ["https://api.binance.com/api/v3/time", "https://api.binance.com.br/api/v3/time"]:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                offset = int(r.json()["serverTime"]) - int(time.time() * 1000)
                logging.info(f"Offset Binance: {offset}ms"); return offset
        except:
            continue
    return 0


def _fetch_balance_retry(exchange, retries=3, delay=3):
    last_err = None
    for attempt in range(retries):
        try:
            return exchange.fetch_balance({"type": "spot"})
        except Exception as e:
            last_err = e
            if attempt < retries - 1: time.sleep(delay)
    raise last_err


def _make_exchange(api_key, api_secret, testnet):
    try:
        import ccxt
    except ImportError:
        raise RuntimeError("pip install ccxt")
    offset = _get_server_time_offset()
    exchange = ccxt.binance({
        "apiKey": api_key, "secret": api_secret,
        "options": {"defaultType": "spot", "recvWindow": 60000, "adjustForTimeDifference": False},
        "enableRateLimit": True,
    })
    if testnet: exchange.set_sandbox_mode(True)
    exchange.load_markets()
    import time as _t; _off = offset
    exchange.nonce = lambda: int(_t.time() * 1000) + _off
    return exchange


def bot_step(user_id, symbol="BTC/USDT", exchange=None):
    log = logging.getLogger(__name__)
    keys = get_user_keys(user_id)
    if not keys: log.warning(f"[user {user_id}] Sem chaves API."); return

    api_key, api_secret, testnet = keys
    if exchange is None:
        try:
            exchange = _make_exchange(api_key, api_secret, bool(testnet))
        except Exception as e:
            _save_error(user_id, f"Falha exchange: {e}"); return

    s = get_bot_state(user_id, symbol)
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    if not s:
        try:
            bal = _fetch_balance_retry(exchange)
            u_bal_total = float(bal.get("free", {}).get("USDT", 0) or 0)
            asset_key = SYMBOL_ASSET.get(symbol, "BTC")
            a_bal = float(bal.get("free", {}).get(asset_key, 0) or 0)
            u_bal = min(u_bal_total, USDT_PER_SYMBOL)
        except Exception as e:
            _save_error(user_id, f"Saldo inicial: {e}", symbol=symbol); return
        upsert_bot_state(user_id, 1, u_bal, a_bal, 0, None, None, None, _now(), symbol=symbol)
        log.info(f"[user {user_id}][{symbol}] Estado inicial | USDT={u_bal:.2f} | {asset_key}={a_bal:.6f}")
        return

    if not int(s.get("enabled") or 0):
        log.debug(f"[user {user_id}][{symbol}] Bot desativado."); return

    # v5.0.0: saldo mínimo desativado (MIN_DEPOSIT_TO_ACTIVATE = 0)
    if MIN_DEPOSIT_TO_ACTIVATE > 0:
        saldo_ledger = user_balance(user_id)
        if saldo_ledger < MIN_DEPOSIT_TO_ACTIVATE:
            log.warning(f"[user {user_id}][{symbol}] Saldo insuficiente: ${saldo_ledger:.2f} < ${MIN_DEPOSIT_TO_ACTIVATE:.2f}")
            return

    usdt        = float(s.get("usdt") or 0.0)
    asset       = float(s.get("asset") or 0.0)
    in_pos      = int(s.get("in_position") or 0)
    entry_price = s.get("entry_price")
    entry_qty   = s.get("entry_qty")
    entry_time  = s.get("entry_time")
    last_sl_time= s.get("last_sl_time")

    daily_losses    = int(s.get("daily_losses") or 0)
    daily_loss_date = s.get("daily_loss_date")
    if daily_loss_date != today:
        daily_losses = 0; daily_loss_date = today

    try:
        ticker = exchange.fetch_ticker(symbol)
        price = float(ticker["last"])
        if price <= 0:
            log.warning(f"[user {user_id}][{symbol}] Preço zerado — pulando"); return
    except Exception as e:
        _save_error(user_id, f"Preço: {e}", s); return

    # ══════════════════════════════════════════════════════════
    # SEM POSIÇÃO — lógica de entrada
    # ══════════════════════════════════════════════════════════
    if in_pos == 0:
        try:
            bal_check   = _fetch_balance_retry(exchange)
            asset_key_c = SYMBOL_ASSET.get(symbol, "BTC")
            asset_real  = float(bal_check.get("free", {}).get(asset_key_c, 0) or 0)
            usdt_real   = float(bal_check.get("free", {}).get("USDT", 0) or 0)
            ticker_price= float(exchange.fetch_ticker(symbol)["last"])
            min_asset_val = MIN_USDT_ORDER / (ticker_price * 1.05)
            market_info = exchange.market(symbol)
            min_qty     = float(market_info.get("limits", {}).get("amount", {}).get("min", 0) or 0)
            if asset_real > max(min_asset_val, min_qty * 2):
                log.warning(f"[user {user_id}][{symbol}] Já tem {asset_real:.8f} — marcando IN_POSITION")
                upsert_bot_state(user_id, 1, usdt_real, asset_real, 1,
                                 float(usdt / asset_real) if asset_real > 0 else None,
                                 asset_real, _now(), _now(),
                                 last_error="Posição detectada na exchange",
                                 last_sl_time=last_sl_time,
                                 daily_losses=daily_losses, daily_loss_date=daily_loss_date,
                                 symbol=symbol)
                return
            usdt = min(usdt_real, USDT_PER_SYMBOL)
        except Exception as e:
            log.warning(f"[user {user_id}][{symbol}] Verificação saldo: {e}")

        if usdt < MIN_USDT_ORDER:
            log.info(f"[user {user_id}][{symbol}] USDT insuficiente: {usdt:.2f}")
            upsert_bot_state(user_id, 1, usdt, 0.0, 0, None, None, None, _now(),
                             last_sl_time=last_sl_time, daily_losses=daily_losses,
                             daily_loss_date=daily_loss_date, symbol=symbol)
            return

        if last_sl_time:
            try:
                elapsed = (now - datetime.fromisoformat(last_sl_time)).total_seconds()
                if elapsed < COOLDOWN_AFTER_SL:
                    remaining = int(COOLDOWN_AFTER_SL - elapsed)
                    upsert_bot_state(user_id, 1, usdt, 0.0, 0, None, None, None, _now(),
                                     last_error=f"⏳ Cooldown pós-SL: {remaining}s restantes",
                                     last_sl_time=last_sl_time, daily_losses=daily_losses,
                                     daily_loss_date=daily_loss_date, symbol=symbol)
                    return
            except:
                pass

        can_buy, reason, macd_val, macd_sig = check_entry_signal(exchange, symbol, log, user_id)

        if not can_buy:
            log.info(f"[user {user_id}] ⏸ {reason}")
            upsert_bot_state(user_id, 1, usdt, 0.0, 0, None, None, None, _now(),
                             last_error=f"Aguardando: {reason}",
                             last_sl_time=last_sl_time, daily_losses=daily_losses,
                             daily_loss_date=daily_loss_date, symbol=symbol)
            return

        try:
            try:
                bal_total  = _fetch_balance_retry(exchange)
                usdt_total = float(bal_total.get("free", {}).get("USDT", 0) or 0)
                usdt_por_par = usdt_total * BANCA_FRAC_POR_PAR
            except:
                usdt_por_par = USDT_PER_SYMBOL

            buy_usdt = min(usdt * ORDER_USDT_FRAC, usdt_por_par * ORDER_USDT_FRAC, USDT_PER_SYMBOL)
            log.info(f"[user {user_id}][{symbol}] 💰 Usando {buy_usdt:.2f} USDT")

            qty_raw = buy_usdt / price
            qty_str = exchange.amount_to_precision(symbol, qty_raw)
            qty_f   = float(qty_str)
            if qty_f <= 0: _save_error(user_id, "Qty zerada", s); return

            log.info(f"[user {user_id}][{symbol}] 🟢 BUY {qty_f:.8f} @ ~{price:.2f} | MACD={macd_val:.4f}")
            order = exchange.create_market_buy_order(symbol, qty_f)
            oid   = str(order.get("id", ""))
            fp    = float(order.get("average") or order.get("price") or price)
            fq    = float(order.get("filled") or qty_f)
            fee_r = fp * fq * FEE_RATE_EST

            try:
                bal = _fetch_balance_retry(exchange)
                un  = float(bal.get("free", {}).get("USDT", 0) or 0)
                an  = float(bal.get("free", {}).get(SYMBOL_ASSET.get(symbol, "BTC"), 0) or 0)
            except:
                un = usdt - (fp * fq); an = asset + fq

            price_min_valido = {"BTC/USDT": 1000.0, "ETH/USDT": 100.0}.get(symbol, 1.0)
            if fp < price_min_valido:
                log.error(f"[user {user_id}][{symbol}] ❌ entry_price inválido ({fp}) — usando preço real ({price})")
                fp = price

            upsert_bot_state(user_id, 1, un, an, 1, fp, fq,
                             now.isoformat(sep=" ", timespec="seconds"), _now(),
                             last_error=None, last_sl_time=None,
                             daily_losses=daily_losses, daily_loss_date=daily_loss_date, symbol=symbol)
            insert_bot_trade(user_id, "BUY", fp, fq, fee_r, un, an, "BUY_SIGNAL", None,
                             oid, rsi_entry=macd_val, ema_signal=macd_sig, symbol=symbol)

            # v5.0.0: SEM taxa na compra — taxa cobrada apenas na venda
            log.info(f"[user {user_id}][{symbol}] ✅ BUY @ {fp:.2f} | USDT={un:.2f}")
        except Exception as e:
            err_msg = str(e)
            if "insufficient" in err_msg.lower() or "balance" in err_msg.lower():
                log.warning(f"[user {user_id}][{symbol}] Saldo insuficiente — aguardando")
                upsert_bot_state(user_id, 1, usdt, 0.0, 0, None, None, None, _now(),
                                 last_error="⚠️ Saldo insuficiente na exchange",
                                 last_sl_time=last_sl_time,
                                 daily_losses=daily_losses, daily_loss_date=daily_loss_date, symbol=symbol)
            else:
                _save_error(user_id, f"Compra: {e}", s, symbol=symbol)
        return

    # ══════════════════════════════════════════════════════════
    # EM POSIÇÃO — lógica de saída
    # ══════════════════════════════════════════════════════════
    if in_pos == 1 and entry_price and entry_qty:
        ep_f = float(entry_price)
        eq_f = float(entry_qty)

        price_min_valido = {"BTC/USDT": 1000.0, "ETH/USDT": 100.0}.get(symbol, 1.0)
        if ep_f < price_min_valido:
            log.error(f"[user {user_id}][{symbol}] ❌ entry_price corrompido ({ep_f}) — resetando posição!")
            upsert_bot_state(user_id, 1, usdt, 0.0, 0, None, None, None, _now(),
                             last_error=f"Estado corrompido corrigido: entry_price={ep_f}",
                             last_sl_time=last_sl_time,
                             daily_losses=daily_losses, daily_loss_date=daily_loss_date, symbol=symbol)
            return

        tp   = ep_f * (1 + TAKE_PROFIT)
        sl   = ep_f * (1 - STOP_LOSS)
        pct  = (price / ep_f - 1) * 100

        held_ok = True
        if entry_time and MIN_HOLD_SECONDS > 0:
            try:
                elapsed = (now - datetime.fromisoformat(entry_time)).total_seconds()
                held_ok = elapsed >= MIN_HOLD_SECONDS
            except:
                pass

        trailing_sl = None
        if USE_TRAILING_STOP:
            peak_price = price
            last_err = s.get("last_error") or ""
            if last_err.startswith("PEAK:"):
                try:
                    peak_price = float(last_err.split(":")[1])
                except:
                    peak_price = price
            new_peak = max(peak_price, price)
            activation_price = ep_f * (1 + TRAILING_ACTIVATION)
            if new_peak >= activation_price:
                trailing_sl = new_peak * (1 - TRAILING_DISTANCE)
                if new_peak != peak_price:
                    log.info(f"[user {user_id}][{symbol}] 📈 Trailing peak: {new_peak:.2f} | TSL: {trailing_sl:.2f}")
            upsert_bot_state(user_id, 1, usdt, asset, 1, entry_price, entry_qty,
                             entry_time, _now(),
                             last_error=f"PEAK:{new_peak:.4f}",
                             last_sl_time=last_sl_time,
                             daily_losses=daily_losses, daily_loss_date=daily_loss_date, symbol=symbol)

        exit_reason = None

        if trailing_sl and price <= trailing_sl:
            exit_reason = "TRAILING_STOP"
            log.info(f"[user {user_id}][{symbol}] 🔻 TRAILING STOP @ {price:.2f} | TSL={trailing_sl:.2f}")
        elif price >= tp:
            exit_reason = "TAKE_PROFIT"
        elif price <= sl:
            exit_reason = "STOP_LOSS"
        elif held_ok:
            smart_exit, smart_reason = check_exit_signal(
                exchange, symbol, ep_f, log, user_id, entry_time=entry_time)
            if smart_exit:
                exit_reason = smart_reason

        if exit_reason:
            try:
                try:
                    bal_now   = _fetch_balance_retry(exchange)
                    asset_now = float(bal_now.get("free", {}).get(SYMBOL_ASSET.get(symbol, "BTC"), 0) or 0)
                except:
                    asset_now = asset

                if asset_now <= 0:
                    upsert_bot_state(user_id, 1, usdt, 0.0, 0, None, None, None, _now(),
                                     last_error="Asset zerado ao tentar vender",
                                     last_sl_time=last_sl_time,
                                     daily_losses=daily_losses, daily_loss_date=daily_loss_date, symbol=symbol)
                    return

                qs_str = exchange.amount_to_precision(symbol, asset_now)
                qs_f   = float(qs_str)
                if qs_f <= 0:
                    log.warning(f"[user {user_id}][{symbol}] Qty zerada: {asset_now} → {qs_f}"); return

                log.info(f"[user {user_id}][{symbol}] 📤 SELL {qs_f:.8f} | motivo={exit_reason}")
                order  = exchange.create_market_sell_order(symbol, qs_f)
                oid    = str(order.get("id", ""))
                sp     = float(order.get("average") or order.get("price") or price)
                sq     = float(order.get("filled") or asset_now)
                gross  = sp * sq
                fee_r  = gross * FEE_RATE_EST
                pnl    = (gross - fee_r) - (ep_f * eq_f)

                try:
                    bal     = _fetch_balance_retry(exchange)
                    un_total= float(bal.get("free", {}).get("USDT", 0) or 0)
                    un      = min(un_total, USDT_PER_SYMBOL)
                    an      = 0.0
                except:
                    un = min(usdt + (sp * sq - fee_r), USDT_PER_SYMBOL); an = 0.0

                is_loss     = pnl < 0
                new_daily   = daily_losses + (1 if is_loss else 0)
                new_sl_time = _now() if exit_reason in ("STOP_LOSS", "TRAILING_STOP") else None

                upsert_bot_state(user_id, 1, un, an, 0, None, None, None, _now(),
                                 last_error=None, last_sl_time=new_sl_time,
                                 daily_losses=new_daily, daily_loss_date=daily_loss_date, symbol=symbol)
                insert_bot_trade(user_id, "SELL", sp, sq, fee_r, un, an, exit_reason, pnl, oid, symbol=symbol)

                # v5.0.0: Taxa cobrada na VENDA (não na compra)
                try:
                    add_ledger(user_id, "ADJUST", -TRADE_FEE, "bot_trades", None)
                    log.info(f"[user {user_id}][{symbol}] 💳 Taxa: -${TRADE_FEE:.2f} cobrada no fechamento")
                except Exception as e:
                    log.warning(f"[user {user_id}][{symbol}] Erro ao cobrar taxa: {e}")

                emoji = "🟢" if pnl > 0 else "🔴"
                log.info(f"[user {user_id}][{symbol}] {emoji} SELL ({exit_reason}) @ {sp:.2f} | pnl={pnl:.4f}")

            except Exception as e:
                _save_error(user_id, f"Venda: {e}", s)
        else:
            upsert_bot_state(user_id, 1, usdt, asset, 1, entry_price, entry_qty,
                             entry_time, _now(), last_error=s.get("last_error"),
                             last_sl_time=last_sl_time,
                             daily_losses=daily_losses, daily_loss_date=daily_loss_date, symbol=symbol)


def run_bot_loop():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.handlers.RotatingFileHandler(
                "bot.log", maxBytes=5*1024*1024, backupCount=2, encoding="utf-8"
            ),
            logging.StreamHandler()
        ]
    )
    init_db()
    log = logging.getLogger(__name__)
    log.info("=" * 60)
    log.info("  OBS PRO BOT v5.0.1 — TODAS AS CORREÇÕES")
    log.info(f"  Pares: {', '.join(BOT_SYMBOLS)}")
    log.info(f"  TP: {TAKE_PROFIT * 100:.2f}% | SL: {STOP_LOSS * 100:.2f}% | R:R 2:1")
    log.info(f"  ENTRADA: MACD linha > 0 + RSI {RSI_ENTRY_MIN}-{RSI_ENTRY_MAX} + EMA{EMA_TREND} H1 + EMA50 4H")
    log.info(f"  SAÍDA: TP | SL | Trailing Stop")
    log.info(f"  ✅ FIX: Exchange cache — sem MemoryError")
    log.info(f"  ✅ FIX: Taxa na VENDA — não na compra")
    log.info(f"  ✅ FIX: Saldo mínimo desativado")
    log.info(f"  ✅ FIX: Log rotativo 5MB")
    log.info("=" * 60)

    # ══════════════════════════════════════════════════════════
    # CACHE DE EXCHANGE — criado uma vez por hora
    # Resolve o MemoryError de load_markets() a cada 15s
    # ══════════════════════════════════════════════════════════
    _exchange_cache = {}
    _exchange_last_build = {}

    def get_or_build_exchange(uid, api_key, api_secret, testnet):
        cache_key = (uid, api_key)
        agora = time.time()
        ultimo_build = _exchange_last_build.get(cache_key, 0)
        precisa_rebuild = (
            cache_key not in _exchange_cache or
            (agora - ultimo_build) > EXCHANGE_REBUILD_INTERVAL
        )
        if precisa_rebuild:
            log.info(f"[user {uid}] 🔄 Construindo exchange...")
            try:
                exch = _make_exchange(api_key, api_secret, bool(testnet))
                _exchange_cache[cache_key] = exch
                _exchange_last_build[cache_key] = agora
                log.info(f"[user {uid}] ✅ Exchange cacheado")
            except MemoryError:
                log.error(f"[user {uid}] ❌ MemoryError ao construir exchange — aguardando")
                return None
            except Exception as e:
                log.error(f"[user {uid}] ❌ Erro exchange: {e}")
                if cache_key in _exchange_cache:
                    log.warning(f"[user {uid}] ⚠️ Usando exchange antigo do cache")
                    return _exchange_cache[cache_key]
                return None
        return _exchange_cache[cache_key]

    erros_consecutivos = 0
    while True:
        try:
            ativos = get_all_active_bot_users()
            for uid in ativos:
                try:
                    keys = get_user_keys(uid)
                    if not keys: continue
                    api_key, api_secret, testnet = keys

                    exch = get_or_build_exchange(uid, api_key, api_secret, testnet)
                    if exch is None:
                        log.warning(f"[user {uid}] ⏭ Exchange indisponível — próximo ciclo")
                        continue

                    states = {sym: get_bot_state(uid, sym) for sym in ALL_SYMBOLS}
                    pares_em_posicao = [s for s, st in states.items()
                                        if st and int(st.get("in_position") or 0) == 1]
                    n_posicoes = len(pares_em_posicao)

                    for sym in ALL_SYMBOLS:
                        try:
                            st     = states.get(sym, {})
                            in_pos = int(st.get("in_position") or 0) if st else 0
                            if in_pos == 1:
                                bot_step(uid, symbol=sym, exchange=exch)
                            elif n_posicoes < MAX_PARES_SIMULTANEOS:
                                bot_step(uid, symbol=sym, exchange=exch)
                            else:
                                log.debug(f"[user {uid}][{sym}] Aguardando vaga ({n_posicoes}/{MAX_PARES_SIMULTANEOS})")
                        except Exception as e:
                            log.error(f"[user {uid}][{sym}] Erro no par: {e}", exc_info=True)
                            # Invalida cache se erro de mercado
                            if "market" in str(e).lower() or "symbol" in str(e).lower():
                                cache_key = (uid, api_key)
                                if cache_key in _exchange_cache:
                                    del _exchange_cache[cache_key]
                                    log.warning(f"[user {uid}] 🗑 Cache invalidado — rebuild no próximo ciclo")

                    erros_consecutivos = 0
                except MemoryError:
                    log.error(f"[user {uid}] MemoryError — pulando ciclo")
                    erros_consecutivos += 1
                except Exception as e:
                    erros_consecutivos += 1
                    log.error(f"[user {uid}] Erro: {e}", exc_info=True)
                    if erros_consecutivos >= 10:
                        log.critical("10 erros consecutivos. Aguardando 60s...")
                        time.sleep(60); erros_consecutivos = 0
        except Exception as e:
            log.critical(f"Erro fatal: {e}", exc_info=True)
        time.sleep(BOT_LOOP_INTERVAL)


if BOT_MODE:
    run_bot_loop()
    sys.exit(0)

# =============================================================
# INTERFACE STREAMLIT
# =============================================================
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except:
    HAS_AUTOREFRESH = False

init_db()
st.set_page_config(page_title="OBS PRO — BOT v5.0.1", layout="wide")


def fetch_price_display(symbol):
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price",
                         params={"symbol": symbol.replace("/", "").upper()}, timeout=6)
        if r.status_code == 200: return float(r.json()["price"])
    except:
        pass
    return None


def do_login(user):
    token = create_session(user[0])
    st.session_state.user = user
    st.session_state.token = token
    try: st.query_params["sid"] = token
    except: pass


def do_logout():
    token = st.session_state.get("token", "")
    if token: delete_session(token)
    st.session_state.user = None
    st.session_state.token = ""
    try: st.query_params.clear()
    except: pass
    st.rerun()


if "user" not in st.session_state: st.session_state.user = None
if "token" not in st.session_state: st.session_state.token = ""

if st.session_state.user is None:
    try:
        sid = st.query_params.get("sid", "")
        if sid:
            recovered = get_session_user(sid)
            if recovered:
                st.session_state.user = recovered
                st.session_state.token = sid
            else:
                try: st.query_params.clear()
                except: pass
    except:
        pass

with st.sidebar:
    st.header("🔐 Login")
    if st.session_state.user:
        st.success(f"Logado: {st.session_state.user[1]} ({st.session_state.user[3]})")
        if st.button("Sair"): do_logout()
    else:
        lu = st.text_input("Usuário", key="li_u")
        lp = st.text_input("Senha", type="password", key="li_p")
        if st.button("Entrar"):
            user = auth(lu, lp)
            if user: do_login(user); st.rerun()
            else: st.error("Usuário ou senha inválidos.")
    st.divider()
    st.header("🧾 Cadastro")
    nu  = st.text_input("Novo usuário", key="reg_u")
    np_ = st.text_input("Nova senha", type="password", key="reg_p")
    rc  = st.text_input("Código indicação (opcional)", key="reg_c")
    if st.button("Criar conta"):
        try:
            create_user(nu, np_, "user", rc or None); st.success("Conta criada! Faça login.")
        except Exception as e:
            st.error(str(e))
    st.divider()
    st.caption("🔁 Auto atualização")
    auto_ref = st.checkbox("Ativar", value=True)
    ref_sec  = st.slider("Intervalo (s)", 5, 60, 15)
    if auto_ref and HAS_AUTOREFRESH:
        st_autorefresh(interval=ref_sec * 1000, key="ar")
    elif auto_ref:
        st.caption("⚠️ pip install streamlit-autorefresh")

st.title("OBS PRO — BOT v5.0.0  🤖")
st.caption(
    f"Pares: {', '.join(BOT_SYMBOLS)} | "
    f"MACD > 0 + RSI {RSI_ENTRY_MIN}-{RSI_ENTRY_MAX} | "
    f"TP {TAKE_PROFIT*100:.2f}% | SL {STOP_LOSS*100:.2f}% | "
    f"Taxa/op: ${TRADE_FEE:.2f} (na venda)"
)

if not st.session_state.user:
    st.info("Faça login na barra lateral.")
    st.stop()

user = st.session_state.user
user_id, username, _, role, created_at, referrer_code, my_code = user

tab_names = ["📊 Painel BOT", "👤 Minha Conta", "🔑 Chaves API", "💰 Aporte", "💸 Saque", "📄 Extrato"]
if role == "admin": tab_names.append("⚙️ Administração")
tabs = st.tabs(tab_names)

with tabs[0]:
    has_keys = get_user_keys(user_id) is not None

    if not has_keys:
        st.warning("⚠️ Cadastre suas chaves API na aba **🔑 Chaves API** antes de operar.")

    s_first = get_bot_state(user_id, BOT_SYMBOLS[0])
    bot_on  = bool(int(s_first.get("enabled") or 0)) if s_first else False
    new_on  = st.toggle(
        f"🟢 Operar na Binance (REAL) — máx {MAX_PARES_SIMULTANEOS} pares | "
        f"TP {TAKE_PROFIT*100:.2f}% | SL {STOP_LOSS*100:.2f}%",
        value=bot_on, disabled=not has_keys)

    if new_on != bot_on:
        for sym in BOT_SYMBOLS:
            s_sym = get_bot_state(user_id, sym)
            if s_sym:
                upsert_bot_state(user_id, int(new_on),
                                 float(s_sym.get("usdt") or 0), float(s_sym.get("asset") or 0),
                                 int(s_sym.get("in_position") or 0),
                                 s_sym.get("entry_price"), s_sym.get("entry_qty"), s_sym.get("entry_time"),
                                 s_sym.get("last_step_ts"), s_sym.get("last_error"), s_sym.get("last_sl_time"),
                                 int(s_sym.get("daily_losses") or 0), s_sym.get("daily_loss_date"), symbol=sym)
            else:
                upsert_bot_state(user_id, int(new_on), 0.0, 0.0, 0, None, None, None, None, symbol=sym)
        st.rerun()

    if not s_first:
        st.info("Ative o bot e rode: `python dashboard.py --bot`")
    else:
        st.divider()
        for sym in BOT_SYMBOLS:
            s = get_bot_state(user_id, sym)
            if not s: continue

            asset_ticker = sym.split("/")[0]
            price_now    = fetch_price_display(sym)
            bot_usdt     = float(s.get("usdt") or 0.0)
            bot_asset    = float(s.get("asset") or 0.0)
            in_pos       = int(s.get("in_position") or 0)
            entry_price  = s.get("entry_price")
            entry_time   = s.get("entry_time")
            err          = s.get("last_error") or ""
            lts          = s.get("last_step_ts")

            with st.expander(f"{'🟡' if in_pos else '⚪'} {sym} — {'COMPRADO' if in_pos else 'FLAT'}", expanded=True):
                if err:
                    if "Aguardando" in err or "Cooldown" in err or "⏳" in err:
                        st.info(f"📊 {err}")
                    else:
                        st.error(f"🚨 {err}")
                if lts: st.caption(f"⏱ Último ciclo: `{lts}`")

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("USDT", f"{bot_usdt:.2f}")
                c2.metric(f"{asset_ticker}", f"{bot_asset:.6f}")
                c3.metric("Status", "🟡 COMPRADO" if in_pos else "⚪ FLAT")
                c4.metric("Preço", f"{price_now:.2f}" if price_now else "—")

                if in_pos and entry_price:
                    ep   = float(entry_price)
                    tp_p = ep * (1 + TAKE_PROFIT)
                    sl_p = ep * (1 - STOP_LOSS)
                    a, b, c_, d = st.columns(4)
                    a.metric("Entrada", f"{ep:.2f}")
                    b.metric("Take Profit", f"{tp_p:.2f}")
                    c_.metric("Stop Loss", f"{sl_p:.2f}")
                    if price_now:
                        pct = (price_now / ep - 1) * 100
                        d.metric("P&L atual", f"{pct:+.3f}%")
                    if entry_time:
                        try:
                            secs     = int((datetime.now() - datetime.fromisoformat(entry_time)).total_seconds())
                            hold_rest= max(0, MIN_HOLD_SECONDS - secs)
                            st.caption(f"⏱ Em posição há {secs}s | Hold restante: {hold_rest}s")
                        except:
                            pass

        st.divider()
        st.subheader("📈 Performance Global")
        df_tr = load_bot_trades(user_id, 500)
        m  = compute_metrics(df_tr)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total vendas", f"{m['sells']}")
        m2.metric("Winrate", f"{m['winrate']:.1f}%")
        m3.metric("PnL realizado", f"{m['pnl']:.4f} USDT")
        m4.metric("Ganhos/Perdas", f"{m['wins']}W / {m['losses']}L")

        st.subheader("📋 Histórico de trades")
        if df_tr.empty:
            st.info("Sem operações. Rode: `python dashboard.py --bot`")
        else:
            par_filtro = st.selectbox("Filtrar por par", ["Todos"] + BOT_SYMBOLS)
            df_show    = df_tr if par_filtro == "Todos" else df_tr[df_tr["symbol"] == par_filtro]
            st.dataframe(df_show.tail(200), use_container_width=True)

with tabs[1]:
    bal = user_balance(user_id)
    c1, c2, c3 = st.columns(3)
    c1.metric("Usuário", username)
    c2.metric("Saldo ledger", f"{bal:.2f} USDT")
    c3.metric("Meu código", my_code)
    if referrer_code: st.caption(f"Indicado por: `{referrer_code}`")

with tabs[2]:
    st.subheader("🔑 Chaves API — Binance")
    st.warning("⚠️ Use chaves com permissão apenas de **Spot Trading**. NUNCA habilite saque.")
    ex = get_user_keys(user_id)
    if ex: st.success(f"✅ Chaves cadastradas | Key: `{ex[0][:8]}...`")
    with st.form("form_keys"):
        nk = st.text_input("API Key", type="password")
        ns = st.text_input("API Secret", type="password")
        tn = st.checkbox("Usar Testnet", value=False)
        if st.form_submit_button("💾 Salvar chaves"):
            try:
                save_user_keys(user_id, nk, ns, tn); st.success("✅ Chaves salvas!"); st.rerun()
            except Exception as e:
                st.error(str(e))

with tabs[3]:
    st.subheader("💰 Aporte em USDT")
    st.markdown(f"**Rede:** `{DEPOSIT_NETWORK_LABEL}`")
    st.code(DEPOSIT_ADDRESS_FIXED)
    amt_d  = st.number_input("Valor (USDT)", min_value=0.0, step=10.0, format="%.2f", key="amt_d")
    txid_d = st.text_input("TXID / Hash da transação")
    if st.button("📤 Enviar comprovante"):
        try:
            if amt_d <= 0: st.error("Informe um valor.")
            else: create_deposit(user_id, amt_d, txid_d); st.success("Enviado! Aguarde aprovação.")
        except Exception as e:
            st.error(str(e))
    st.divider()
    rows = list_deposits(user_id=user_id)
    if rows:
        st.dataframe(pd.DataFrame(rows, columns=["id","valor","txid","status","criado","revisado","nota"]),
                     use_container_width=True)
    else:
        st.info("Sem aportes ainda.")

with tabs[4]:
    st.subheader("💸 Solicitar saque")
    bal   = user_balance(user_id)
    st.metric("Saldo disponível", f"{bal:.2f} USDT")
    amt_w = st.number_input("Valor (USDT)", min_value=0.0, step=10.0, format="%.2f", key="amt_w")
    net_w = st.selectbox("Rede", ["TRC20","BEP20","ERC20"])
    adr_w = st.text_input("Endereço destino")
    fee_w = amt_w * WITHDRAW_FEE_RATE
    c1, c2, c3 = st.columns(3)
    c1.metric("Taxa", f"{WITHDRAW_FEE_RATE * 100:.0f}%")
    c2.metric("Taxa (USDT)", f"{fee_w:.2f}")
    c3.metric("Você recebe", f"{amt_w - fee_w:.2f}")
    if st.button("📤 Solicitar saque"):
        try:
            if amt_w <= 0: st.error("Informe um valor.")
            else: create_withdrawal(user_id, amt_w, net_w, adr_w); st.success("Solicitado!")
        except Exception as e:
            st.error(str(e))
    st.divider()
    rows = list_withdrawals(user_id=user_id)
    if rows:
        st.dataframe(pd.DataFrame(rows,
                     columns=["id","valor","taxa","liquido","rede","endereco","txid_pago","status","criado","revisado","nota"]),
                     use_container_width=True)
    else:
        st.info("Sem saques ainda.")

with tabs[5]:
    st.subheader("📄 Extrato")
    with _DB_LOCK:
        conn = db()
        df_led = pd.read_sql_query(
            "SELECT created_at,kind,amount_usdt,ref_table,ref_id FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 500",
            conn, params=(user_id,))
        conn.close()
    if df_led.empty:
        st.info("Sem movimentações.")
    else:
        st.dataframe(df_led, use_container_width=True)
        st.download_button("⬇️ Baixar CSV", df_led.to_csv(index=False).encode(), "extrato.csv", "text/csv")

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
        dep_df  = pd.DataFrame(dep_all, columns=["id","username","valor","txid","status","criado","revisado","nota"])
        pend_d  = dep_df[dep_df["status"] == "PENDING"]
        if pend_d.empty:
            st.info("Nenhum aporte pendente.")
        else:
            st.dataframe(pend_d, use_container_width=True)
            did = st.number_input("ID do depósito", min_value=1, step=1, key="did")
            dn  = st.text_input("Nota", key="dn")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ Aprovar", key="apd"):
                    try: admin_review_deposit(int(did), True, user_id, dn); st.success("Aprovado!"); st.rerun()
                    except Exception as e: st.error(str(e))
            with c2:
                if st.button("❌ Rejeitar", key="rjd"):
                    try: admin_review_deposit(int(did), False, user_id, dn); st.warning("Rejeitado."); st.rerun()
                    except Exception as e: st.error(str(e))

        st.divider()
        st.markdown("### 💸 Saques pendentes")
        w_all = list_withdrawals()
        w_df  = pd.DataFrame(w_all,
                  columns=["id","username","valor_req","taxa","liquido","rede","endereco",
                            "txid_pago","status","criado","revisado","nota"])
        pend_w = w_df[w_df["status"] == "PENDING"]
        if pend_w.empty:
            st.info("Nenhum saque pendente.")
        else:
            st.dataframe(pend_w, use_container_width=True)
            wid = st.number_input("ID do saque", min_value=1, step=1, key="wid")
            wn  = st.text_input("Nota", key="wn")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ Aprovar", key="apw"):
                    try: admin_review_withdrawal(int(wid), True, user_id, wn); st.success("Aprovado!"); st.rerun()
                    except Exception as e: st.error(str(e))
            with c2:
                if st.button("❌ Rejeitar", key="rjw"):
                    try: admin_review_withdrawal(int(wid), False, user_id, wn); st.warning("Rejeitado."); st.rerun()
                    except Exception as e: st.error(str(e))

        st.divider()
        st.markdown("### ✅ Marcar saque como PAGO")
        aprov_w = w_df[w_df["status"] == "APPROVED"]
        if aprov_w.empty:
            st.info("Nenhum saque aprovado aguardando pagamento.")
        else:
            st.dataframe(aprov_w, use_container_width=True)
            wid2  = st.number_input("ID saque aprovado", min_value=1, step=1, key="wid2")
            ptxid = st.text_input("TXID do pagamento (obrigatório)", key="ptxid")
            pn    = st.text_input("Nota", key="pn")
            if st.button("💳 Marcar como PAGO"):
                try: admin_mark_withdraw_paid(int(wid2), user_id, ptxid, pn); st.success("Marcado!"); st.rerun()
                except Exception as e: st.error(str(e))

        st.divider()
        st.markdown("### 🤖 Status dos bots")
        with _DB_LOCK:
            conn = db()
            df_bots = pd.read_sql_query("""
                SELECT u.id as user_id, u.username, bs.symbol, bs.enabled, bs.usdt, bs.asset, bs.in_position,
                       bs.entry_price, bs.last_step_ts, bs.last_error, bs.daily_losses,
                       CASE WHEN uk.user_id IS NOT NULL THEN 'Sim' ELSE 'Não' END as tem_chave
                FROM bot_state bs
                JOIN users u ON u.id=bs.user_id
                LEFT JOIN user_keys uk ON uk.user_id=bs.user_id
                ORDER BY u.username, bs.symbol
            """, conn)
            conn.close()
        if not df_bots.empty:
            st.dataframe(df_bots, use_container_width=True)
        else:
            st.info("Nenhum bot registrado ainda.")

        st.divider()
        st.markdown("### ⚡ Controle de Bot por Usuário")
        all_users = list_users()
        for u in all_users:
            uid, uname, urole, ucreated, ucode = u
            if urole == "admin": continue
            saldo = user_balance(uid)
            has_keys_u = get_user_keys(uid) is not None
            s_bot = get_bot_state(uid, ALL_SYMBOLS[0])
            bot_ativo = bool(int(s_bot.get("enabled") or 0)) if s_bot else False

            col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 2])
            col1.write(f"**{uname}**")
            col2.write(f"${saldo:.2f}")
            col3.write("✅ API" if has_keys_u else "❌ Sem API")
            col4.write("🟢 ON" if bot_ativo else "⚫ OFF")

            with col5:
                if bot_ativo:
                    if st.button(f"⏹ Desativar", key=f"des_{uid}"):
                        desativar_bot_usuario(uid)
                        st.success(f"Bot de {uname} desativado!")
                        st.rerun()
                else:
                    if has_keys_u:
                        if st.button(f"▶️ Ativar", key=f"ati_{uid}"):
                            ativar_bot_usuario(uid)
                            st.success(f"Bot de {uname} ativado!")
                            st.rerun()
                    else:
                        st.caption("⚠️ sem API")
