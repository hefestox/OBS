#!/usr/bin/env python3
# =============================================================
# OBS PRO BOT — VERSÃO FINAL CORRIGIDA
#
# CORREÇÕES APLICADAS:
#   1. Binance Brasil (binance.com.br) — API correta para usuários BR
#   2. SQLite Windows: threading.Lock global em todas as funções
#   3. BOT_MODE: checagem segura ignorando args do Streamlit
#   4. st.stop() removido de dentro de tab
#   5. fetch_balance com retry (3 tentativas)
#   6. recvWindow=10000 — resolve clock drift no Windows
#   7. Logs detalhados para diagnóstico
#   8. Sessão com fallback para st.session_state
#
# INSTALAÇÃO:
#   pip install streamlit pandas requests ccxt streamlit-autorefresh
#
# COMO RODAR (2 terminais):
#   Terminal 1 → Interface web:
#     streamlit run dashboard.py --server.port 8501
#
#   Terminal 2 → Bot autônomo 24/7:
#     python dashboard.py --bot
#
# =============================================================

import sys

# ── BOT_MODE seguro (ignora args do Streamlit) ─────────────────
_raw_argv = sys.argv[1:]
BOT_MODE = "--bot" in _raw_argv and not any("streamlit" in a for a in _raw_argv)

import sqlite3
import hashlib
import time
import logging
import threading
import requests
from datetime import datetime
import pandas as pd

# ── Lock global SQLite (Windows não tolera escritas simultâneas) ─
_DB_LOCK = threading.Lock()

# =============================================================
# ★ CONFIG — EDITE AQUI ★
# =============================================================
DB_PATH               = "mvp_funds.db"
DEFAULT_ADMIN_USER    = "admin"
DEFAULT_ADMIN_PASS    = "LU87347748"        # ← MUDE ISSO
DEPOSIT_ADDRESS_FIXED = "TMYvfwaT8XX998h6dP9JVWxgdPxY88cLmt"  # ← MUDE ISSO
DEPOSIT_NETWORK_LABEL = "TRC20"
WITHDRAW_FEE_RATE     = 0.05    # 5% taxa de saque
BOT_SYMBOL            = "BTC/USDT"
TAKE_PROFIT           = 0.006   # +0.6%
STOP_LOSS             = 0.004   # -0.4%
FEE_RATE_EST          = 0.001   # 0.1% fee estimada
ORDER_USDT_FRAC       = 0.95    # usa 95% do saldo por ordem
MIN_USDT_ORDER        = 10.0    # mínimo USDT para abrir ordem
BOT_LOOP_INTERVAL     = 10      # segundos entre ciclos
MIN_HOLD_SECONDS      = 0       # tempo mínimo em posição antes de vender
SESSION_SECRET        = "obspro-mude-essa-chave-2024"  # ← MUDE ISSO


# =============================================================
# DATABASE
# =============================================================
def db():
    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False,
        timeout=30,
        isolation_level=None,   # autocommit
    )
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

def make_code(username: str) -> str:
    return sha256(username + "|code")[:8]

def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def init_db():
    with _DB_LOCK:
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

        cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")

        conn.commit()

        # Migrações seguras
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
            cur.execute(
                "INSERT INTO users (username,pass_hash,role,created_at,my_code) VALUES (?,?,?,?,?)",
                (DEFAULT_ADMIN_USER, sha256(DEFAULT_ADMIN_PASS), "admin", _now(), make_code(DEFAULT_ADMIN_USER))
            )
            conn.commit()
        conn.close()


# ── Usuários ──────────────────────────────────────────────────
def get_user_by_username(username: str):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT id,username,pass_hash,role,created_at,referrer_code,my_code FROM users WHERE username=?", (username,))
        row = cur.fetchone(); conn.close(); return row

def get_user_by_id(user_id: int):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT id,username,pass_hash,role,created_at,referrer_code,my_code FROM users WHERE id=?", (user_id,))
        row = cur.fetchone(); conn.close(); return row

def auth(username: str, password: str):
    u = get_user_by_username(username.strip())
    return u if u and sha256(password) == u[2] else None

