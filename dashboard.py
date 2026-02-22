#!/usr/bin/env python3
# =============================================================
# OBS PRO BOT — ARQUIVO ÚNICO COMPLETO (STREAMLIT + BOT RUNNER)
#
# Instalação:
#   pip install streamlit pandas requests ccxt streamlit-autorefresh extra-streamlit-components
#
# Rodar:
#   1) Interface:
#      streamlit run dashboard.py --server.port 8501
#   2) Runner 24/7:
#      python dashboard.py --bot
#
# Observação importante:
# - No Streamlit Cloud você NÃO deve rodar o runner "--bot" no mesmo processo.
#   Cloud roda só a UI. Para bot 24/7, use VPS/Render/Railway/etc.
# =============================================================

import sys
BOT_MODE = "--bot" in sys.argv

import os
import sqlite3
import hashlib
import time
import logging
import requests
from datetime import datetime
import pandas as pd


# =============================================================
# ★ CONFIG — EDITE AQUI ANTES DE SUBIR ★
# =============================================================
# DB no mesmo diretório do arquivo (evita “abas em branco” no Cloud)
DB_PATH               = os.path.join(os.path.dirname(__file__), "mvp_funds.db")

DEFAULT_ADMIN_USER    = "admin"
DEFAULT_ADMIN_PASS    = "LU87347748"     # ← MUDE ISSO

DEPOSIT_ADDRESS_FIXED = "0xBa4D5e87e8bcaA85bF29105AB3171b9fDb2eF9dd"  # ← MUDE ISSO
DEPOSIT_NETWORK_LABEL = "ERC20"

WITHDRAW_FEE_RATE     = 0.05    # 5% taxa de saque

BOT_SYMBOL            = "BTC/USDT"
TAKE_PROFIT           = 0.004   # +0.4%
STOP_LOSS             = 0.003   # -0.3%
FEE_RATE_EST          = 0.001   # 0.1% fee estimado
ORDER_USDT_FRAC       = 1.00    # usa 100% do saldo disponível
MIN_USDT_ORDER        = 10.0    # mínimo para abrir ordem
BOT_LOOP_INTERVAL     = 15      # segundos entre ciclos
MIN_HOLD_SECONDS      = 0       # tempo mínimo em posição antes de vender

# Chave secreta para assinar o cookie (mude para algo único seu)
COOKIE_SECRET         = "obspro-segredo-troque-isso-2024"
COOKIE_NAME           = "obspro_session"
COOKIE_EXPIRY_DAYS    = 30


# =============================================================
# DATABASE
# =============================================================
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=20)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

def make_code(username: str) -> str:
    return sha256(username + "|code")[:8]

def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")

def init_db():
    conn = db()
    cur  = conn.cursor()

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

    conn.commit()

    # Migração segura — adiciona colunas novas se não existirem
    for migration in [
        "ALTER TABLE bot_state ADD COLUMN last_error TEXT",
        "ALTER TABLE bot_trades ADD COLUMN order_id TEXT",
    ]:
        try:
            conn.execute(migration)
            conn.commit()
        except Exception:
            pass

    cur.execute("SELECT id FROM users WHERE username=?", (DEFAULT_ADMIN_USER,))
    if cur.fetchone() is None:
        cur.execute("""INSERT INTO users (username, pass_hash, role, created_at, my_code)
                       VALUES (?,?,?,?,?)""",
                    (DEFAULT_ADMIN_USER, sha256(DEFAULT_ADMIN_PASS), "admin",
                     _now(), make_code(DEFAULT_ADMIN_USER)))
        conn.commit()

    conn.close()


# ── Usuários ──────────────────────────────────────────────────
def get_user_by_username(username: str):
    conn = db(); cur = conn.cursor()
    cur.execute("""SELECT id, username, pass_hash, role, created_at, referrer_code, my_code
                   FROM users WHERE username=?""", (username,))
    row = cur.fetchone(); conn.close(); return row

def get_user_by_id(user_id: int):
    conn = db(); cur = conn.cursor()
    cur.execute("""SELECT id, username, pass_hash, role, created_at, referrer_code, my_code
                   FROM users WHERE id=?""", (user_id,))
    row = cur.fetchone(); conn.close(); return row

def auth(username: str, password: str):
    u = get_user_by_username(username.strip())
    return u if u and sha256(password) == u[2] else None

