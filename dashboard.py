import sqlite3
import hashlib
from datetime import datetime
import pandas as pd
import streamlit as st

# autorefresh
try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except Exception:
    HAS_AUTOREFRESH = False

# ccxt (somente leitura pública para PAPER)
try:
    import ccxt
    HAS_CCXT = True
except Exception:
    HAS_CCXT = False


# =========================
# CONFIG GERAL
# =========================
DB_PATH = "mvp_funds.db"

WITHDRAW_FEE_RATE = 0.05  # 5%

DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "LU87347748"  # ideal: st.secrets

DEPOSIT_ADDRESS_FIXED = "0xBa4D5e87e8bcaA85bF29105AB3171b9fDb2eF9dd"
DEPOSIT_NETWORK_LABEL = "ERC20"

st.set_page_config(page_title="OBS PRO — BOT", layout="wide")


# =========================
# BOT PAPER CONFIG (AGRESSIVO)
# =========================
BOT_SYMBOL = "BTC/USDT"
BOT_TIMEFRAME = "5m"
BOT_LIMIT = 200

FEE_RATE_EST = 0.001
ORDER_USDT_FRAC = 1.00  # usa 100% do saldo do BOT (paper)

TAKE_PROFIT = 0.004     # +0.4%
STOP_LOSS = 0.003       # -0.3%

MIN_USDT_ORDER = 10.0

BOT_MIN_INTERVAL_SEC = 10  # roda 1 step a cada X segundos

# ✅ AGRESSIVO: vender assim que bater TP (sem esperar 60s)
MIN_HOLD_SECONDS_FOR_TP = 0


# =========================
# DB helpers
# =========================
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def make_code(username: str) -> str:
    return sha256(username + "|code")[:8]

def init_db():
    conn = db()
    cur = conn.cursor()

    # users
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        pass_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin','user')),
        created_at TEXT NOT NULL,
        referrer_code TEXT,
        my_code TEXT UNIQUE
    )
    """)

    # deposits
    cur.execute("""
    CREATE TABLE IF NOT EXISTS deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount_usdt REAL NOT NULL,
        txid TEXT,
        deposit_address TEXT,
        status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED')),
        created_at TEXT NOT NULL,
        reviewed_at TEXT,
        reviewed_by INTEGER,
        note TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # withdrawals
    cur.execute("""
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount_request_usdt REAL NOT NULL,
        fee_rate REAL NOT NULL,
        fee_usdt REAL NOT NULL,
        amount_net_usdt REAL NOT NULL,
        network TEXT,
        address TEXT,
        paid_txid TEXT,
        status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED','PAID')),
        created_at TEXT NOT NULL,
        reviewed_at TEXT,
        reviewed_by INTEGER,
        note TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # ledger
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('DEPOSIT','WITHDRAWAL','ADJUST')),
        amount_usdt REAL NOT NULL,
        ref_table TEXT,
        ref_id INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # bot_state (paper por usuário)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_state (
        user_id INTEGER PRIMARY KEY,
        enabled INTEGER NOT NULL DEFAULT 0,
        usdt REAL NOT NULL DEFAULT 0,
        asset REAL NOT NULL DEFAULT 0,
        in_position INTEGER NOT NULL DEFAULT 0,
        entry_price REAL,
        entry_qty REAL,
        entry_time TEXT,
        last_step_ts TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # bot_trades (paper por usuário)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        time TEXT NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
        price REAL NOT NULL,
        qty REAL NOT NULL,
        fee_usdt REAL NOT NULL,
        usdt_balance REAL NOT NULL,
        asset_balance REAL NOT NULL,
        reason TEXT,
        pnl_usdt REAL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    conn.commit()

    # cria admin default
    cur.execute("SELECT id FROM users WHERE username=?", (DEFAULT_ADMIN_USER,))
    if cur.fetchone() is None:
        cur.execute("""
            INSERT INTO users (username, pass_hash, role, created_at, referrer_code, my_code)
            VALUES (?,?,?,?,?,?)
        """, (
            DEFAULT_ADMIN_USER,
            sha256(DEFAULT_ADMIN_PASS),
            "admin",
            datetime.now().isoformat(sep=" ", timespec="seconds"),
            None,
            make_code(DEFAULT_ADMIN_USER),
        ))
        conn.commit()

    conn.close()

def get_user_by_username(username: str):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, username, pass_hash, role, created_at, referrer_code, my_code
        FROM users WHERE username=?
    """, (username,))
    row = cur.fetchone()
    conn.close()
    return row

