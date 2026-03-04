#!/usr/bin/env python3
# =============================================================
# OBS PRO BOT — VERSÃO 3.0 ESTRATÉGIA COMPLETA
#
# NOVIDADES v3.0:
#   ENTRADA:
#     + Filtro EMA200 no H1 — só compra se preço > EMA200 (1h)
#     + RSI 14 entre 40-65
#     + EMA9 > EMA21 no 5m
#
#   SAÍDA INTELIGENTE (4 motivos):
#     1. Take Profit +1.0%
#     2. Stop Loss -0.5%
#     3. RSI > 70 (sobrecomprado — sai antes de reverter)
#     4. EMA9 cruzar abaixo EMA21 (tendência virou)
#
# INSTALAÇÃO:
#   pip install streamlit pandas requests ccxt streamlit-autorefresh
#
# COMO RODAR (2 terminais):
#   Terminal 1 → streamlit run dashboard.py --server.port 8501
#   Terminal 2 → python dashboard.py --bot
# =============================================================

import sys

_raw_argv = sys.argv[1:]
BOT_MODE = "--bot" in _raw_argv and not any("streamlit" in a for a in _raw_argv)

import sqlite3
import hashlib
import time
import logging
import threading
import requests
from datetime import datetime, timedelta
import pandas as pd

_DB_LOCK = threading.Lock()

# =============================================================
# ★ CONFIG — EDITE AQUI ★
# =============================================================
DB_PATH               = "mvp_funds.db"
DEFAULT_ADMIN_USER    = "admin"
DEFAULT_ADMIN_PASS    = "LU87347748"
DEPOSIT_ADDRESS_FIXED = "TMYvfwaT8XX998h6dP9JVWxgdPxY88cLmt"
DEPOSIT_NETWORK_LABEL = "TRC20"
WITHDRAW_FEE_RATE     = 0.05

BOT_SYMBOL            = "BTC/USDT"
TAKE_PROFIT           = 0.010   # +1.0%
STOP_LOSS             = 0.005   # -0.5%
FEE_RATE_EST          = 0.001
ORDER_USDT_FRAC       = 0.95
MIN_USDT_ORDER        = 10.0
BOT_LOOP_INTERVAL     = 15
MIN_HOLD_SECONDS      = 300

# ── Parâmetros de entrada ─────────────────────────────────────
RSI_PERIOD            = 14
EMA_FAST              = 9
EMA_SLOW              = 21
EMA_TREND             = 200     # EMA200 no H1
RSI_MIN               = 40
RSI_MAX               = 65
CANDLE_INTERVAL       = "5m"
CANDLE_INTERVAL_H1    = "1h"
CANDLE_LIMIT          = 50
CANDLE_LIMIT_H1       = 210     # precisa de 200+ candles para EMA200
COOLDOWN_AFTER_SL     = 300     # 5 minutos (era 60s)

# ── Parâmetros de saída inteligente ──────────────────────────
RSI_EXIT              = 70      # vende se RSI sobrecomprado
USE_RSI_EXIT          = True    # ativa saída por RSI
USE_EMA_EXIT          = True    # ativa saída por cruzamento EMA