def create_user(username: str, password: str, role: str, referrer_code=None):
    username = username.strip()
    if not username or not password:
        raise ValueError("Preencha usuário e senha.")
    conn = db(); cur = conn.cursor()
    if referrer_code:
        cur.execute("SELECT id FROM users WHERE my_code=?", (referrer_code.strip(),))
        if not cur.fetchone():
            conn.close(); raise ValueError("Código de indicação inválido.")
    try:
        cur.execute("""INSERT INTO users (username, pass_hash, role, created_at, referrer_code, my_code)
                       VALUES (?,?,?,?,?,?)""",
                    (username, sha256(password), role, _now(),
                     referrer_code.strip() if referrer_code else None,
                     make_code(username)))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close(); raise ValueError("Usuário já existe.")
    conn.close()

def list_users():
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT id, username, role, created_at, my_code FROM users ORDER BY id")
    rows = cur.fetchall(); conn.close(); return rows


# ── Chaves API ────────────────────────────────────────────────
def save_user_keys(user_id: int, api_key: str, api_secret: str, testnet: bool = False):
    if not api_key.strip() or not api_secret.strip():
        raise ValueError("API Key e Secret são obrigatórios.")
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT user_id FROM user_keys WHERE user_id=?", (user_id,))
    exists = cur.fetchone() is not None
    if exists:
        cur.execute("UPDATE user_keys SET api_key=?, api_secret=?, testnet=?, updated_at=? WHERE user_id=?",
                    (api_key.strip(), api_secret.strip(), int(testnet), _now(), user_id))
    else:
        cur.execute("INSERT INTO user_keys (user_id, exchange, api_key, api_secret, testnet, updated_at) VALUES (?,?,?,?,?,?)",
                    (user_id, "binance", api_key.strip(), api_secret.strip(), int(testnet), _now()))
    conn.commit(); conn.close()

def get_user_keys(user_id: int):
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT api_key, api_secret, testnet FROM user_keys WHERE user_id=?", (user_id,))
    row = cur.fetchone(); conn.close(); return row


# ── Ledger / Saldo ────────────────────────────────────────────
def add_ledger(user_id: int, kind: str, amount_usdt: float, ref_table=None, ref_id=None):
    conn = db(); cur = conn.cursor()
    cur.execute("INSERT INTO ledger (user_id, kind, amount_usdt, ref_table, ref_id, created_at) VALUES (?,?,?,?,?,?)",
                (user_id, kind, float(amount_usdt), ref_table, ref_id, _now()))
    conn.commit(); conn.close()

def user_balance(user_id: int) -> float:
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(amount_usdt),0) FROM ledger WHERE user_id=?", (user_id,))
    bal = float(cur.fetchone()[0] or 0); conn.close(); return bal


# ── Depósitos ─────────────────────────────────────────────────
def create_deposit(user_id: int, amount_usdt: float, txid: str):
    if not txid or not txid.strip(): raise ValueError("TXID é obrigatório.")
    conn = db(); cur = conn.cursor()
    cur.execute("INSERT INTO deposits (user_id, amount_usdt, txid, deposit_address, status, created_at) VALUES (?,?,?,?,?,?)",
                (user_id, float(amount_usdt), txid.strip(), DEPOSIT_ADDRESS_FIXED, "PENDING", _now()))
    conn.commit(); conn.close()

def list_deposits(user_id=None):
    conn = db(); cur = conn.cursor()
    if user_id is None:
        cur.execute("""SELECT d.id, u.username, d.amount_usdt, d.txid, d.status,
                              d.created_at, d.reviewed_at, d.note
                       FROM deposits d JOIN users u ON u.id=d.user_id ORDER BY d.id DESC""")
    else:
        cur.execute("""SELECT d.id, d.amount_usdt, d.txid, d.status, d.created_at, d.reviewed_at, d.note
                       FROM deposits d WHERE d.user_id=? ORDER BY d.id DESC""", (user_id,))
    rows = cur.fetchall(); conn.close(); return rows

def admin_review_deposit(deposit_id: int, approve: bool, admin_id: int, note: str = ""):
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT user_id, amount_usdt, status FROM deposits WHERE id=?", (deposit_id,))
    row = cur.fetchone()
    if not row: conn.close(); raise ValueError("Depósito não encontrado.")
    user_id, amt, status = row
    if status != "PENDING": conn.close(); raise ValueError("Já revisado.")
    new_status = "APPROVED" if approve else "REJECTED"
    cur.execute("UPDATE deposits SET status=?, reviewed_at=?, reviewed_by=?, note=? WHERE id=?",
                (new_status, _now(), admin_id, note, deposit_id))
    conn.commit(); conn.close()
    if approve: add_ledger(user_id, "DEPOSIT", float(amt), "deposits", deposit_id)