def create_user(username: str, password: str, role: str, referrer_code: str | None):
    username = username.strip()
    if not username or not password:
        raise ValueError("Preencha usuário e senha.")

    conn = db()
    cur = conn.cursor()

    if referrer_code:
        cur.execute("SELECT id FROM users WHERE my_code=?", (referrer_code.strip(),))
        if cur.fetchone() is None:
            conn.close()
            raise ValueError("Código de indicação inválido.")

    my_code = make_code(username)
    cur.execute("""
        INSERT INTO users (username, pass_hash, role, created_at, referrer_code, my_code)
        VALUES (?,?,?,?,?,?)
    """, (
        username,
        sha256(password),
        role,
        datetime.now().isoformat(sep=" ", timespec="seconds"),
        referrer_code.strip() if referrer_code else None,
        my_code
    ))
    conn.commit()
    conn.close()

def auth(username: str, password: str):
    u = get_user_by_username(username.strip())
    if not u:
        return None
    if sha256(password) != u[2]:
        return None
    return u

def add_ledger(user_id: int, kind: str, amount_usdt: float, ref_table: str | None = None, ref_id: int | None = None):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ledger (user_id, kind, amount_usdt, ref_table, ref_id, created_at)
        VALUES (?,?,?,?,?,?)
    """, (user_id, kind, float(amount_usdt), ref_table, ref_id,
          datetime.now().isoformat(sep=" ", timespec="seconds")))
    conn.commit()
    conn.close()

def user_balance(user_id: int) -> float:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(amount_usdt), 0) FROM ledger WHERE user_id=?", (user_id,))
    bal = float(cur.fetchone()[0] or 0)
    conn.close()
    return bal


# =========================
# Deposits / Withdrawals
# =========================
def create_deposit(user_id: int, amount_usdt: float, txid: str):
    if not txid or not txid.strip():
        raise ValueError("TXID (hash) é obrigatório.")
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO deposits (user_id, amount_usdt, txid, deposit_address, status, created_at)
        VALUES (?,?,?,?,?,?)
    """, (user_id, float(amount_usdt), txid.strip(), DEPOSIT_ADDRESS_FIXED, "PENDING",
          datetime.now().isoformat(sep=" ", timespec="seconds")))
    conn.commit()
    conn.close()