SESSION_SECRET        = "obspro-mude-essa-chave-2024"


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
            user_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
            usdt REAL NOT NULL DEFAULT 0, asset REAL NOT NULL DEFAULT 0,
            in_position INTEGER NOT NULL DEFAULT 0, entry_price REAL, entry_qty REAL,
            entry_time TEXT, last_step_ts TEXT, last_error TEXT, last_sl_time TEXT,
            daily_losses INTEGER NOT NULL DEFAULT 0, daily_loss_date TEXT,
            updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id))""")

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
        ]:
            try: conn.execute(m); conn.commit()
            except: pass

        cur.execute("SELECT id FROM users WHERE username=?", (DEFAULT_ADMIN_USER,))
        if not cur.fetchone():
            cur.execute("INSERT INTO users (username,pass_hash,role,created_at,my_code) VALUES (?,?,?,?,?)",
                (DEFAULT_ADMIN_USER, sha256(DEFAULT_ADMIN_PASS), "admin", _now(), make_code(DEFAULT_ADMIN_USER)))
            conn.commit()
        conn.close()


# ── Usuários ──────────────────────────────────────────────────
def get_user_by_username(username):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT id,username,pass_hash,role,created_at,referrer_code,my_code FROM users WHERE username=?", (username,))
        row = cur.fetchone(); conn.close(); return row

def get_user_by_id(user_id):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT id,username,pass_hash,role,created_at,referrer_code,my_code FROM users WHERE id=?", (user_id,))
        row = cur.fetchone(); conn.close(); return row

def auth(username, password):
    u = get_user_by_username(username.strip())
    return u if u and sha256(password) == u[2] else None

def create_user(username, password, role, referrer_code=None):
    username = username.strip()
    if not username or not password: raise ValueError("Preencha usuário e senha.")
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        if referrer_code:
            cur.execute("SELECT id FROM users WHERE my_code=?", (referrer_code.strip(),))
            if not cur.fetchone(): conn.close(); raise ValueError("Código de indicação inválido.")
        try:
            cur.execute("INSERT INTO users (username,pass_hash,role,created_at,referrer_code,my_code) VALUES (?,?,?,?,?,?)",
                (username, sha256(password), role, _now(),
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


# ── Sessões ───────────────────────────────────────────────────
def create_session(user_id):
    token   = sha256(f"{user_id}|{time.time()}|{SESSION_SECRET}")
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
    except: return None
    return get_user_by_id(user_id)

def delete_session(token):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit(); conn.close()


# ── Chaves API ────────────────────────────────────────────────
def save_user_keys(user_id, api_key, api_secret, testnet=False):
    if not api_key.strip() or not api_secret.strip(): raise ValueError("API Key e Secret são obrigatórios.")
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT user_id FROM user_keys WHERE user_id=?", (user_id,))
        if cur.fetchone():
            cur.execute("UPDATE user_keys SET api_key=?,api_secret=?,testnet=?,updated_at=? WHERE user_id=?",
                        (api_key.strip(), api_secret.strip(), int(testnet), _now(), user_id))
        else:
            cur.execute("INSERT INTO user_keys (user_id,exchange,api_key,api_secret,testnet,updated_at) VALUES (?,?,?,?,?,?)",
                        (user_id, "binance", api_key.strip(), api_secret.strip(), int(testnet), _now()))
        conn.commit(); conn.close()

def get_user_keys(user_id):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT api_key,api_secret,testnet FROM user_keys WHERE user_id=?", (user_id,))
        row = cur.fetchone(); conn.close(); return row


# ── Ledger ────────────────────────────────────────────────────
def add_ledger(user_id, kind, amount_usdt, ref_table=None, ref_id=None):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("INSERT INTO ledger (user_id,kind,amount_usdt,ref_table,ref_id,created_at) VALUES (?,?,?,?,?,?)",
                    (user_id, kind, float(amount_usdt), ref_table, ref_id, _now()))
        conn.commit(); conn.close()

def user_balance(user_id):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(amount_usdt),0) FROM ledger WHERE user_id=?", (user_id,))
        bal = float(cur.fetchone()[0] or 0); conn.close(); return bal


# ── Depósitos ─────────────────────────────────────────────────
def create_deposit(user_id, amount_usdt, txid):
    if not txid or not txid.strip(): raise ValueError("TXID é obrigatório.")
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("INSERT INTO deposits (user_id,amount_usdt,txid,deposit_address,status,created_at) VALUES (?,?,?,?,?,?)",
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

def admin_review_deposit(deposit_id, approve, admin_id, note=""):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT user_id,amount_usdt,status FROM deposits WHERE id=?", (deposit_id,))
        row = cur.fetchone()
        if not row: conn.close(); raise ValueError("Depósito não encontrado.")
        user_id, amt, status = row
        if status != "PENDING": conn.close(); raise ValueError("Já revisado.")
        new_status = "APPROVED" if approve else "REJECTED"
        cur.execute("UPDATE deposits SET status=?,reviewed_at=?,reviewed_by=?,note=? WHERE id=?",
                    (new_status, _now(), admin_id, note, deposit_id))
        conn.commit(); conn.close()
    if approve: add_ledger(user_id, "DEPOSIT", float(amt), "deposits", deposit_id)


# ── Saques ────────────────────────────────────────────────────
def create_withdrawal(user_id, amount_usdt, network, address):
    bal = user_balance(user_id)
    if amount_usdt <= 0: raise ValueError("Valor inválido.")
    if amount_usdt > bal: raise ValueError(f"Saldo insuficiente: {bal:.2f} USDT")
    if not network.strip() or not address.strip(): raise ValueError("Rede e endereço obrigatórios.")
    fee = amount_usdt * WITHDRAW_FEE_RATE
    net = amount_usdt - fee
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("""INSERT INTO withdrawals
            (user_id,amount_request_usdt,fee_rate,fee_usdt,amount_net_usdt,network,address,status,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, float(amount_usdt), float(WITHDRAW_FEE_RATE), float(fee),
             float(net), network.strip(), address.strip(), "PENDING", _now()))
        conn.commit(); conn.close()

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
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT user_id,amount_request_usdt,status FROM withdrawals WHERE id=?", (wid,))
        row = cur.fetchone()
        if not row: conn.close(); raise ValueError("Saque não encontrado.")
        user_id, amt, status = row
        if status != "PENDING": conn.close(); raise ValueError("Já revisado.")
        new_status = "APPROVED" if approve else "REJECTED"
        cur.execute("UPDATE withdrawals SET status=?,reviewed_at=?,reviewed_by=?,note=? WHERE id=?",
                    (new_status, _now(), admin_id, note, wid))
        conn.commit(); conn.close()
    if approve: add_ledger(user_id, "WITHDRAWAL", -float(amt), "withdrawals", wid)

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


# ── Bot State ─────────────────────────────────────────────────
def get_bot_state(user_id):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("""SELECT user_id,enabled,usdt,asset,in_position,entry_price,entry_qty,
                              entry_time,last_step_ts,last_error,last_sl_time,
                              daily_losses,daily_loss_date,updated_at
                       FROM bot_state WHERE user_id=?""", (user_id,))
        row = cur.fetchone(); conn.close()
    if not row: return {}
    keys = ["user_id","enabled","usdt","asset","in_position","entry_price","entry_qty",
            "entry_time","last_step_ts","last_error","last_sl_time",
            "daily_losses","daily_loss_date","updated_at"]
    return dict(zip(keys, row))