# ── Saques ────────────────────────────────────────────────────
def create_withdrawal(user_id: int, amount_usdt: float, network: str, address: str):
    bal = user_balance(user_id)
    if amount_usdt <= 0:  raise ValueError("Valor inválido.")
    if amount_usdt > bal: raise ValueError(f"Saldo insuficiente: {bal:.2f} USDT")
    if not network.strip() or not address.strip(): raise ValueError("Rede e endereço obrigatórios.")
    fee = amount_usdt * WITHDRAW_FEE_RATE
    net = amount_usdt - fee
    conn = db(); cur = conn.cursor()
    cur.execute("""INSERT INTO withdrawals
        (user_id,amount_request_usdt,fee_rate,fee_usdt,amount_net_usdt,network,address,status,created_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (user_id, float(amount_usdt), float(WITHDRAW_FEE_RATE), float(fee),
         float(net), network.strip(), address.strip(), "PENDING", _now()))
    conn.commit(); conn.close()

def list_withdrawals(user_id=None):
    conn = db(); cur = conn.cursor()
    if user_id is None:
        cur.execute("""SELECT w.id, u.username, w.amount_request_usdt, w.fee_usdt, w.amount_net_usdt,
                              w.network, w.address, w.paid_txid, w.status, w.created_at, w.reviewed_at, w.note
                       FROM withdrawals w JOIN users u ON u.id=w.user_id ORDER BY w.id DESC""")
    else:
        cur.execute("""SELECT w.id, w.amount_request_usdt, w.fee_usdt, w.amount_net_usdt,
                              w.network, w.address, w.paid_txid, w.status, w.created_at, w.reviewed_at, w.note
                       FROM withdrawals w WHERE w.user_id=? ORDER BY w.id DESC""", (user_id,))
    rows = cur.fetchall(); conn.close(); return rows

def admin_review_withdrawal(wid: int, approve: bool, admin_id: int, note: str = ""):
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT user_id, amount_request_usdt, status FROM withdrawals WHERE id=?", (wid,))
    row = cur.fetchone()
    if not row: conn.close(); raise ValueError("Saque não encontrado.")
    user_id, amt, status = row
    if status != "PENDING": conn.close(); raise ValueError("Já revisado.")
    new_status = "APPROVED" if approve else "REJECTED"
    cur.execute("UPDATE withdrawals SET status=?, reviewed_at=?, reviewed_by=?, note=? WHERE id=?",
                (new_status, _now(), admin_id, note, wid))
    conn.commit(); conn.close()
    if approve: add_ledger(user_id, "WITHDRAWAL", -float(amt), "withdrawals", wid)

def admin_mark_withdraw_paid(wid: int, admin_id: int, paid_txid: str, note: str = ""):
    if not paid_txid.strip(): raise ValueError("TXID do pagamento é obrigatório.")
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT status FROM withdrawals WHERE id=?", (wid,))
    row = cur.fetchone()
    if not row:        conn.close(); raise ValueError("Saque não encontrado.")
    if row[0] != "APPROVED": conn.close(); raise ValueError("Precisa estar APPROVED.")
    cur.execute("UPDATE withdrawals SET status='PAID', paid_txid=?, reviewed_at=?, reviewed_by=?, note=? WHERE id=?",
                (paid_txid.strip(), _now(), admin_id, note, wid))
    conn.commit(); conn.close()


# ── Bot State ─────────────────────────────────────────────────
def get_bot_state(user_id: int) -> dict:
    conn = db(); cur = conn.cursor()
    cur.execute("""SELECT user_id, enabled, usdt, asset, in_position,
                          entry_price, entry_qty, entry_time, last_step_ts, last_error, updated_at
                   FROM bot_state WHERE user_id=?""", (user_id,))
    row = cur.fetchone(); conn.close()
    if not row: return {}
    keys = ["user_id","enabled","usdt","asset","in_position",
            "entry_price","entry_qty","entry_time","last_step_ts","last_error","updated_at"]
    return dict(zip(keys, row))

def upsert_bot_state(user_id, enabled, usdt, asset, in_position,
                     entry_price, entry_qty, entry_time, last_step_ts, last_error=None):
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT user_id FROM bot_state WHERE user_id=?", (user_id,))
    exists = cur.fetchone() is not None
    if exists:
        cur.execute("""UPDATE bot_state SET enabled=?, usdt=?, asset=?, in_position=?,
                       entry_price=?, entry_qty=?, entry_time=?, last_step_ts=?,
                       last_error=?, updated_at=? WHERE user_id=?""",
                    (enabled, float(usdt), float(asset), int(in_position),
                     entry_price, entry_qty, entry_time, last_step_ts, last_error, _now(), user_id))
    else:
        cur.execute("""INSERT INTO bot_state
                       (user_id,enabled,usdt,asset,in_position,entry_price,entry_qty,
                        entry_time,last_step_ts,last_error,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (user_id, enabled, float(usdt), float(asset), int(in_position),
                     entry_price, entry_qty, entry_time, last_step_ts, last_error, _now()))
    conn.commit(); conn.close()

def insert_bot_trade(user_id, side, price, qty, fee_usdt,
                     usdt_balance, asset_balance, reason, pnl_usdt, order_id=None):
    conn = db(); cur = conn.cursor()
    cur.execute("""INSERT INTO bot_trades
        (user_id,time,symbol,side,price,qty,fee_usdt,usdt_balance,asset_balance,reason,pnl_usdt,order_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, _now(), BOT_SYMBOL, side, float(price), float(qty), float(fee_usdt),
         float(usdt_balance), float(asset_balance), reason, pnl_usdt, order_id))
    conn.commit(); conn.close()

def load_bot_trades(user_id: int, limit: int = 300) -> pd.DataFrame:
    conn = db()
    df = pd.read_sql_query("""SELECT time, symbol, side, price, qty, fee_usdt,
                                     usdt_balance, asset_balance, reason, pnl_usdt, order_id
                              FROM bot_trades WHERE user_id=? ORDER BY time DESC LIMIT ?""",
                           conn, params=(user_id, limit))
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
    return {"sells": total, "wins": wins, "losses": losses,
            "winrate": wins / total * 100 if total else 0.0,
            "pnl": float(sells["pnl_usdt"].sum()) if not sells.empty else 0.0}

def get_all_active_bot_users():
    conn = db(); cur = conn.cursor()
    cur.execute("""SELECT bs.user_id FROM bot_state bs
                   JOIN user_keys uk ON uk.user_id = bs.user_id
                   WHERE bs.enabled = 1""")
    rows = cur.fetchall(); conn.close()
    return [r[0] for r in rows]


# =============================================================
# BOT RUNNER
# =============================================================
def _save_error(user_id: int, msg: str):
    s = get_bot_state(user_id)
    if not s: return
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
        logging.error("ccxt não instalado! pip install ccxt")
        return

    keys = get_user_keys(user_id)
    if not keys:
        logging.warning(f"[user {user_id}] Sem chaves API.")
        return

    api_key, api_secret, testnet = keys
    try:
        exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "options": {"defaultType": "spot"},
            "enableRateLimit": True,
        })
        if testnet:
            exchange.set_sandbox_mode(True)
    except Exception as e:
        logging.error(f"[user {user_id}] Falha exchange: {e}")
        _save_error(user_id, str(e))
        return

    s   = get_bot_state(user_id)
    now = datetime.now()

    if not s:
        try:
            bal   = exchange.fetch_balance()
            u_bal = float(bal["free"].get("USDT", 0))
            a_bal = float(bal["free"].get("BTC",  0))
        except Exception:
            u_bal, a_bal = 0.0, 0.0
        upsert_bot_state(user_id, 1, u_bal, a_bal, 0, None, None, None, None)
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
        _save_error(user_id, str(e))
        return

    # ── FLAT → COMPRAR ────────────────────────────────────────
    if in_pos == 0:
        if usdt < MIN_USDT_ORDER:
            logging.info(f"[user {user_id}] Saldo baixo: {usdt:.2f} USDT")
            upsert_bot_state(user_id, 1, usdt, 0.0, 0, None, None, None, _now())
            return
        try:
            buy_usdt = usdt * ORDER_USDT_FRAC
            qty_est  = exchange.amount_to_precision(BOT_SYMBOL, buy_usdt / price)
            order    = exchange.create_market_buy_order(BOT_SYMBOL, float(qty_est))
            oid  = str(order.get("id", ""))

            fp   = float(order.get("average") or order.get("price") or price)
            fq   = float(order.get("filled")  or qty_est)

            fee_r = fp * fq * FEE_RATE_EST

            bal  = exchange.fetch_balance()
            un   = float(bal["free"].get("USDT", 0))
            an   = float(bal["free"].get("BTC",  0))

            upsert_bot_state(
                user_id, 1, un, an, 1, fp, fq,
                now.isoformat(sep=" ", timespec="seconds"),
                _now(),
                last_error=None
            )
            insert_bot_trade(user_id, "BUY", fp, fq, fee_r, un, an, "BUY_AUTO", None, oid)
            logging.info(f"[user {user_id}] ✅ BUY @ {fp:.2f} | qty={fq:.8f}")
        except Exception as e:
            logging.error(f"[user {user_id}] Erro ao comprar: {e}")
            _save_error(user_id, str(e))
        return

    # ── COMPRADO → TP / SL ────────────────────────────────────
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

                upsert_bot_state(user_id, 1, un, an, 0, None, None, None, _now(), last_error=None)
                insert_bot_trade(user_id, "SELL", sp, sq, fee_r, un, an, exit_reason, pnl, oid)
                logging.info(f"[user {user_id}] {'🟢' if pnl>0 else '🔴'} SELL ({exit_reason}) @ {sp:.2f} | pnl={pnl:.4f}")
            except Exception as e:
                logging.error(f"[user {user_id}] Erro ao vender: {e}")
                _save_error(user_id, str(e))
        else:
            upsert_bot_state(
                user_id, 1, usdt, asset, 1, entry_price, entry_qty,
                entry_time, _now(), last_error=s.get("last_error")
            )

def run_bot_loop():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
    )
    init_db()
    log = logging.getLogger(__name__)
    log.info("=" * 50)
    log.info("  OBS PRO BOT — Runner iniciado")
    log.info(f"  Par: {BOT_SYMBOL} | TP: {TAKE_PROFIT*100:.1f}% | SL: {STOP_LOSS*100:.1f}%")
    log.info(f"  Intervalo: {BOT_LOOP_INTERVAL}s")
    log.info("=" * 50)
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
                log.debug("Nenhum bot ativo.")
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

# Cookie lib (fallback para não quebrar no Cloud)
try:
    import extra_streamlit_components as stx
    HAS_COOKIE_LIB = True
except Exception:
    HAS_COOKIE_LIB = False
    stx = None

# autorefresh (fallback)
try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except Exception:
    HAS_AUTOREFRESH = False

import traceback
from contextlib import contextmanager

@contextmanager
def guard(tab_name: str):
    """Evita aba em branco no Cloud: mostra traceback na própria aba."""
    try:
        yield
    except Exception:
        st.error(f"🚨 Erro na aba: {tab_name}")
        st.code(traceback.format_exc())
        st.stop()

def fetch_price_display(symbol: str):
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": symbol.replace("/","").upper()},
            timeout=6
        )
        if r.status_code == 200:
            return float(r.json()["price"])
    except Exception:
        pass
    return None

def make_session_token(user_id: int) -> str:
    raw = f"{user_id}|{COOKIE_SECRET}"
    return f"{user_id}|{sha256(raw)}"

def validate_session_token(token: str):
    try:
        parts = token.split("|")
        if len(parts) != 2:
            return None
        uid_str, token_hash = parts
        uid = int(uid_str)
        raw = f"{uid}|{COOKIE_SECRET}"
        if sha256(raw) == token_hash:
            return uid
    except Exception:
        pass
    return None


init_db()
st.set_page_config(page_title="OBS PRO — BOT", layout="wide")

# Cookie manager seguro
cookie_manager = None
if HAS_COOKIE_LIB:
    try:
        cookie_manager = stx.CookieManager()
    except Exception:
        cookie_manager = None
        HAS_COOKIE_LIB = False

def do_login(user):
    st.session_state.user = user
    if HAS_COOKIE_LIB and cookie_manager is not None:
        token = make_session_token(user[0])
        cookie_manager.set(COOKIE_NAME, token, key="cookie_set")

def do_logout():
    st.session_state.user = None
    if HAS_COOKIE_LIB and cookie_manager is not None:
        cookie_manager.delete(COOKIE_NAME, key="cookie_del")
    st.rerun()

# ── Recupera sessão do cookie se session_state vazia ─────────
if "user" not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None and HAS_COOKIE_LIB and cookie_manager is not None:
    try:
        token = cookie_manager.get(COOKIE_NAME)
        if token:
            uid = validate_session_token(token)
            if uid:
                user_from_cookie = get_user_by_id(uid)
                if user_from_cookie:
                    st.session_state.user = user_from_cookie
    except Exception:
        # não quebra a UI
        pass


# ── Sidebar ───────────────────────────────────────────────────
with st.sidebar:
    st.header("🔐 Login")
    if st.session_state.user:
        st.success(f"Logado: {st.session_state.user[1]} ({st.session_state.user[3]})")
        if st.button("Sair"):
            do_logout()
    else:
        lu = st.text_input("Usuário", key="li_u")
        lp = st.text_input("Senha", type="password", key="li_p")
        if st.button("Entrar"):
            user = auth(lu, lp)
            if user:
                do_login(user)
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos.")

    st.divider()
    st.header("🧾 Cadastro")
    nu  = st.text_input("Novo usuário", key="reg_u")
    np_ = st.text_input("Nova senha",   type="password", key="reg_p")
    rc  = st.text_input("Código indicação (opcional)", key="reg_c")
    if st.button("Criar conta"):
        try:
            create_user(nu, np_, "user", rc or None)
            st.success("Conta criada! Faça login.")
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


# ── Cabeçalho ─────────────────────────────────────────────────
st.title("OBS PRO — BOT  🤖")
st.caption(f"{BOT_SYMBOL} | TP {TAKE_PROFIT*100:.1f}% | SL {STOP_LOSS*100:.1f}% | runner: python dashboard.py --bot")

if not st.session_state.user:
    st.info("Faça login na barra lateral.")
    st.stop()

user = st.session_state.user
user_id, username, _, role, created_at, referrer_code, my_code = user

tab_names = ["📊 Painel BOT","👤 Minha Conta","🔑 Chaves API",
             "💰 Aporte","💸 Saque","📄 Extrato"]
if role == "admin":
    tab_names.append("⚙️ Administração")
tabs = st.tabs(tab_names)


# ══════════════════════════════════════════════════════════════
# TAB 0 — PAINEL BOT
# ══════════════════════════════════════════════════════════════
with tabs[0]:
    with guard("Painel BOT"):
        has_keys = get_user_keys(user_id) is not None
        s        = get_bot_state(user_id)

        if not has_keys:
            st.warning("⚠️ Cadastre suas chaves API na aba **🔑 Chaves API** antes de operar.")

        bot_on = bool(int(s.get("enabled") or 0)) if s else False
        new_on = st.toggle("🟢 Operar na Binance (REAL)", value=bot_on, disabled=not has_keys)

        if s and int(s.get("enabled") or 0) != int(new_on):
            upsert_bot_state(
                user_id, int(new_on),
                float(s.get("usdt") or 0), float(s.get("asset") or 0),
                int(s.get("in_position") or 0),
                s.get("entry_price"), s.get("entry_qty"), s.get("entry_time"),
                s.get("last_step_ts"), s.get("last_error")
            )
            st.rerun()
        elif not s and new_on:
            upsert_bot_state(user_id, 1, 0.0, 0.0, 0, None, None, None, None)
            st.rerun()

        if not s:
            st.info("Ative o bot para iniciar.")
            st.stop()

        s = get_bot_state(user_id)
        err = s.get("last_error")
        if err:
            st.error(f"🚨 Último erro: {err}")

        lts = s.get("last_step_ts")
        if lts:
            st.caption(f"⏱ Último ciclo do runner: `{lts}`")

        price_now   = fetch_price_display(BOT_SYMBOL)
        bot_usdt    = float(s.get("usdt")  or 0.0)
        bot_asset   = float(s.get("asset") or 0.0)
        in_pos      = int(s.get("in_position") or 0)
        entry_price = s.get("entry_price")
        entry_time  = s.get("entry_time")
        pos_txt     = "🟡 COMPRADO" if in_pos else "⚪ FLAT"

        c1,c2,c3,c4 = st.columns(4)
        c1.metric("USDT (exchange)",  f"{bot_usdt:.2f}")
        c2.metric("BTC em carteira",  f"{bot_asset:.6f}")
        c3.metric("Posição",          pos_txt)
        c4.metric("Preço atual",      f"{price_now:.2f}" if price_now else "—")

        st.divider()

        if in_pos and entry_price:
            ep   = float(entry_price)
            tp_p = ep * (1 + TAKE_PROFIT)
            sl_p = ep * (1 - STOP_LOSS)
            a,b,c_,d = st.columns(4)
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
                except Exception:
                    pass

        st.divider()
        st.subheader("📈 Performance")
        df_tr = load_bot_trades(user_id, 500)
        m     = compute_metrics(df_tr)
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Total vendas",  f"{m['sells']}")
        m2.metric("Winrate",       f"{m['winrate']:.1f}%")
        m3.metric("PnL realizado", f"{m['pnl']:.4f} USDT")
        m4.metric("Ganhos/Perdas", f"{m['wins']}W / {m['losses']}L")

        st.subheader("📋 Histórico")
        if df_tr.empty:
            st.info("Sem operações. (No Cloud, o runner não roda. Use VPS/local: python dashboard.py --bot)")
        else:
            st.dataframe(df_tr.tail(200), width="stretch")


# ══════════════════════════════════════════════════════════════
# TAB 1 — MINHA CONTA
# ══════════════════════════════════════════════════════════════
with tabs[1]:
    with guard("Minha Conta"):
        bal = user_balance(user_id)
        c1,c2,c3 = st.columns(3)
        c1.metric("Usuário",      username)
        c2.metric("Saldo ledger", f"{bal:.2f} USDT")
        c3.metric("Meu código",   my_code)
        if referrer_code:
            st.caption(f"Indicado por: `{referrer_code}`")


# ══════════════════════════════════════════════════════════════
# TAB 2 — CHAVES API
# ══════════════════════════════════════════════════════════════
with tabs[2]:
    with guard("Chaves API"):
        st.subheader("🔑 Chaves API Binance")
        st.warning("⚠️ Use chaves com permissão apenas de **Spot Trading**. NUNCA habilite saque.")
        ex = get_user_keys(user_id)
        if ex:
            st.success(f"✅ Chaves cadastradas | Key: `{ex[0][:8]}...` | Testnet: {'Sim' if ex[2] else 'Não'}")

        with st.form("form_keys"):
            nk  = st.text_input("API Key",    type="password")
            ns  = st.text_input("API Secret", type="password")
            tn  = st.checkbox("Usar Testnet (recomendado para testes iniciais)", value=False)
            if st.form_submit_button("💾 Salvar chaves"):
                save_user_keys(user_id, nk, ns, tn)
                st.success("✅ Chaves salvas!")
                st.rerun()

        st.divider()
        st.markdown("""
**Como criar chaves na Binance:**
1. binance.com → Conta → API Management → Criar nova chave
2. Habilite apenas: **Enable Spot & Margin Trading** (se for Spot, melhor ainda)
3. **NÃO habilite Enable Withdrawals** (nunca!)
4. Restrinja ao IP do servidor para máxima segurança
        """)


# ══════════════════════════════════════════════════════════════
# TAB 3 — APORTE
# ══════════════════════════════════════════════════════════════
with tabs[3]:
    with guard("Aporte"):
        st.subheader("💰 Aporte em USDT")
        st.markdown(f"**Rede:** `{DEPOSIT_NETWORK_LABEL}`")
        st.code(DEPOSIT_ADDRESS_FIXED)
        st.caption("Envie USDT para o endereço acima e cole o TXID. O admin confirmará o crédito.")

        amt_d  = st.number_input("Valor (USDT)", min_value=0.0, step=10.0, format="%.2f", key="amt_d")
        txid_d = st.text_input("TXID / Hash da transação")
        if st.button("📤 Enviar comprovante"):
            if amt_d <= 0:
                st.error("Informe um valor.")
            else:
                create_deposit(user_id, amt_d, txid_d)
                st.success("Enviado! Aguarde aprovação.")

        st.divider()
        rows = list_deposits(user_id=user_id)
        if rows:
            # sem columns fixo (evita mismatch no Cloud)
            df = pd.DataFrame(rows, columns=["id","valor","txid","status","criado","revisado","nota"])
            st.dataframe(df, width="stretch")
        else:
            st.info("Sem aportes ainda.")


# ══════════════════════════════════════════════════════════════
# TAB 4 — SAQUE
# ══════════════════════════════════════════════════════════════
with tabs[4]:
    with guard("Saque"):
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

        if st.button("📤 Solicitar saque"):
            if amt_w <= 0:
                st.error("Informe um valor.")
            else:
                create_withdrawal(user_id, amt_w, net_w, adr_w)
                st.success("Solicitado! Aguarde aprovação.")

        st.divider()
        rows = list_withdrawals(user_id=user_id)
        if rows:
            df = pd.DataFrame(rows, columns=["id","valor","taxa","liquido","rede","endereco","txid_pago","status","criado","revisado","nota"])
            st.dataframe(df, width="stretch")
        else:
            st.info("Sem saques ainda.")


# ══════════════════════════════════════════════════════════════
# TAB 5 — EXTRATO
# ══════════════════════════════════════════════════════════════
with tabs[5]:
    with guard("Extrato"):
        st.subheader("📄 Extrato")
        conn   = db()
        df_led = pd.read_sql_query("""SELECT created_at, kind, amount_usdt, ref_table, ref_id
                                      FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 500""",
                                   conn, params=(user_id,))
        conn.close()

        if df_led.empty:
            st.info("Sem movimentações.")
        else:
            st.dataframe(df_led, width="stretch")
            st.download_button(
                "⬇️ Baixar CSV",
                df_led.to_csv(index=False).encode(),
                "extrato.csv",
                "text/csv",
                use_container_width=True  # ok aqui (warning só futuro)
            )


# ══════════════════════════════════════════════════════════════
# TAB 6 — ADMINISTRAÇÃO (somente admin)
# ══════════════════════════════════════════════════════════════
if role == "admin":
    with tabs[6]:
        with guard("Administração"):
            st.subheader("⚙️ Administração")

            st.markdown("### 👥 Usuários")
            ul = list_users()
            if ul:
                dfu = pd.DataFrame(ul, columns=["id","username","role","criado","codigo"])
                st.dataframe(dfu, width="stretch")

            st.divider()
            st.markdown("### 💰 Aportes pendentes")
            dep_all = list_deposits()
            dep_df  = pd.DataFrame(dep_all, columns=["id","username","valor","txid","status","criado","revisado","nota"]) if dep_all else pd.DataFrame(
                columns=["id","username","valor","txid","status","criado","revisado","nota"]
            )
            pend_d  = dep_df[dep_df["status"] == "PENDING"] if not dep_df.empty else dep_df

            if pend_d.empty:
                st.info("Nenhum aporte pendente.")
            else:
                st.dataframe(pend_d, width="stretch")
                did  = st.number_input("ID do depósito", min_value=1, step=1, key="did")
                dn   = st.text_input("Nota", key="dn")
                c1,c2 = st.columns(2)
                with c1:
                    if st.button("✅ Aprovar", use_container_width=True, key="apd"):
                        admin_review_deposit(int(did), True, user_id, dn)
                        st.success("Aprovado!")
                        st.rerun()
                with c2:
                    if st.button("❌ Rejeitar", use_container_width=True, key="rjd"):
                        admin_review_deposit(int(did), False, user_id, dn)
                        st.warning("Rejeitado.")
                        st.rerun()

            st.divider()
            st.markdown("### 💸 Saques pendentes")
            w_all = list_withdrawals()
            w_df  = pd.DataFrame(w_all, columns=["id","username","valor_req","taxa","liquido","rede","endereco","txid_pago","status","criado","revisado","nota"]) if w_all else pd.DataFrame(
                columns=["id","username","valor_req","taxa","liquido","rede","endereco","txid_pago","status","criado","revisado","nota"]
            )
            pend_w = w_df[w_df["status"] == "PENDING"] if not w_df.empty else w_df

            if pend_w.empty:
                st.info("Nenhum saque pendente.")
            else:
                st.dataframe(pend_w, width="stretch")
                wid  = st.number_input("ID do saque", min_value=1, step=1, key="wid")
                wn   = st.text_input("Nota", key="wn")
                c1,c2 = st.columns(2)
                with c1:
                    if st.button("✅ Aprovar", use_container_width=True, key="apw"):
                        admin_review_withdrawal(int(wid), True, user_id, wn)
                        st.success("Aprovado!")
                        st.rerun()
                with c2:
                    if st.button("❌ Rejeitar", use_container_width=True, key="rjw"):
                        admin_review_withdrawal(int(wid), False, user_id, wn)
                        st.warning("Rejeitado.")
                        st.rerun()

            st.divider()
            st.markdown("### ✅ Marcar saque como PAGO")
            aprov_w = w_df[w_df["status"] == "APPROVED"] if not w_df.empty else w_df
            if aprov_w.empty:
                st.info("Nenhum saque aprovado aguardando pagamento.")
            else:
                st.dataframe(aprov_w, width="stretch")
                wid2  = st.number_input("ID saque aprovado", min_value=1, step=1, key="wid2")
                ptxid = st.text_input("TXID do pagamento (obrigatório)", key="ptxid")
                pn    = st.text_input("Nota", key="pn")
                if st.button("💳 Marcar como PAGO", use_container_width=True):
                    admin_mark_withdraw_paid(int(wid2), user_id, ptxid, pn)
                    st.success("Marcado!")
                    st.rerun()

            st.divider()
            st.markdown("### 🤖 Status dos bots por usuário")
            conn = db()
            df_bots = pd.read_sql_query("""
                SELECT u.username, bs.enabled, bs.usdt, bs.asset, bs.in_position,
                       bs.entry_price, bs.last_step_ts, bs.last_error,
                       CASE WHEN uk.user_id IS NOT NULL THEN 'Sim' ELSE 'Não' END as tem_chave
                FROM bot_state bs
                JOIN users u ON u.id = bs.user_id
                LEFT JOIN user_keys uk ON uk.user_id = bs.user_id
                ORDER BY u.username
            """, conn)
            conn.close()

            if not df_bots.empty:
                st.dataframe(df_bots, width="stretch")
            else:
                st.info("Nenhum bot ativo ainda.")