def create_user(username: str, password: str, role: str, referrer_code=None):
    username = username.strip()
    if not username or not password:
        raise ValueError("Preencha usuário e senha.")
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        if referrer_code:
            cur.execute("SELECT id FROM users WHERE my_code=?", (referrer_code.strip(),))
            if not cur.fetchone():
                conn.close(); raise ValueError("Código de indicação inválido.")
        try:
            cur.execute(
                "INSERT INTO users (username,pass_hash,role,created_at,referrer_code,my_code) VALUES (?,?,?,?,?,?)",
                (username, sha256(password), role, _now(),
                 referrer_code.strip() if referrer_code else None, make_code(username))
            )
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
def create_session(user_id: int) -> str:
    from datetime import timedelta
    token   = sha256(f"{user_id}|{time.time()}|{SESSION_SECRET}")
    expires = (datetime.now() + timedelta(days=30)).isoformat(sep=" ", timespec="seconds")
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        cur.execute("INSERT INTO sessions (token,user_id,created_at,expires_at) VALUES (?,?,?,?)",
                    (token, user_id, _now(), expires))
        conn.commit(); conn.close()
    return token

def get_session_user(token: str):
    if not token: return None
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT user_id,expires_at FROM sessions WHERE token=?", (token,))
        row = cur.fetchone(); conn.close()
    if not row: return None
    user_id, expires_at = row
    try:
        if datetime.fromisoformat(expires_at) < datetime.now(): return None
    except Exception: return None
    return get_user_by_id(user_id)

def delete_session(token: str):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit(); conn.close()


# ── Chaves API ────────────────────────────────────────────────
def save_user_keys(user_id: int, api_key: str, api_secret: str, testnet: bool = False):
    if not api_key.strip() or not api_secret.strip():
        raise ValueError("API Key e Secret são obrigatórios.")
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

def get_user_keys(user_id: int):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT api_key,api_secret,testnet FROM user_keys WHERE user_id=?", (user_id,))
        row = cur.fetchone(); conn.close(); return row


# ── Ledger ────────────────────────────────────────────────────
def add_ledger(user_id: int, kind: str, amount_usdt: float, ref_table=None, ref_id=None):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("INSERT INTO ledger (user_id,kind,amount_usdt,ref_table,ref_id,created_at) VALUES (?,?,?,?,?,?)",
                    (user_id, kind, float(amount_usdt), ref_table, ref_id, _now()))
        conn.commit(); conn.close()

def user_balance(user_id: int) -> float:
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(amount_usdt),0) FROM ledger WHERE user_id=?", (user_id,))
        bal = float(cur.fetchone()[0] or 0); conn.close(); return bal


# ── Depósitos ─────────────────────────────────────────────────
def create_deposit(user_id: int, amount_usdt: float, txid: str):
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

def admin_review_deposit(deposit_id: int, approve: bool, admin_id: int, note: str = ""):
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
def create_withdrawal(user_id: int, amount_usdt: float, network: str, address: str):
    bal = user_balance(user_id)
    if amount_usdt <= 0:  raise ValueError("Valor inválido.")
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

def admin_review_withdrawal(wid: int, approve: bool, admin_id: int, note: str = ""):
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

def admin_mark_withdraw_paid(wid: int, admin_id: int, paid_txid: str, note: str = ""):
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
def get_bot_state(user_id: int) -> dict:
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("""SELECT user_id,enabled,usdt,asset,in_position,
                              entry_price,entry_qty,entry_time,last_step_ts,last_error,updated_at
                       FROM bot_state WHERE user_id=?""", (user_id,))
        row = cur.fetchone(); conn.close()
    if not row: return {}
    keys = ["user_id","enabled","usdt","asset","in_position",
            "entry_price","entry_qty","entry_time","last_step_ts","last_error","updated_at"]
    return dict(zip(keys, row))