def upsert_bot_state(user_id, enabled, usdt, asset, in_position,
                     entry_price, entry_qty, entry_time, last_step_ts,
                     last_error=None, last_sl_time=None,
                     daily_losses=0, daily_loss_date=None):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT user_id FROM bot_state WHERE user_id=?", (user_id,))
        if cur.fetchone():
            cur.execute("""UPDATE bot_state SET enabled=?,usdt=?,asset=?,in_position=?,
                           entry_price=?,entry_qty=?,entry_time=?,last_step_ts=?,
                           last_error=?,last_sl_time=?,daily_losses=?,daily_loss_date=?,
                           updated_at=? WHERE user_id=?""",
                        (enabled, float(usdt), float(asset), int(in_position),
                         entry_price, entry_qty, entry_time, last_step_ts,
                         last_error, last_sl_time, daily_losses, daily_loss_date,
                         _now(), user_id))
        else:
            cur.execute("""INSERT INTO bot_state
                           (user_id,enabled,usdt,asset,in_position,entry_price,entry_qty,
                            entry_time,last_step_ts,last_error,last_sl_time,
                            daily_losses,daily_loss_date,updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (user_id, enabled, float(usdt), float(asset), int(in_position),
                         entry_price, entry_qty, entry_time, last_step_ts,
                         last_error, last_sl_time, daily_losses, daily_loss_date, _now()))
        conn.commit(); conn.close()

def insert_bot_trade(user_id, side, price, qty, fee_usdt,
                     usdt_balance, asset_balance, reason, pnl_usdt,
                     order_id=None, rsi_entry=None, ema_signal=None):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("""INSERT INTO bot_trades
            (user_id,time,symbol,side,price,qty,fee_usdt,usdt_balance,asset_balance,
             reason,pnl_usdt,order_id,rsi_entry,ema_signal)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, _now(), BOT_SYMBOL, side, float(price), float(qty), float(fee_usdt),
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
    wins   = int((sells["pnl_usdt"] > 0).sum())
    losses = int((sells["pnl_usdt"] < 0).sum())
    total  = wins + losses
    return {"sells": total, "wins": wins, "losses": losses,
            "winrate": wins / total * 100 if total else 0.0,
            "pnl": float(sells["pnl_usdt"].sum()) if not sells.empty else 0.0}

def get_all_active_bot_users():
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("""SELECT bs.user_id FROM bot_state bs
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
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains  = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0: return 100.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 2)


def fetch_indicators_5m(exchange, symbol):
    """Indicadores no 5m: RSI14, EMA9, EMA21."""
    try:
        ohlcv  = exchange.fetch_ohlcv(symbol, CANDLE_INTERVAL, limit=CANDLE_LIMIT)
        closes = [float(c[4]) for c in ohlcv]
        rsi      = calc_rsi(closes, RSI_PERIOD)
        ema_fast = calc_ema(closes, EMA_FAST)
        ema_slow = calc_ema(closes, EMA_SLOW)
        if rsi is None or ema_fast is None or ema_slow is None:
            return {"ok": False, "reason": "Dados insuficientes (5m)"}
        return {"ok": True, "rsi": rsi, "ema_fast": ema_fast, "ema_slow": ema_slow, "closes": closes}
    except Exception as e:
        return {"ok": False, "reason": f"Erro candles 5m: {e}"}


def fetch_ema200_h1(exchange, symbol):
    """EMA200 no H1 — filtro de tendência macro."""
    try:
        ohlcv  = exchange.fetch_ohlcv(symbol, CANDLE_INTERVAL_H1, limit=CANDLE_LIMIT_H1)
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
    """
    Verifica se todas as condições de entrada estão OK.
    Retorna (can_buy, reason, rsi, ema_sig)
    """
    # 1. EMA200 H1 — tendência macro
    h1 = fetch_ema200_h1(exchange, symbol)
    if not h1.get("ok"):
        return False, f"EMA200 H1 indisponível: {h1.get('reason')}", None, None
    if not h1["above"]:
        return False, f"Preço({h1['price']:.0f}) < EMA200_H1({h1['ema200']:.0f}) — mercado em tendência de BAIXA", None, None

    # 2. Indicadores 5m
    ind = fetch_indicators_5m(exchange, symbol)
    if not ind.get("ok"):
        return False, f"Indicadores 5m: {ind.get('reason')}", None, None

    rsi      = ind["rsi"]
    ema_fast = ind["ema_fast"]
    ema_slow = ind["ema_slow"]

    reasons = []
    if not (ema_fast > ema_slow):
        reasons.append(f"EMA{EMA_FAST}({ema_fast:.0f}) < EMA{EMA_SLOW}({ema_slow:.0f})")
    if not (RSI_MIN <= rsi <= RSI_MAX):
        reasons.append(f"RSI({rsi:.1f}) fora da zona {RSI_MIN}-{RSI_MAX}")

    ema_sig = f"EMA{EMA_FAST}>{EMA_SLOW}" if ema_fast > ema_slow else f"EMA{EMA_FAST}<{EMA_SLOW}"

    if reasons:
        return False, " | ".join(reasons), rsi, ema_sig

    log.info(f"[user {user_id}] ✅ Sinal de ENTRADA | RSI={rsi:.1f} | {ema_sig} | EMA200_H1 OK ({h1['price']:.0f} > {h1['ema200']:.0f})")
    return True, "Condições favoráveis", rsi, ema_sig


def check_exit_signal(exchange, symbol, entry_price, log, user_id):
    """
    Verifica saídas inteligentes: RSI>70 ou EMA cruzou para baixo.
    Retorna (should_exit, reason) além do TP/SL normal.
    """
    ind = fetch_indicators_5m(exchange, symbol)
    if not ind.get("ok"):
        return False, None

    rsi      = ind["rsi"]
    ema_fast = ind["ema_fast"]
    ema_slow = ind["ema_slow"]

    # RSI sobrecomprado
    if USE_RSI_EXIT and rsi >= RSI_EXIT:
        log.info(f"[user {user_id}] 🔴 Saída RSI sobrecomprado: RSI={rsi:.1f} >= {RSI_EXIT}")
        return True, f"RSI_OVERBOUGHT({rsi:.1f})"

    # EMA cruzou para baixo (tendência virou)
    if USE_EMA_EXIT and ema_fast < ema_slow:
        log.info(f"[user {user_id}] 🔴 Saída EMA cruzou: EMA{EMA_FAST}({ema_fast:.0f}) < EMA{EMA_SLOW}({ema_slow:.0f})")
        return True, f"EMA_CROSS_DOWN"

    return False, None


# =============================================================
# BOT ENGINE
# =============================================================
def _save_error(user_id, msg, s=None):
    if s is None: s = get_bot_state(user_id)
    if not s: return
    upsert_bot_state(user_id, int(s.get("enabled") or 1),
        float(s.get("usdt") or 0), float(s.get("asset") or 0),
        int(s.get("in_position") or 0),
        s.get("entry_price"), s.get("entry_qty"), s.get("entry_time"),
        _now(), last_error=str(msg)[:500],
        last_sl_time=s.get("last_sl_time"),
        daily_losses=int(s.get("daily_losses") or 0),
        daily_loss_date=s.get("daily_loss_date"))

def _get_server_time_offset():
    for url in ["https://api.binance.com/api/v3/time", "https://api.binance.com.br/api/v3/time"]:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                offset = int(r.json()["serverTime"]) - int(time.time() * 1000)
                logging.info(f"Offset Binance: {offset}ms"); return offset
        except: continue
    return 0

def _fetch_balance_retry(exchange, retries=3, delay=3):
    last_err = None
    for attempt in range(retries):
        try: return exchange.fetch_balance({"type": "spot"})
        except Exception as e:
            last_err = e
            if attempt < retries - 1: time.sleep(delay)
    raise last_err

def _make_exchange(api_key, api_secret, testnet):
    try: import ccxt
    except ImportError: raise RuntimeError("pip install ccxt")
    offset = _get_server_time_offset()
    exchange = ccxt.binance({
        "apiKey": api_key, "secret": api_secret,
        "options": {"defaultType": "spot", "recvWindow": 60000, "adjustForTimeDifference": False},
        "enableRateLimit": True,
    })
    if testnet: exchange.set_sandbox_mode(True)
    import time as _t; _off = offset
    exchange.nonce = lambda: int(_t.time() * 1000) + _off
    return exchange


def bot_step(user_id):
    log = logging.getLogger(__name__)
    keys = get_user_keys(user_id)
    if not keys: log.warning(f"[user {user_id}] Sem chaves API."); return

    api_key, api_secret, testnet = keys
    try: exchange = _make_exchange(api_key, api_secret, bool(testnet))
    except Exception as e:
        _save_error(user_id, f"Falha exchange: {e}"); return

    s   = get_bot_state(user_id)
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    # ── Primeira execução ──────────────────────────────────────
    if not s:
        try:
            bal   = _fetch_balance_retry(exchange)
            u_bal = float(bal.get("free", {}).get("USDT", 0) or 0)
            a_bal = float(bal.get("free", {}).get("BTC",  0) or 0)
        except Exception as e:
            _save_error(user_id, f"Saldo inicial: {e}"); return
        upsert_bot_state(user_id, 1, u_bal, a_bal, 0, None, None, None, _now())
        return

    if not int(s.get("enabled") or 0): return

    usdt         = float(s.get("usdt")  or 0.0)
    asset        = float(s.get("asset") or 0.0)
    in_pos       = int(s.get("in_position") or 0)
    entry_price  = s.get("entry_price")
    entry_qty    = s.get("entry_qty")
    entry_time   = s.get("entry_time")
    last_sl_time = s.get("last_sl_time")

    # ── Contador de losses diários ─────────────────────────────
    daily_losses     = int(s.get("daily_losses") or 0)
    daily_loss_date  = s.get("daily_loss_date")
    if daily_loss_date != today:
        daily_losses    = 0
        daily_loss_date = today

    # ── Busca preço ────────────────────────────────────────────
    try:
        ticker = exchange.fetch_ticker(BOT_SYMBOL)
        price  = float(ticker["last"])
    except Exception as e:
        _save_error(user_id, f"Preço: {e}", s); return

    # ══════════════════════════════════════════════════════════
    # SEM POSIÇÃO — lógica de entrada
    # ══════════════════════════════════════════════════════════
    if in_pos == 0:
        if usdt < MIN_USDT_ORDER:
            upsert_bot_state(user_id, 1, usdt, 0.0, 0, None, None, None, _now(),
                             last_sl_time=last_sl_time, daily_losses=daily_losses,
                             daily_loss_date=daily_loss_date)
            return

        # Cooldown após SL
        if last_sl_time:
            try:
                elapsed = (now - datetime.fromisoformat(last_sl_time)).total_seconds()
                if elapsed < COOLDOWN_AFTER_SL:
                    remaining = int(COOLDOWN_AFTER_SL - elapsed)
                    upsert_bot_state(user_id, 1, usdt, 0.0, 0, None, None, None, _now(),
                                     last_error=f"⏳ Cooldown pós-SL: {remaining}s restantes",
                                     last_sl_time=last_sl_time, daily_losses=daily_losses,
                                     daily_loss_date=daily_loss_date)
                    return
            except: pass

        # Verifica sinal de entrada
        can_buy, reason, rsi_val, ema_sig = check_entry_signal(exchange, BOT_SYMBOL, log, user_id)

        if not can_buy:
            log.info(f"[user {user_id}] ⏸ Aguardando: {reason}")
            upsert_bot_state(user_id, 1, usdt, 0.0, 0, None, None, None, _now(),
                             last_error=f"Aguardando: {reason}",
                             last_sl_time=last_sl_time, daily_losses=daily_losses,
                             daily_loss_date=daily_loss_date)
            return

        # ── COMPRAR ───────────────────────────────────────────
        try:
            buy_usdt = usdt * ORDER_USDT_FRAC
            qty_raw  = buy_usdt / price
            qty_str  = exchange.amount_to_precision(BOT_SYMBOL, qty_raw)
            qty_f    = float(qty_str)
            if qty_f <= 0: _save_error(user_id, "Qty zerada", s); return

            log.info(f"[user {user_id}] 🟢 BUY {qty_f:.8f} @ ~{price:.2f} | RSI={rsi_val:.1f} | {ema_sig}")
            order = exchange.create_market_buy_order(BOT_SYMBOL, qty_f)
            oid   = str(order.get("id", ""))
            fp    = float(order.get("average") or order.get("price") or price)
            fq    = float(order.get("filled")  or qty_f)
            fee_r = fp * fq * FEE_RATE_EST

            try:
                bal = _fetch_balance_retry(exchange)
                un  = float(bal.get("free", {}).get("USDT", 0) or 0)
                an  = float(bal.get("free", {}).get("BTC",  0) or 0)
            except:
                un = usdt - (fp * fq); an = asset + fq

            upsert_bot_state(user_id, 1, un, an, 1, fp, fq,
                             now.isoformat(sep=" ", timespec="seconds"), _now(),
                             last_error=None, last_sl_time=None,
                             daily_losses=daily_losses, daily_loss_date=daily_loss_date)
            insert_bot_trade(user_id, "BUY", fp, fq, fee_r, un, an, "BUY_SIGNAL", None,
                             oid, rsi_entry=rsi_val, ema_signal=ema_sig)
            log.info(f"[user {user_id}] ✅ BUY @ {fp:.2f} | USDT={un:.2f}")
        except Exception as e:
            _save_error(user_id, f"Compra: {e}", s)
        return

    # ══════════════════════════════════════════════════════════
    # EM POSIÇÃO — lógica de saída
    # ══════════════════════════════════════════════════════════
    if in_pos == 1 and entry_price and entry_qty:
        ep_f = float(entry_price)
        eq_f = float(entry_qty)
        tp   = ep_f * (1 + TAKE_PROFIT)
        sl   = ep_f * (1 - STOP_LOSS)
        pct  = (price / ep_f - 1) * 100

        held_ok = True
        if entry_time and MIN_HOLD_SECONDS > 0:
            try:
                elapsed = (now - datetime.fromisoformat(entry_time)).total_seconds()
                held_ok = elapsed >= MIN_HOLD_SECONDS
            except: pass

        exit_reason = None

        # 1. Take Profit
        if held_ok and price >= tp:
            exit_reason = "TAKE_PROFIT"
        # 2. Stop Loss
        elif price <= sl:
            exit_reason = "STOP_LOSS"
        # 3. Saídas inteligentes (RSI sobrecomprado ou EMA cruzou)
        elif held_ok:
            smart_exit, smart_reason = check_exit_signal(exchange, BOT_SYMBOL, ep_f, log, user_id)
            if smart_exit:
                exit_reason = smart_reason

        if exit_reason:
            try:
                try:
                    bal_now   = _fetch_balance_retry(exchange)
                    asset_now = float(bal_now.get("free", {}).get("BTC", 0) or 0)
                except: asset_now = asset

                if asset_now <= 0:
                    upsert_bot_state(user_id, 1, usdt, 0.0, 0, None, None, None, _now(),
                                     last_error="BTC zerado ao tentar vender",
                                     last_sl_time=last_sl_time,
                                     daily_losses=daily_losses, daily_loss_date=daily_loss_date)
                    return

                qs    = exchange.amount_to_precision(BOT_SYMBOL, asset_now)
                qs_f  = float(qs)
                order = exchange.create_market_sell_order(BOT_SYMBOL, qs_f)
                oid   = str(order.get("id", ""))
                sp    = float(order.get("average") or order.get("price") or price)
                sq    = float(order.get("filled")  or asset_now)
                gross = sp * sq
                fee_r = gross * FEE_RATE_EST
                pnl   = (gross - fee_r) - (ep_f * eq_f)

                try:
                    bal = _fetch_balance_retry(exchange)
                    un  = float(bal.get("free", {}).get("USDT", 0) or 0)
                    an  = float(bal.get("free", {}).get("BTC",  0) or 0)
                except:
                    un = usdt + (sp * sq - fee_r); an = 0.0

                # Atualiza losses diários
                is_loss = pnl < 0
                new_daily = daily_losses + (1 if is_loss else 0)
                new_sl_time = _now() if exit_reason == "STOP_LOSS" else None

                upsert_bot_state(user_id, 1, un, an, 0, None, None, None, _now(),
                                 last_error=None, last_sl_time=new_sl_time,
                                 daily_losses=new_daily, daily_loss_date=daily_loss_date)
                insert_bot_trade(user_id, "SELL", sp, sq, fee_r, un, an, exit_reason, pnl, oid)
                emoji = "🟢" if pnl > 0 else "🔴"
                log.info(f"[user {user_id}] {emoji} SELL ({exit_reason}) @ {sp:.2f} | pnl={pnl:.4f} | losses_hoje={new_daily}")

            except Exception as e:
                _save_error(user_id, f"Venda: {e}", s)
        else:
            upsert_bot_state(user_id, 1, usdt, asset, 1, entry_price, entry_qty,
                             entry_time, _now(), last_error=s.get("last_error"),
                             last_sl_time=last_sl_time,
                             daily_losses=daily_losses, daily_loss_date=daily_loss_date)


def run_bot_loop():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler("bot.log", encoding="utf-8"), logging.StreamHandler()]
    )
    init_db()
    log = logging.getLogger(__name__)
    log.info("=" * 60)
    log.info("  OBS PRO BOT v3.0 — Estratégia Completa")
    log.info(f"  Par: {BOT_SYMBOL} | TP: {TAKE_PROFIT*100:.1f}% | SL: {STOP_LOSS*100:.1f}%")
    log.info(f"  ENTRADA: RSI {RSI_MIN}-{RSI_MAX} + EMA{EMA_FAST}/{EMA_SLOW} + EMA{EMA_TREND} H1")
    log.info(f"  SAÍDA: TP | SL | RSI>{RSI_EXIT} | EMA cross down")
    log.info(f"  Cooldown SL: {COOLDOWN_AFTER_SL}s | Ciclo: {BOT_LOOP_INTERVAL}s")
    log.info("=" * 60)

    erros_consecutivos = 0
    while True:
        try:
            ativos = get_all_active_bot_users()
            if ativos:
                for uid in ativos:
                    try:
                        bot_step(uid)
                        erros_consecutivos = 0
                    except Exception as e:
                        erros_consecutivos += 1
                        log.error(f"[user {uid}] Erro: {e}", exc_info=True)
                        if erros_consecutivos >= 5:
                            log.critical("5 erros consecutivos. Aguardando 60s...")
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
except: HAS_AUTOREFRESH = False

init_db()
st.set_page_config(page_title="OBS PRO — BOT v3.0", layout="wide")

def fetch_price_display(symbol):
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price",
                         params={"symbol": symbol.replace("/","").upper()}, timeout=6)
        if r.status_code == 200: return float(r.json()["price"])
    except: pass
    return None

def do_login(user):
    token = create_session(user[0])
    st.session_state.user  = user
    st.session_state.token = token
    try: st.query_params["sid"] = token
    except: pass

def do_logout():
    token = st.session_state.get("token", "")
    if token: delete_session(token)
    st.session_state.user  = None
    st.session_state.token = ""
    try: st.query_params.clear()
    except: pass
    st.rerun()

if "user"  not in st.session_state: st.session_state.user  = None
if "token" not in st.session_state: st.session_state.token = ""

if st.session_state.user is None:
    try:
        sid = st.query_params.get("sid", "")
        if sid:
            recovered = get_session_user(sid)
            if recovered:
                st.session_state.user  = recovered
                st.session_state.token = sid
            else:
                try: st.query_params.clear()
                except: pass
    except: pass

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
        try: create_user(nu, np_, "user", rc or None); st.success("Conta criada! Faça login.")
        except Exception as e: st.error(str(e))
    st.divider()
    st.caption("🔁 Auto atualização")
    auto_ref = st.checkbox("Ativar", value=True)
    ref_sec  = st.slider("Intervalo (s)", 5, 60, 15)
    if auto_ref and HAS_AUTOREFRESH: st_autorefresh(interval=ref_sec * 1000, key="ar")
    elif auto_ref: st.caption("⚠️ pip install streamlit-autorefresh")

st.title("OBS PRO — BOT v3.0  🤖")
st.caption(
    f"ENTRADA: RSI({RSI_PERIOD}) {RSI_MIN}-{RSI_MAX} + EMA{EMA_FAST}/{EMA_SLOW} + EMA{EMA_TREND}(H1) | "
    f"SAÍDA: TP {TAKE_PROFIT*100:.1f}% | SL {STOP_LOSS*100:.1f}% | RSI>{RSI_EXIT} | EMA cross | "
    f"Cooldown: {COOLDOWN_AFTER_SL}s"
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
    s        = get_bot_state(user_id)

    if not has_keys:
        st.warning("⚠️ Cadastre suas chaves API na aba **🔑 Chaves API** antes de operar.")

    bot_on = bool(int(s.get("enabled") or 0)) if s else False
    new_on = st.toggle("🟢 Operar na Binance Brasil (REAL)", value=bot_on, disabled=not has_keys)

    if s and int(s.get("enabled") or 0) != int(new_on):
        upsert_bot_state(user_id, int(new_on),
            float(s.get("usdt") or 0), float(s.get("asset") or 0),
            int(s.get("in_position") or 0),
            s.get("entry_price"), s.get("entry_qty"), s.get("entry_time"),
            s.get("last_step_ts"), s.get("last_error"), s.get("last_sl_time"),
            int(s.get("daily_losses") or 0), s.get("daily_loss_date"))
        st.rerun()
    elif not s and new_on:
        upsert_bot_state(user_id, 1, 0.0, 0.0, 0, None, None, None, None)
        st.rerun()

    if not s:
        st.info("Ative o bot e rode: `python dashboard.py --bot`")
    else:
        s = get_bot_state(user_id)
        err = s.get("last_error")
        if err:
            if "Aguardando" in str(err) or "Cooldown" in str(err) or "⏳" in str(err):
                st.info(f"📊 {err}")
            else:
                st.error(f"🚨 {err}")

        lts = s.get("last_step_ts")
        if lts: st.caption(f"⏱ Último ciclo: `{lts}`")
        else: st.warning("⚠️ Runner não detectado. Rode: `python dashboard.py --bot`")

        price_now  = fetch_price_display(BOT_SYMBOL)
        bot_usdt   = float(s.get("usdt")  or 0.0)
        bot_asset  = float(s.get("asset") or 0.0)
        in_pos     = int(s.get("in_position") or 0)
        entry_price = s.get("entry_price")
        entry_time  = s.get("entry_time")
        daily_losses = int(s.get("daily_losses") or 0)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("USDT (exchange)", f"{bot_usdt:.2f}")
        c2.metric("BTC em carteira", f"{bot_asset:.6f}")
        c3.metric("Posição", "🟡 COMPRADO" if in_pos else "⚪ FLAT")
        c4.metric("Preço atual", f"{price_now:.2f}" if price_now else "—")

        st.divider()

        if in_pos and entry_price:
            ep   = float(entry_price)
            tp_p = ep * (1 + TAKE_PROFIT)
            sl_p = ep * (1 - STOP_LOSS)
            a, b, c_, d = st.columns(4)
            a.metric("Entrada",     f"{ep:.2f}")
            b.metric("Take Profit", f"{tp_p:.2f}")
            c_.metric("Stop Loss",  f"{sl_p:.2f}")
            if price_now:
                pct = (price_now / ep - 1) * 100
                d.metric("P&L atual", f"{pct:+.3f}%")
            if entry_time:
                try:
                    secs = int((datetime.now() - datetime.fromisoformat(entry_time)).total_seconds())
                    st.caption(f"⏱ Em posição há {secs}s")
                except: pass

        st.divider()

        # Painel da estratégia v3.0
        st.subheader("🧠 Estratégia v3.0")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**📥 Filtros de ENTRADA**")
            st.info(f"EMA{EMA_TREND} H1 — preço acima da tendência macro")
            st.info(f"EMA{EMA_FAST}/{EMA_SLOW} — tendência de alta no 5m")
            st.info(f"RSI {RSI_PERIOD} — zona {RSI_MIN} a {RSI_MAX}")
        with col2:
            st.markdown("**📤 Gatilhos de SAÍDA**")
            st.success(f"✅ Take Profit +{TAKE_PROFIT*100:.1f}%")
            st.error(f"❌ Stop Loss -{STOP_LOSS*100:.1f}%")
            st.warning(f"⚠️ RSI > {RSI_EXIT} (sobrecomprado)")
            st.warning(f"⚠️ EMA{EMA_FAST} cruzar abaixo EMA{EMA_SLOW}")

        st.divider()
        st.subheader("📈 Performance")
        df_tr = load_bot_trades(user_id, 500)
        m     = compute_metrics(df_tr)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total vendas",  f"{m['sells']}")
        m2.metric("Winrate",       f"{m['winrate']:.1f}%")
        m3.metric("PnL realizado", f"{m['pnl']:.4f} USDT")
        m4.metric("Ganhos/Perdas", f"{m['wins']}W / {m['losses']}L")

        st.subheader("📋 Histórico de trades")
        if df_tr.empty:
            st.info("Sem operações. Rode: `python dashboard.py --bot`")
        else:
            st.dataframe(df_tr.tail(200), use_container_width=True)

with tabs[1]:
    bal = user_balance(user_id)
    c1, c2, c3 = st.columns(3)
    c1.metric("Usuário", username)
    c2.metric("Saldo ledger", f"{bal:.2f} USDT")
    c3.metric("Meu código", my_code)
    if referrer_code: st.caption(f"Indicado por: `{referrer_code}`")

with tabs[2]:
    st.subheader("🔑 Chaves API — Binance Brasil")
    st.warning("⚠️ Use chaves com permissão apenas de **Spot Trading**. NUNCA habilite saque.")
    ex = get_user_keys(user_id)
    if ex: st.success(f"✅ Chaves cadastradas | Key: `{ex[0][:8]}...`")
    with st.form("form_keys"):
        nk = st.text_input("API Key", type="password")
        ns = st.text_input("API Secret", type="password")
        tn = st.checkbox("Usar Testnet", value=False)
        if st.form_submit_button("💾 Salvar chaves"):
            try: save_user_keys(user_id, nk, ns, tn); st.success("✅ Chaves salvas!"); st.rerun()
            except Exception as e: st.error(str(e))

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
        except Exception as e: st.error(str(e))
    st.divider()
    rows = list_deposits(user_id=user_id)
    if rows:
        st.dataframe(pd.DataFrame(rows, columns=["id","valor","txid","status","criado","revisado","nota"]),
                     use_container_width=True)
    else: st.info("Sem aportes ainda.")

with tabs[4]:
    st.subheader("💸 Solicitar saque")
    bal = user_balance(user_id)
    st.metric("Saldo disponível", f"{bal:.2f} USDT")
    amt_w = st.number_input("Valor (USDT)", min_value=0.0, step=10.0, format="%.2f", key="amt_w")
    net_w = st.selectbox("Rede", ["TRC20", "BEP20", "ERC20"])
    adr_w = st.text_input("Endereço destino")
    fee_w = amt_w * WITHDRAW_FEE_RATE
    c1, c2, c3 = st.columns(3)
    c1.metric("Taxa", f"{WITHDRAW_FEE_RATE*100:.0f}%")
    c2.metric("Taxa (USDT)", f"{fee_w:.2f}")
    c3.metric("Você recebe", f"{amt_w - fee_w:.2f}")
    if st.button("📤 Solicitar saque"):
        try:
            if amt_w <= 0: st.error("Informe um valor.")
            else: create_withdrawal(user_id, amt_w, net_w, adr_w); st.success("Solicitado!")
        except Exception as e: st.error(str(e))
    st.divider()
    rows = list_withdrawals(user_id=user_id)
    if rows:
        st.dataframe(pd.DataFrame(rows, columns=["id","valor","taxa","liquido","rede","endereco","txid_pago","status","criado","revisado","nota"]),
                     use_container_width=True)
    else: st.info("Sem saques ainda.")

with tabs[5]:
    st.subheader("📄 Extrato")
    with _DB_LOCK:
        conn   = db()
        df_led = pd.read_sql_query(
            "SELECT created_at,kind,amount_usdt,ref_table,ref_id FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 500",
            conn, params=(user_id,))
        conn.close()
    if df_led.empty: st.info("Sem movimentações.")
    else:
        st.dataframe(df_led, use_container_width=True)
        st.download_button("⬇️ Baixar CSV", df_led.to_csv(index=False).encode(), "extrato.csv", "text/csv")

if role == "admin":
    with tabs[6]:
        st.subheader("⚙️ Administração")
        st.markdown("### 👥 Usuários")
        ul = list_users()
        if ul:
            st.dataframe(pd.DataFrame(ul, columns=["id","username","role","criado","codigo"]), use_container_width=True)

        st.divider()
        st.markdown("### 💰 Aportes pendentes")
        dep_all = list_deposits()
        dep_df  = pd.DataFrame(dep_all, columns=["id","username","valor","txid","status","criado","revisado","nota"])
        pend_d  = dep_df[dep_df["status"] == "PENDING"]
        if pend_d.empty: st.info("Nenhum aporte pendente.")
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
        w_df  = pd.DataFrame(w_all, columns=["id","username","valor_req","taxa","liquido","rede","endereco","txid_pago","status","criado","revisado","nota"])
        pend_w = w_df[w_df["status"] == "PENDING"]
        if pend_w.empty: st.info("Nenhum saque pendente.")
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
        if aprov_w.empty: st.info("Nenhum saque aprovado aguardando pagamento.")
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
            conn    = db()
            df_bots = pd.read_sql_query("""
                SELECT u.username, bs.enabled, bs.usdt, bs.asset, bs.in_position,
                       bs.entry_price, bs.last_step_ts, bs.last_error, bs.daily_losses,
                       CASE WHEN uk.user_id IS NOT NULL THEN 'Sim' ELSE 'Não' END as tem_chave
                FROM bot_state bs
                JOIN users u ON u.id=bs.user_id
                LEFT JOIN user_keys uk ON uk.user_id=bs.user_id
                ORDER BY u.username
            """, conn)
            conn.close()
        if not df_bots.empty: st.dataframe(df_bots, use_container_width=True)
        else: st.info("Nenhum bot ativo ainda.")