def list_deposits(user_id: int | None = None):
    conn = db()
    cur = conn.cursor()
    if user_id is None:
        cur.execute("""
            SELECT d.id, u.username, d.amount_usdt, d.txid, d.deposit_address, d.status, d.created_at, d.reviewed_at, d.note
            FROM deposits d JOIN users u ON u.id=d.user_id
            ORDER BY d.id DESC
        """)
    else:
        cur.execute("""
            SELECT d.id, d.amount_usdt, d.txid, d.deposit_address, d.status, d.created_at, d.reviewed_at, d.note
            FROM deposits d
            WHERE d.user_id=?
            ORDER BY d.id DESC
        """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def admin_review_deposit(deposit_id: int, approve: bool, admin_id: int, note: str = ""):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id, amount_usdt, status FROM deposits WHERE id=?", (deposit_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise ValueError("Depósito não encontrado.")
    user_id, amt, status = row
    if status != "PENDING":
        conn.close()
        raise ValueError("Depósito já revisado.")

    new_status = "APPROVED" if approve else "REJECTED"
    cur.execute("""
        UPDATE deposits
        SET status=?, reviewed_at=?, reviewed_by=?, note=?
        WHERE id=?
    """, (new_status, datetime.now().isoformat(sep=" ", timespec="seconds"), admin_id, note, deposit_id))
    conn.commit()
    conn.close()

    if approve:
        add_ledger(user_id, "DEPOSIT", float(amt), ref_table="deposits", ref_id=deposit_id)

def create_withdrawal(user_id: int, amount_usdt: float, network: str, address: str):
    bal = user_balance(user_id)
    if amount_usdt <= 0:
        raise ValueError("Valor inválido.")
    if amount_usdt > bal:
        raise ValueError(f"Saldo insuficiente. Saldo atual: {bal:.2f} USDT")
    if not network.strip():
        raise ValueError("Rede é obrigatória.")
    if not address.strip():
        raise ValueError("Endereço é obrigatório.")

    fee = amount_usdt * WITHDRAW_FEE_RATE
    net = amount_usdt - fee

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO withdrawals
        (user_id, amount_request_usdt, fee_rate, fee_usdt, amount_net_usdt, network, address, status, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (user_id, float(amount_usdt), float(WITHDRAW_FEE_RATE), float(fee), float(net),
          network.strip(), address.strip(), "PENDING",
          datetime.now().isoformat(sep=" ", timespec="seconds")))
    conn.commit()
    conn.close()

def list_withdrawals(user_id: int | None = None):
    conn = db()
    cur = conn.cursor()
    if user_id is None:
        cur.execute("""
            SELECT w.id, u.username, w.amount_request_usdt, w.fee_usdt, w.amount_net_usdt,
                   w.network, w.address, w.paid_txid, w.status, w.created_at, w.reviewed_at, w.note
            FROM withdrawals w JOIN users u ON u.id=w.user_id
            ORDER BY w.id DESC
        """)
    else:
        cur.execute("""
            SELECT w.id, w.amount_request_usdt, w.fee_usdt, w.amount_net_usdt,
                   w.network, w.address, w.paid_txid, w.status, w.created_at, w.reviewed_at, w.note
            FROM withdrawals w
            WHERE w.user_id=?
            ORDER BY w.id DESC
        """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def admin_review_withdrawal(withdraw_id: int, approve: bool, admin_id: int, note: str = ""):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id, amount_request_usdt, status FROM withdrawals WHERE id=?", (withdraw_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise ValueError("Saque não encontrado.")
    user_id, amt, status = row
    if status != "PENDING":
        conn.close()
        raise ValueError("Saque já revisado.")

    new_status = "APPROVED" if approve else "REJECTED"
    cur.execute("""
        UPDATE withdrawals
        SET status=?, reviewed_at=?, reviewed_by=?, note=?
        WHERE id=?
    """, (new_status, datetime.now().isoformat(sep=" ", timespec="seconds"), admin_id, note, withdraw_id))
    conn.commit()
    conn.close()

    if approve:
        add_ledger(user_id, "WITHDRAWAL", -float(amt), ref_table="withdrawals", ref_id=withdraw_id)

def admin_mark_withdraw_paid(withdraw_id: int, admin_id: int, paid_txid: str, note: str = ""):
    if not paid_txid.strip():
        raise ValueError("TXID do pagamento é obrigatório.")
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT status FROM withdrawals WHERE id=?", (withdraw_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise ValueError("Saque não encontrado.")
    if row[0] != "APPROVED":
        conn.close()
        raise ValueError("Precisa estar APPROVED para marcar como PAID.")
    cur.execute("""
        UPDATE withdrawals
        SET status='PAID', paid_txid=?, reviewed_at=?, reviewed_by=?, note=?
        WHERE id=?
    """, (paid_txid.strip(), datetime.now().isoformat(sep=" ", timespec="seconds"), admin_id, note, withdraw_id))
    conn.commit()
    conn.close()


# =========================
# BOT HELPERS (Paper)
# =========================
def get_bot_state(user_id: int) -> dict:
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, enabled, usdt, asset, in_position, entry_price, entry_qty, entry_time, last_step_ts, updated_at
        FROM bot_state WHERE user_id=?
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {}
    keys = ["user_id","enabled","usdt","asset","in_position","entry_price","entry_qty","entry_time","last_step_ts","updated_at"]
    return dict(zip(keys, row))

def upsert_bot_state(user_id: int, enabled: int, usdt: float, asset: float,
                     in_position: int, entry_price, entry_qty, entry_time, last_step_ts):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM bot_state WHERE user_id=?", (user_id,))
    exists = cur.fetchone() is not None
    now = datetime.now().isoformat(sep=" ", timespec="seconds")

    if exists:
        cur.execute("""
            UPDATE bot_state
            SET enabled=?, usdt=?, asset=?, in_position=?, entry_price=?, entry_qty=?, entry_time=?, last_step_ts=?, updated_at=?
            WHERE user_id=?
        """, (enabled, float(usdt), float(asset), int(in_position),
              entry_price, entry_qty, entry_time, last_step_ts, now, user_id))
    else:
        cur.execute("""
            INSERT INTO bot_state (user_id, enabled, usdt, asset, in_position, entry_price, entry_qty, entry_time, last_step_ts, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (user_id, enabled, float(usdt), float(asset), int(in_position),
              entry_price, entry_qty, entry_time, last_step_ts, now))
    conn.commit()
    conn.close()

def insert_bot_trade(user_id: int, side: str, price: float, qty: float, fee_usdt: float,
                     usdt_balance: float, asset_balance: float, reason: str, pnl_usdt):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO bot_trades
        (user_id, time, symbol, side, price, qty, fee_usdt, usdt_balance, asset_balance, reason, pnl_usdt)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        user_id,
        datetime.now().isoformat(sep=" ", timespec="seconds"),
        BOT_SYMBOL, side, float(price), float(qty), float(fee_usdt),
        float(usdt_balance), float(asset_balance), reason, pnl_usdt
    ))
    conn.commit()
    conn.close()

def load_bot_trades(user_id: int, limit: int = 300) -> pd.DataFrame:
    conn = db()
    df = pd.read_sql_query("""
        SELECT time, symbol, side, price, qty, fee_usdt, usdt_balance, asset_balance, reason, pnl_usdt
        FROM bot_trades
        WHERE user_id=?
        ORDER BY time DESC
        LIMIT ?
    """, conn, params=(user_id, limit))
    conn.close()
    if not df.empty:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.sort_values("time").reset_index(drop=True)
    return df

def compute_metrics_from_trades(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"sells": 0, "wins": 0, "losses": 0, "winrate": 0.0, "pnl": 0.0}
    sells = df[df["side"].astype(str).str.upper() == "SELL"].copy()
    sells["pnl_usdt"] = pd.to_numeric(sells["pnl_usdt"], errors="coerce")
    wins = int((sells["pnl_usdt"] > 0).sum()) if not sells.empty else 0
    losses = int((sells["pnl_usdt"] < 0).sum()) if not sells.empty else 0
    total = wins + losses
    winrate = (wins / total * 100.0) if total else 0.0
    pnl = float(sells["pnl_usdt"].sum()) if not sells.empty else 0.0
    return {"sells": total, "wins": wins, "losses": losses, "winrate": winrate, "pnl": pnl}

def build_exchange_public():
    if not HAS_CCXT:
        return None
    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    ex.load_markets()
    return ex

@st.cache_resource
def get_exchange():
    return build_exchange_public()

def fetch_price(ex, symbol: str) -> float | None:
    try:
        t = ex.fetch_ticker(symbol)
        return float(t["last"])
    except Exception:
        return None

def maybe_auto_sync_bot_cash_when_flat(user_id: int, ledger_balance: float):
    """
    Quando estiver FLAT (sem posição), banca do BOT acompanha o saldo do ledger automaticamente.
    """
    s = get_bot_state(user_id)
    if not s:
        upsert_bot_state(
            user_id=user_id,
            enabled=0,
            usdt=float(ledger_balance),
            asset=0.0,
            in_position=0,
            entry_price=None,
            entry_qty=None,
            entry_time=None,
            last_step_ts=None
        )
        return

    if int(s.get("in_position") or 0) == 0:
        upsert_bot_state(
            user_id=user_id,
            enabled=int(s.get("enabled") or 0),
            usdt=float(ledger_balance),
            asset=0.0,
            in_position=0,
            entry_price=None,
            entry_qty=None,
            entry_time=None,
            last_step_ts=s.get("last_step_ts")
        )

def bot_step_agressivo(user_id: int) -> str:
    """
    ✅ AGRESSIVO:
    - Se FLAT e tiver saldo >= MIN_USDT_ORDER: COMPRA
    - Se COMPRADO: vende por TP/SL
    """
    if not HAS_CCXT:
        return "Instale ccxt para pegar preço real (PAPER)."

    ex = get_exchange()
    if ex is None:
        return "Falha ao iniciar exchange (ccxt)."

    s = get_bot_state(user_id)
    if not s:
        return "Sem estado do BOT. Recarregue."

    enabled = int(s.get("enabled") or 0)
    if enabled != 1:
        return "Bot desligado."

    now = datetime.now()

    # limitador de frequência
    last_ts = s.get("last_step_ts")
    if last_ts:
        try:
            last_dt = datetime.fromisoformat(last_ts)
            if (now - last_dt).total_seconds() < BOT_MIN_INTERVAL_SEC:
                return "Aguardando intervalo mínimo..."
        except Exception:
            pass

    usdt = float(s.get("usdt") or 0.0)
    asset = float(s.get("asset") or 0.0)
    in_pos = int(s.get("in_position") or 0)
    entry_price = s.get("entry_price")
    entry_qty = s.get("entry_qty")
    entry_time = s.get("entry_time")

    price = fetch_price(ex, BOT_SYMBOL)
    if price is None:
        upsert_bot_state(user_id, enabled, usdt, asset, in_pos, entry_price, entry_qty, entry_time,
                         now.isoformat(sep=" ", timespec="seconds"))
        return "Sem preço agora (falha ticker)."

    # =========================
    # BUY (COMPRA SEM SINAL: SEM RSI/TREND)
    # =========================
    if in_pos == 0:
        if usdt < MIN_USDT_ORDER:
            upsert_bot_state(user_id, enabled, usdt, 0.0, 0, None, None, None,
                             now.isoformat(sep=" ", timespec="seconds"))
            return f"Saldo do BOT baixo: {usdt:.2f} USDT"

        buy_usdt = usdt * ORDER_USDT_FRAC
        fee = buy_usdt * FEE_RATE_EST
        net = buy_usdt - fee
        qty = net / price

        usdt2 = usdt - buy_usdt
        asset2 = qty

        upsert_bot_state(
            user_id=user_id,
            enabled=enabled,
            usdt=usdt2,
            asset=asset2,
            in_position=1,
            entry_price=price,
            entry_qty=qty,
            entry_time=now.isoformat(sep=" ", timespec="seconds"),
            last_step_ts=now.isoformat(sep=" ", timespec="seconds")
        )
        insert_bot_trade(
            user_id=user_id,
            side="BUY",
            price=price,
            qty=qty,
            fee_usdt=fee,
            usdt_balance=usdt2,
            asset_balance=asset2,
            reason="BUY_AGRESSIVO (sem RSI/Trend)",
            pnl_usdt=None
        )
        return f"BUY @ {price:.2f} | qty={qty:.8f}"

    # =========================
    # SELL
    # =========================
    if in_pos == 1 and entry_price is not None and entry_qty is not None and float(entry_qty) > 0:
        entry_price = float(entry_price)
        entry_qty = float(entry_qty)

        tp_price = entry_price * (1 + TAKE_PROFIT)
        sl_price = entry_price * (1 - STOP_LOSS)

        held_ok = True
        if entry_time:
            try:
                et = datetime.fromisoformat(entry_time)
                held_ok = (now - et).total_seconds() >= MIN_HOLD_SECONDS_FOR_TP
            except Exception:
                held_ok = True

        exit_reason = None
        if held_ok and price >= tp_price:
            exit_reason = "TAKE_PROFIT"
        elif price <= sl_price:
            exit_reason = "STOP_LOSS"

        if exit_reason:
            gross = asset * price
            fee = gross * FEE_RATE_EST
            net = gross - fee

            entry_cost = entry_price * entry_qty
            pnl = net - entry_cost

            usdt2 = usdt + net
            asset2 = 0.0

            upsert_bot_state(
                user_id=user_id,
                enabled=enabled,
                usdt=usdt2,
                asset=asset2,
                in_position=0,
                entry_price=None,
                entry_qty=None,
                entry_time=None,
                last_step_ts=now.isoformat(sep=" ", timespec="seconds")
            )
            insert_bot_trade(
                user_id=user_id,
                side="SELL",
                price=price,
                qty=entry_qty,
                fee_usdt=fee,
                usdt_balance=usdt2,
                asset_balance=asset2,
                reason=exit_reason,
                pnl_usdt=pnl
            )
            return f"SELL ({exit_reason}) @ {price:.2f} | pnl={pnl:.4f} USDT"

    upsert_bot_state(user_id, enabled, usdt, asset, in_pos, entry_price, entry_qty, entry_time,
                     now.isoformat(sep=" ", timespec="seconds"))
    return "Em posição (aguardando TP/SL)."


# =========================
# UI
# =========================
init_db()

if "user" not in st.session_state:
    st.session_state.user = None

def logout():
    st.session_state.user = None
    st.rerun()

with st.sidebar:
    st.header("🔐 Login")
    if st.session_state.user:
        st.success(f"Logado: {st.session_state.user[1]} ({st.session_state.user[3]})")
        if st.button("Sair"):
            logout()
    else:
        u = st.text_input("Usuário", key="login_user")
        p = st.text_input("Senha", type="password", key="login_pass")
        if st.button("Entrar"):
            user = auth(u, p)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Usuário/senha inválidos.")

    st.divider()
    st.header("🧾 Cadastro")
    new_u = st.text_input("Novo usuário", key="reg_user")
    new_p = st.text_input("Nova senha", type="password", key="reg_pass")
    ref_code = st.text_input("Código de indicação (opcional)", key="reg_ref", placeholder="ex: a1b2c3d4")
    if st.button("Criar conta"):
        try:
            create_user(new_u, new_p, role="user", referrer_code=ref_code if ref_code else None)
            st.success("Conta criada! Faça login.")
        except Exception as e:
            st.error(str(e))

    st.divider()
    st.caption("🔁 Atualização")
    auto_refresh = st.checkbox("Auto atualizar", value=True)
    refresh_sec = st.slider("Intervalo (seg)", 2, 60, 10)
    if auto_refresh and HAS_AUTOREFRESH:
        st_autorefresh(interval=refresh_sec * 1000, key="ar_key")
    elif auto_refresh and not HAS_AUTOREFRESH:
        st.warning("Instale: streamlit-autorefresh")

st.title("OBS PRO — BOT")

if not st.session_state.user:
    st.info("Faça login (barra lateral) para acessar o painel completo.")
    st.stop()

user = st.session_state.user
user_id, username, _, role, created_at, referrer_code, my_code = user

tabs = st.tabs(
    ["Painel BOT", "Minha Conta", "Aporte USDT", "Saque", "Extrato"]
    + (["Administração", "Configuração"] if role == "admin" else [])
)

# =========================
# TAB 0: Painel BOT (corretora)
# =========================
with tabs[0]:
    ledger_bal = user_balance(user_id)
    maybe_auto_sync_bot_cash_when_flat(user_id, ledger_bal)

    s = get_bot_state(user_id)
    if not s:
        st.warning("Estado do BOT ainda não foi criado. Recarregue a página.")
        st.stop()

    col1, col2 = st.columns([1, 2])
    with col1:
        enabled_ui = st.toggle("Operar (PAPER)", value=bool(int(s.get("enabled") or 0)))
    with col2:
        st.caption(f"✅ TP {TAKE_PROFIT*100:.1f}% | SL {STOP_LOSS*100:.1f}% | step {BOT_MIN_INTERVAL_SEC}s | hold {MIN_HOLD_SECONDS_FOR_TP}s")

    if int(s.get("enabled") or 0) != int(enabled_ui):
        upsert_bot_state(
            user_id=user_id,
            enabled=int(enabled_ui),
            usdt=float(s.get("usdt") or 0.0),
            asset=float(s.get("asset") or 0.0),
            in_position=int(s.get("in_position") or 0),
            entry_price=s.get("entry_price"),
            entry_qty=s.get("entry_qty"),
            entry_time=s.get("entry_time"),
            last_step_ts=s.get("last_step_ts")
        )
        s = get_bot_state(user_id)

    # roda 1 step por refresh
    status_msg = bot_step_agressivo(user_id) if int(s.get("enabled") or 0) == 1 else "Bot desligado."
    s = get_bot_state(user_id)

    # preço atual
    price_now = None
    if HAS_CCXT:
        try:
            ex = get_exchange()
            price_now = fetch_price(ex, BOT_SYMBOL)
        except Exception:
            price_now = None

    ledger_bal = user_balance(user_id)
    bot_usdt = float(s.get("usdt") or 0.0)
    bot_asset = float(s.get("asset") or 0.0)
    in_pos = int(s.get("in_position") or 0)
    entry_price = s.get("entry_price")
    entry_time = s.get("entry_time")

    pos_txt = "COMPRADO" if in_pos == 1 else "FLAT"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Saldo (Livro-caixa)", f"{ledger_bal:.2f} USDT")
    c2.metric("Banca do BOT (PAPER)", f"{bot_usdt:.2f} USDT")
    c3.metric("Ativo (BTC)", f"{bot_asset:.6f}")
    c4.metric("Posição", pos_txt)

    st.caption(status_msg)

    st.divider()
    a, b, c, d, e = st.columns(5)

    a.metric("Preço atual", f"{price_now:.2f}" if price_now is not None else "—")

    if in_pos == 1 and entry_price:
        entry_price = float(entry_price)
        tp_price = entry_price * (1 + TAKE_PROFIT)
        sl_price = entry_price * (1 - STOP_LOSS)
        b.metric("Entrada", f"{entry_price:.2f}")
        c.metric("TP", f"{tp_price:.2f}")
        d.metric("SL", f"{sl_price:.2f}")
        if price_now is not None:
            pnl_pct = (price_now / entry_price - 1) * 100.0
            e.metric("Lucro atual (%)", f"{pnl_pct:.3f}%")
        else:
            e.metric("Lucro atual (%)", "—")

        if entry_time:
            try:
                et = datetime.fromisoformat(entry_time)
                secs = int((datetime.now() - et).total_seconds())
                st.caption(f"⏱️ Tempo em posição: {secs}s")
            except Exception:
                pass
    else:
        b.metric("Entrada", "—")
        c.metric("TP", "—")
        d.metric("SL", "—")
        e.metric("Lucro atual (%)", "—")

    st.divider()

    df_tr = load_bot_trades(user_id, limit=500)
    m = compute_metrics_from_trades(df_tr)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("VENDAS", f"{m['sells']}")
    m2.metric("Winrate", f"{m['winrate']:.1f}%")
    m3.metric("PnL Realizado", f"{m['pnl']:.4f} USDT")

    last_bot = None
    if not df_tr.empty and "usdt_balance" in df_tr.columns:
        last_bot = df_tr["usdt_balance"].dropna().iloc[-1] if df_tr["usdt_balance"].notna().any() else None
    m4.metric("Último saldo (BOT)", f"{float(last_bot):.4f}" if last_bot is not None else "—")

    st.subheader("Últimas trocas")
    if df_tr.empty:
        st.info("Sem operações ainda.")
    else:
        st.dataframe(df_tr.tail(300), width="stretch")


# TAB 1: Minha conta
with tabs[1]:
    bal = user_balance(user_id)
    c1, c2, c3 = st.columns(3)
    c1.metric("Usuário", username)
    c2.metric("Saldo (USDT)", f"{bal:.2f}")
    c3.metric("Meu código", my_code)
    if referrer_code:
        st.caption(f"Indicado por: `{referrer_code}`")

# TAB 2: Aporte
with tabs[2]:
    st.subheader("Aporte em USDT (TXID obrigatório)")
    st.caption("Envie para o endereço abaixo e cole o TXID para o admin confirmar.")
    st.markdown(f"**Rede do depósito:** `{DEPOSIT_NETWORK_LABEL}`")
    st.code(DEPOSIT_ADDRESS_FIXED, language="text")

    amount = st.number_input("Valor (USDT)", min_value=0.0, step=10.0, format="%.2f")
    txid = st.text_input("TXID / Hash da transação (obrigatório)")

    if st.button("Enviar comprovante de aporte"):
        try:
            if amount <= 0:
                st.error("Informe um valor.")
            elif not txid.strip():
                st.error("Cole o TXID (hash). Obrigatório.")
            else:
                create_deposit(user_id, amount, txid)
                st.success("Aporte criado como PENDENTE. Aguarde aprovação do admin.")
        except Exception as e:
            st.error(str(e))

    st.divider()
    st.write("Meus aportes:")
    rows = list_deposits(user_id=user_id)
    if rows:
        df_dep = pd.DataFrame(rows, columns=["id","amount_usdt","txid","deposit_address","status","created_at","reviewed_at","note"])
        st.dataframe(df_dep, width="stretch")
    else:
        st.info("Sem aportes ainda.")

# TAB 3: Saque
with tabs[3]:
    st.subheader("Solicitar saque")
    bal = user_balance(user_id)
    st.metric("Saldo (USDT)", f"{bal:.2f}")

    amount_w = st.number_input("Valor para sacar (USDT)", min_value=0.0, step=10.0, format="%.2f")
    network = st.selectbox("Rede", ["TRC20", "BEP20", "ERC20"], index=0)
    address = st.text_input("Endereço USDT (obrigatório)")

    fee = amount_w * WITHDRAW_FEE_RATE
    net = amount_w - fee
    c1, c2, c3 = st.columns(3)
    c1.metric("Taxa", f"{WITHDRAW_FEE_RATE*100:.0f}%")
    c2.metric("Taxa (USDT)", f"{fee:.2f}")
    c3.metric("Você recebe (líquido)", f"{net:.2f}")

    if st.button("Enviar solicitação de saque"):
        try:
            if amount_w <= 0:
                st.error("Informe um valor.")
            elif not address.strip():
                st.error("Informe o endereço. Obrigatório.")
            else:
                create_withdrawal(user_id, amount_w, network, address)
                st.success("Saque criado como PENDENTE. Aguarde aprovação do admin.")
        except Exception as e:
            st.error(str(e))

    st.divider()
    st.write("Meus saques:")
    rows = list_withdrawals(user_id=user_id)
    if rows:
        df_w = pd.DataFrame(rows, columns=["id","amount_req","fee","net","network","address","paid_txid","status","created_at","reviewed_at","note"])
        st.dataframe(df_w, width="stretch")
    else:
        st.info("Sem saques ainda.")

# TAB 4: Extrato
with tabs[4]:
    st.subheader("Extrato (ledger)")
    conn = db()
    df_led = pd.read_sql_query("""
        SELECT created_at, kind, amount_usdt, ref_table, ref_id
        FROM ledger
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 500
    """, conn, params=(user_id,))
    conn.close()

    if df_led.empty:
        st.info("Sem movimentações ainda.")
    else:
        st.dataframe(df_led, width="stretch")
        st.download_button(
            "Baixar extrato CSV",
            data=df_led.to_csv(index=False).encode("utf-8"),
            file_name="extrato.csv",
            mime="text/csv",
            use_container_width=True
        )

# Admin / Config
if role == "admin":
    with tabs[5]:
        st.subheader("Administração")

        st.markdown("## Aportes pendentes")
        dep_all = list_deposits(user_id=None)
        dep_df = pd.DataFrame(dep_all, columns=["id","username","amount_usdt","txid","deposit_address","status","created_at","reviewed_at","note"])
        pending_dep = dep_df[dep_df["status"] == "PENDING"].copy()

        if pending_dep.empty:
            st.info("Sem aportes pendentes.")
        else:
            st.dataframe(pending_dep, width="stretch")
            dep_id = st.number_input("ID do depósito", min_value=1, step=1, key="dep_id")
            dep_note = st.text_input("Nota (opcional)", key="dep_note")

            c1, c2 = st.columns(2)
            with c1:
                if st.button("Aprovar depósito", use_container_width=True):
                    try:
                        admin_review_deposit(int(dep_id), True, admin_id=user_id, note=dep_note)
                        st.success("Depósito aprovado e saldo creditado.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with c2:
                if st.button("Rejeitar depósito", use_container_width=True):
                    try:
                        admin_review_deposit(int(dep_id), False, admin_id=user_id, note=dep_note)
                        st.warning("Depósito rejeitado.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

        st.divider()
        st.markdown("## Saques pendentes")
        w_all = list_withdrawals(user_id=None)
        w_df = pd.DataFrame(w_all, columns=["id","username","amount_req","fee","net","network","address","paid_txid","status","created_at","reviewed_at","note"])
        pending_w = w_df[w_df["status"] == "PENDING"].copy()

        if pending_w.empty:
            st.info("Sem saques pendentes.")
        else:
            st.dataframe(pending_w, width="stretch")
            wid = st.number_input("ID do saque", min_value=1, step=1, key="wid")
            w_note = st.text_input("Nota (opcional)", key="w_note")

            c1, c2 = st.columns(2)
            with c1:
                if st.button("Aprovar saque", use_container_width=True):
                    try:
                        admin_review_withdrawal(int(wid), True, admin_id=user_id, note=w_note)
                        st.success("Saque aprovado e saldo descontado.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with c2:
                if st.button("Rejeitar saque", use_container_width=True):
                    try:
                        admin_review_withdrawal(int(wid), False, admin_id=user_id, note=w_note)
                        st.warning("Saque rejeitado.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

        st.divider()
        st.markdown("## Marcar saque como PAGO")
        approved_w = w_df[w_df["status"] == "APPROVED"].copy()
        if approved_w.empty:
            st.info("Sem saques aprovados aguardando pagamento.")
        else:
            st.dataframe(approved_w, width="stretch")
            wid2 = st.number_input("ID do saque aprovado", min_value=1, step=1, key="wid2")
            paid_txid = st.text_input("TXID do pagamento (obrigatório)", key="paid_txid")
            paid_note = st.text_input("Nota (opcional)", key="paid_note")

            if st.button("Marcar como PAGO", use_container_width=True):
                try:
                    admin_mark_withdraw_paid(int(wid2), admin_id=user_id, paid_txid=paid_txid, note=paid_note)
                    st.success("Saque marcado como PAGO e TXID registrado.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    with tabs[6]:
        st.subheader("Configuração")
        st.code("pip install -r requirements.txt\nstreamlit run app.py", language="bash")
        st.markdown("### Paper TP/SL")
        st.code(
            f"TP={TAKE_PROFIT*100:.1f}% | SL={STOP_LOSS*100:.1f}% | STEP={BOT_MIN_INTERVAL_SEC}s | HOLD={MIN_HOLD_SECONDS_FOR_TP}s",
            language="text"
        )