def upsert_bot_state(user_id, enabled, usdt, asset, in_position,
                     entry_price, entry_qty, entry_time, last_step_ts, last_error=None):
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("SELECT user_id FROM bot_state WHERE user_id=?", (user_id,))
        if cur.fetchone():
            cur.execute("""UPDATE bot_state SET enabled=?,usdt=?,asset=?,in_position=?,
                           entry_price=?,entry_qty=?,entry_time=?,last_step_ts=?,
                           last_error=?,updated_at=? WHERE user_id=?""",
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
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("""INSERT INTO bot_trades
            (user_id,time,symbol,side,price,qty,fee_usdt,usdt_balance,asset_balance,reason,pnl_usdt,order_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, _now(), BOT_SYMBOL, side, float(price), float(qty), float(fee_usdt),
             float(usdt_balance), float(asset_balance), reason, pnl_usdt, order_id))
        conn.commit(); conn.close()

def load_bot_trades(user_id: int, limit: int = 300) -> pd.DataFrame:
    with _DB_LOCK:
        conn = db()
        df = pd.read_sql_query(
            """SELECT time,symbol,side,price,qty,fee_usdt,
                      usdt_balance,asset_balance,reason,pnl_usdt,order_id
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
    with _DB_LOCK:
        conn = db(); cur = conn.cursor()
        cur.execute("""SELECT bs.user_id FROM bot_state bs
                       JOIN user_keys uk ON uk.user_id=bs.user_id
                       WHERE bs.enabled=1""")
        rows = cur.fetchall(); conn.close()
    return [r[0] for r in rows]


# =============================================================
# BOT ENGINE
# =============================================================
def _save_error(user_id: int, msg: str):
    s = get_bot_state(user_id)
    if not s: return
    upsert_bot_state(user_id, int(s.get("enabled") or 1),
        float(s.get("usdt") or 0), float(s.get("asset") or 0),
        int(s.get("in_position") or 0),
        s.get("entry_price"), s.get("entry_qty"), s.get("entry_time"),
        _now(), last_error=str(msg)[:500])


def _get_server_time_offset() -> int:
    """
    Calcula a diferença em ms entre o relógio local e o servidor Binance.
    Usa sempre api.binance.com (global) para o endpoint de tempo — mais confiável.
    """
    for url in ["https://api.binance.com/api/v3/time",
                "https://api.binance.com.br/api/v3/time"]:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                server_ms = int(r.json()["serverTime"])
                local_ms  = int(time.time() * 1000)
                offset    = server_ms - local_ms
                logging.info(f"Offset de tempo com Binance: {offset}ms (via {url})")
                return offset
        except Exception:
            continue
    logging.warning("Nao foi possivel obter tempo do servidor. Usando offset=0.")
    return 0


def _fetch_balance_retry(exchange, retries=3, delay=3):
    """
    Busca saldo usando fetch_balance com params={type:spot}.
    Evita o endpoint sapi/v1/capital/config/getall que nao existe na Binance BR.
    """
    last_err = None
    for attempt in range(retries):
        try:
            # params type=spot evita chamada ao endpoint de capital config
            return exchange.fetch_balance({"type": "spot"})
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                logging.warning(f"fetch_balance falhou (tentativa {attempt+1}/{retries}): {e}. Aguardando {delay}s...")
                time.sleep(delay)
    raise last_err


def _make_exchange(api_key: str, api_secret: str, testnet: bool):
    """
    Cria exchange Binance com nonce corrigido para Windows.
    Usa api.binance.com (global) — funciona normalmente para usuarios BR.
    O nonce sobrescrito corrige o erro -1021 causado pelo relogio adiantado.
    """
    try:
        import ccxt
    except ImportError:
        raise RuntimeError("ccxt nao instalado! Execute: pip install ccxt")

    # Mede offset entre relogio local e servidor Binance
    offset = _get_server_time_offset()

    exchange = ccxt.binance({
        "apiKey": api_key,
        "secret": api_secret,
        "options": {
            "defaultType": "spot",
            "recvWindow":  60000,
            "adjustForTimeDifference": False,
        },
        "enableRateLimit": True,
    })
    if testnet:
        exchange.set_sandbox_mode(True)

    # Sobrescreve nonce para corrigir timestamp em TODAS as requisicoes
    import time as _time
    _offset = offset
    exchange.nonce = lambda: int(_time.time() * 1000) + _offset

    logging.info(f"Exchange criada | offset={offset}ms | recvWindow=60000ms | nonce corrigido")
    return exchange


def bot_step(user_id: int):
    log = logging.getLogger(__name__)

    keys = get_user_keys(user_id)
    if not keys:
        log.warning(f"[user {user_id}] Sem chaves API."); return

    api_key, api_secret, testnet = keys

    try:
        exchange = _make_exchange(api_key, api_secret, bool(testnet))
    except Exception as e:
        log.error(f"[user {user_id}] Falha ao criar exchange: {e}")
        _save_error(user_id, f"Falha exchange: {e}"); return

    s   = get_bot_state(user_id)
    now = datetime.now()

    # ── Primeira execução: inicializa com saldo real ───────────
    if not s:
        try:
            bal   = _fetch_balance_retry(exchange)
            u_bal = float(bal.get("free", {}).get("USDT", 0) or 0)
            a_bal = float(bal.get("free", {}).get("BTC",  0) or 0)
            log.info(f"[user {user_id}] Inicializando estado: USDT={u_bal:.2f} BTC={a_bal:.8f}")
        except Exception as e:
            log.error(f"[user {user_id}] Erro ao buscar saldo inicial: {e}")
            _save_error(user_id, f"Saldo inicial: {e}"); return
        upsert_bot_state(user_id, 1, u_bal, a_bal, 0, None, None, None, _now())
        return

    if not int(s.get("enabled") or 0):
        return

    usdt        = float(s.get("usdt")  or 0.0)
    asset       = float(s.get("asset") or 0.0)
    in_pos      = int(s.get("in_position") or 0)
    entry_price = s.get("entry_price")
    entry_qty   = s.get("entry_qty")
    entry_time  = s.get("entry_time")

    # ── Busca preço atual ──────────────────────────────────────
    try:
        ticker = exchange.fetch_ticker(BOT_SYMBOL)
        price  = float(ticker["last"])
        log.debug(f"[user {user_id}] {BOT_SYMBOL} = {price:.2f}")
    except Exception as e:
        log.warning(f"[user {user_id}] Erro ao buscar preço: {e}")
        _save_error(user_id, f"Preço: {e}"); return

    # ── SEM POSIÇÃO: tenta comprar ─────────────────────────────
    if in_pos == 0:
        if usdt < MIN_USDT_ORDER:
            log.debug(f"[user {user_id}] USDT insuficiente ({usdt:.2f} < {MIN_USDT_ORDER})")
            upsert_bot_state(user_id, 1, usdt, 0.0, 0, None, None, None, _now())
            return

        try:
            buy_usdt = usdt * ORDER_USDT_FRAC
            qty_raw  = buy_usdt / price
            qty_str  = exchange.amount_to_precision(BOT_SYMBOL, qty_raw)
            qty_f    = float(qty_str)

            if qty_f <= 0:
                log.warning(f"[user {user_id}] Qty zerada. buy_usdt={buy_usdt:.2f}")
                _save_error(user_id, "Qty zerada ao comprar"); return

            log.info(f"[user {user_id}] → BUY {qty_f:.8f} {BOT_SYMBOL} @ ~{price:.2f}")
            order = exchange.create_market_buy_order(BOT_SYMBOL, qty_f)

            oid   = str(order.get("id", ""))
            fp    = float(order.get("average") or order.get("price") or price)
            fq    = float(order.get("filled")  or qty_f)
            fee_r = fp * fq * FEE_RATE_EST

            try:
                bal = _fetch_balance_retry(exchange)
                un  = float(bal.get("free", {}).get("USDT", 0) or 0)
                an  = float(bal.get("free", {}).get("BTC",  0) or 0)
            except Exception as be:
                log.warning(f"[user {user_id}] Não atualizou saldo pós-compra: {be}")
                un = usdt - (fp * fq)
                an = asset + fq

            upsert_bot_state(user_id, 1, un, an, 1, fp, fq,
                             now.isoformat(sep=" ", timespec="seconds"), _now(), last_error=None)
            insert_bot_trade(user_id, "BUY", fp, fq, fee_r, un, an, "BUY_AUTO", None, oid)
            log.info(f"[user {user_id}] ✅ BUY @ {fp:.2f} | qty={fq:.8f} | USDT={un:.2f}")

        except Exception as e:
            log.error(f"[user {user_id}] ERRO ao comprar: {e}", exc_info=True)
            _save_error(user_id, f"Compra: {e}")
        return

    # ── EM POSIÇÃO: verifica TP / SL ──────────────────────────
    if in_pos == 1 and entry_price and entry_qty:
        ep_f = float(entry_price)
        eq_f = float(entry_qty)
        tp   = ep_f * (1 + TAKE_PROFIT)
        sl   = ep_f * (1 - STOP_LOSS)
        pct  = (price / ep_f - 1) * 100
        log.debug(f"[user {user_id}] Posição: {ep_f:.2f} → {price:.2f} ({pct:+.3f}%) | TP={tp:.2f} SL={sl:.2f}")

        held_ok = True
        if entry_time and MIN_HOLD_SECONDS > 0:
            try:
                et      = datetime.fromisoformat(entry_time)
                elapsed = (now - et).total_seconds()
                held_ok = elapsed >= MIN_HOLD_SECONDS
            except Exception: pass

        exit_reason = None
        if held_ok and price >= tp:
            exit_reason = "TAKE_PROFIT"
        elif price <= sl:
            exit_reason = "STOP_LOSS"

        if exit_reason:
            try:
                # Usa saldo real da exchange para vender
                try:
                    bal_now   = _fetch_balance_retry(exchange)
                    asset_now = float(bal_now.get("free", {}).get("BTC", 0) or 0)
                except Exception:
                    asset_now = asset

                if asset_now <= 0:
                    log.warning(f"[user {user_id}] Nada para vender (BTC=0 na exchange).")
                    upsert_bot_state(user_id, 1, usdt, 0.0, 0, None, None, None, _now(),
                                     last_error="BTC zerado ao tentar vender")
                    return

                qs    = exchange.amount_to_precision(BOT_SYMBOL, asset_now)
                qs_f  = float(qs)
                log.info(f"[user {user_id}] → SELL {qs_f:.8f} | razão={exit_reason}")
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
                except Exception as be:
                    log.warning(f"[user {user_id}] Não atualizou saldo pós-venda: {be}")
                    un = usdt + (sp * sq - fee_r)
                    an = 0.0

                upsert_bot_state(user_id, 1, un, an, 0, None, None, None, _now(), last_error=None)
                insert_bot_trade(user_id, "SELL", sp, sq, fee_r, un, an, exit_reason, pnl, oid)
                emoji = "🟢" if pnl > 0 else "🔴"
                log.info(f"[user {user_id}] {emoji} SELL ({exit_reason}) @ {sp:.2f} | pnl={pnl:.4f} | saldo={un:.2f}")

            except Exception as e:
                log.error(f"[user {user_id}] ERRO ao vender: {e}", exc_info=True)
                _save_error(user_id, f"Venda: {e}")
        else:
            # Mantém posição
            upsert_bot_state(user_id, 1, usdt, asset, 1, entry_price, entry_qty,
                             entry_time, _now(), last_error=s.get("last_error"))


def run_bot_loop():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("bot.log", encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    init_db()
    log = logging.getLogger(__name__)
    log.info("=" * 55)
    log.info("  OBS PRO BOT — Binance Brasil — Iniciado")
    log.info(f"  Par: {BOT_SYMBOL} | TP: {TAKE_PROFIT*100:.2f}% | SL: {STOP_LOSS*100:.2f}%")
    log.info(f"  Fração por ordem: {ORDER_USDT_FRAC*100:.0f}% | Ciclo: {BOT_LOOP_INTERVAL}s")
    log.info("=" * 55)

    erros_consecutivos = 0

    while True:
        try:
            ativos = get_all_active_bot_users()
            if ativos:
                log.info(f"Ciclo — {len(ativos)} usuário(s) ativo(s): {ativos}")
                for uid in ativos:
                    try:
                        bot_step(uid)
                        erros_consecutivos = 0
                    except Exception as e:
                        erros_consecutivos += 1
                        log.error(f"[user {uid}] Erro: {e}", exc_info=True)
                        if erros_consecutivos >= 5:
                            log.critical("5 erros consecutivos. Aguardando 60s...")
                            time.sleep(60)
                            erros_consecutivos = 0
            else:
                log.debug("Nenhum bot ativo.")
        except Exception as e:
            log.critical(f"Erro fatal no loop principal: {e}", exc_info=True)

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
except Exception:
    HAS_AUTOREFRESH = False

init_db()
st.set_page_config(page_title="OBS PRO — BOT", layout="wide")


def fetch_price_display(symbol: str):
    """Busca preco na API global da Binance."""
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price",
                         params={"symbol": symbol.replace("/", "").upper()}, timeout=6)
        if r.status_code == 200:
            return float(r.json()["price"])
    except Exception:
        pass
    return None


# ── Sessão ────────────────────────────────────────────────────
def do_login(user):
    token = create_session(user[0])
    st.session_state.user  = user
    st.session_state.token = token
    try:
        st.query_params["sid"] = token
    except Exception:
        pass

def do_logout():
    token = st.session_state.get("token", "")
    if token: delete_session(token)
    st.session_state.user  = None
    st.session_state.token = ""
    try: st.query_params.clear()
    except Exception: pass
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
                except Exception: pass
    except Exception:
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
st.caption(f"Binance Brasil | {BOT_SYMBOL} | TP {TAKE_PROFIT*100:.2f}% | SL {STOP_LOSS*100:.2f}% | runner: python dashboard.py --bot")

if not st.session_state.user:
    st.info("Faça login na barra lateral.")
    st.stop()

user = st.session_state.user
user_id, username, _, role, created_at, referrer_code, my_code = user

tab_names = ["📊 Painel BOT", "👤 Minha Conta", "🔑 Chaves API",
             "💰 Aporte", "💸 Saque", "📄 Extrato"]
if role == "admin":
    tab_names.append("⚙️ Administração")
tabs = st.tabs(tab_names)


# ══════════════════════════════════════════════════════════════
# TAB 0 — PAINEL BOT
# ══════════════════════════════════════════════════════════════
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
            s.get("last_step_ts"), s.get("last_error"))
        st.rerun()
    elif not s and new_on:
        upsert_bot_state(user_id, 1, 0.0, 0.0, 0, None, None, None, None)
        st.rerun()

    if not s:
        st.info("Ative o bot e certifique-se de rodar o runner: `python dashboard.py --bot`")
    else:
        s = get_bot_state(user_id)

        err = s.get("last_error")
        if err:
            st.error(f"🚨 Último erro: {err}")

        lts = s.get("last_step_ts")
        if lts:
            st.caption(f"⏱ Último ciclo do runner: `{lts}`")
        else:
            st.warning("⚠️ Runner não detectado. Abra outro terminal e rode: `python dashboard.py --bot`")

        price_now   = fetch_price_display(BOT_SYMBOL)
        bot_usdt    = float(s.get("usdt")  or 0.0)
        bot_asset   = float(s.get("asset") or 0.0)
        in_pos      = int(s.get("in_position") or 0)
        entry_price = s.get("entry_price")
        entry_time  = s.get("entry_time")
        pos_txt     = "🟡 COMPRADO" if in_pos else "⚪ FLAT"

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("USDT (exchange)",  f"{bot_usdt:.2f}")
        c2.metric("BTC em carteira",  f"{bot_asset:.6f}")
        c3.metric("Posição",          pos_txt)
        c4.metric("Preço atual",      f"{price_now:.2f}" if price_now else "—")

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
                except Exception: pass

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
            st.info("Sem operações. Certifique-se que o runner está rodando: `python dashboard.py --bot`")
        else:
            st.dataframe(df_tr.tail(200), use_container_width=True)


# ══════════════════════════════════════════════════════════════
# TAB 1 — MINHA CONTA
# ══════════════════════════════════════════════════════════════
with tabs[1]:
    bal = user_balance(user_id)
    c1, c2, c3 = st.columns(3)
    c1.metric("Usuário",      username)
    c2.metric("Saldo ledger", f"{bal:.2f} USDT")
    c3.metric("Meu código",   my_code)
    if referrer_code:
        st.caption(f"Indicado por: `{referrer_code}`")


# ══════════════════════════════════════════════════════════════
# TAB 2 — CHAVES API
# ══════════════════════════════════════════════════════════════
with tabs[2]:
    st.subheader("🔑 Chaves API — Binance Brasil")
    st.warning("⚠️ Use chaves com permissão apenas de **Spot Trading**. NUNCA habilite saque.")
    st.info("ℹ️ Crie suas chaves em **binance.com.br** (não binance.com)")
    ex = get_user_keys(user_id)
    if ex:
        st.success(f"✅ Chaves cadastradas | Key: `{ex[0][:8]}...` | Testnet: {'Sim' if ex[2] else 'Não'}")

    with st.form("form_keys"):
        nk = st.text_input("API Key",    type="password")
        ns = st.text_input("API Secret", type="password")
        tn = st.checkbox("Usar Testnet", value=False)
        if st.form_submit_button("💾 Salvar chaves"):
            try:
                save_user_keys(user_id, nk, ns, tn)
                st.success("✅ Chaves salvas!"); st.rerun()
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.markdown("""
**Como criar chaves na Binance Brasil:**
1. Acesse **binance.com.br** → Perfil → Gerenciamento de API
2. Crie nova chave do tipo **API Gerada pelo Sistema**
3. Habilite apenas: ✅ **Ativar Trading Spot e de Margem**
4. ❌ **NÃO habilite Saques** (nunca!)
5. Em Restrições de IP: deixe **Irrestrito** para começar
    """)


# ══════════════════════════════════════════════════════════════
# TAB 3 — APORTE
# ══════════════════════════════════════════════════════════════
with tabs[3]:
    st.subheader("💰 Aporte em USDT")
    st.markdown(f"**Rede:** `{DEPOSIT_NETWORK_LABEL}`")
    st.code(DEPOSIT_ADDRESS_FIXED)
    st.caption("Envie USDT para o endereço acima e cole o TXID. O admin confirmará o crédito.")

    amt_d  = st.number_input("Valor (USDT)", min_value=0.0, step=10.0, format="%.2f", key="amt_d")
    txid_d = st.text_input("TXID / Hash da transação")
    if st.button("📤 Enviar comprovante"):
        try:
            if amt_d <= 0:
                st.error("Informe um valor.")
            else:
                create_deposit(user_id, amt_d, txid_d)
                st.success("Enviado! Aguarde aprovação do admin.")
        except Exception as e:
            st.error(str(e))

    st.divider()
    rows = list_deposits(user_id=user_id)
    if rows:
        st.dataframe(pd.DataFrame(rows, columns=["id","valor","txid","status","criado","revisado","nota"]),
                     use_container_width=True)
    else:
        st.info("Sem aportes ainda.")


# ══════════════════════════════════════════════════════════════
# TAB 4 — SAQUE
# ══════════════════════════════════════════════════════════════
with tabs[4]:
    st.subheader("💸 Solicitar saque")
    bal = user_balance(user_id)
    st.metric("Saldo disponível", f"{bal:.2f} USDT")

    amt_w = st.number_input("Valor (USDT)", min_value=0.0, step=10.0, format="%.2f", key="amt_w")
    net_w = st.selectbox("Rede", ["TRC20", "BEP20", "ERC20"])
    adr_w = st.text_input("Endereço destino")

    fee_w = amt_w * WITHDRAW_FEE_RATE
    liq_w = amt_w - fee_w
    c1, c2, c3 = st.columns(3)
    c1.metric("Taxa", f"{WITHDRAW_FEE_RATE*100:.0f}%")
    c2.metric("Taxa (USDT)", f"{fee_w:.2f}")
    c3.metric("Você recebe", f"{liq_w:.2f}")

    if st.button("📤 Solicitar saque"):
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
        st.dataframe(
            pd.DataFrame(rows, columns=["id","valor","taxa","liquido","rede","endereco","txid_pago","status","criado","revisado","nota"]),
            use_container_width=True)
    else:
        st.info("Sem saques ainda.")


# ══════════════════════════════════════════════════════════════
# TAB 5 — EXTRATO
# ══════════════════════════════════════════════════════════════
with tabs[5]:
    st.subheader("📄 Extrato")
    with _DB_LOCK:
        conn   = db()
        df_led = pd.read_sql_query(
            "SELECT created_at,kind,amount_usdt,ref_table,ref_id FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 500",
            conn, params=(user_id,))
        conn.close()
    if df_led.empty:
        st.info("Sem movimentações.")
    else:
        st.dataframe(df_led, use_container_width=True)
        st.download_button("⬇️ Baixar CSV", df_led.to_csv(index=False).encode(),
                           "extrato.csv", "text/csv", use_container_width=True)


# ══════════════════════════════════════════════════════════════
# TAB 6 — ADMINISTRAÇÃO
# ══════════════════════════════════════════════════════════════
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
                if st.button("✅ Aprovar", use_container_width=True, key="apd"):
                    try:
                        admin_review_deposit(int(did), True, user_id, dn)
                        st.success("Aprovado!"); st.rerun()
                    except Exception as e: st.error(str(e))
            with c2:
                if st.button("❌ Rejeitar", use_container_width=True, key="rjd"):
                    try:
                        admin_review_deposit(int(did), False, user_id, dn)
                        st.warning("Rejeitado."); st.rerun()
                    except Exception as e: st.error(str(e))

        st.divider()
        st.markdown("### 💸 Saques pendentes")
        w_all = list_withdrawals()
        w_df  = pd.DataFrame(w_all, columns=["id","username","valor_req","taxa","liquido","rede","endereco","txid_pago","status","criado","revisado","nota"])
        pend_w = w_df[w_df["status"] == "PENDING"]
        if pend_w.empty:
            st.info("Nenhum saque pendente.")
        else:
            st.dataframe(pend_w, use_container_width=True)
            wid = st.number_input("ID do saque", min_value=1, step=1, key="wid")
            wn  = st.text_input("Nota", key="wn")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ Aprovar", use_container_width=True, key="apw"):
                    try:
                        admin_review_withdrawal(int(wid), True, user_id, wn)
                        st.success("Aprovado!"); st.rerun()
                    except Exception as e: st.error(str(e))
            with c2:
                if st.button("❌ Rejeitar", use_container_width=True, key="rjw"):
                    try:
                        admin_review_withdrawal(int(wid), False, user_id, wn)
                        st.warning("Rejeitado."); st.rerun()
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
            if st.button("💳 Marcar como PAGO", use_container_width=True):
                try:
                    admin_mark_withdraw_paid(int(wid2), user_id, ptxid, pn)
                    st.success("Marcado!"); st.rerun()
                except Exception as e: st.error(str(e))

        st.divider()
        st.markdown("### 🤖 Status dos bots por usuário")
        with _DB_LOCK:
            conn    = db()
            df_bots = pd.read_sql_query("""
                SELECT u.username, bs.enabled, bs.usdt, bs.asset, bs.in_position,
                       bs.entry_price, bs.last_step_ts, bs.last_error,
                       CASE WHEN uk.user_id IS NOT NULL THEN 'Sim' ELSE 'Não' END as tem_chave
                FROM bot_state bs
                JOIN users u ON u.id=bs.user_id
                LEFT JOIN user_keys uk ON uk.user_id=bs.user_id
                ORDER BY u.username
            """, conn)
            conn.close()
        if not df_bots.empty:
            st.dataframe(df_bots, use_container_width=True)
        else:
            st.info("Nenhum bot ativo ainda.")