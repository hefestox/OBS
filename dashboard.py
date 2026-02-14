import os
import sqlite3
import hashlib
from datetime import datetime
import pandas as pd
import streamlit as st

# (opcional) autorefresh
try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except Exception:
    HAS_AUTOREFRESH = False


# =========================
# CONFIG
# =========================
DB_PATH = "mvp_funds.db"
TRADES_CSV_DEFAULT = "paper_trades.csv"
WITHDRAW_FEE_RATE = 0.05  # 5%
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "admin123"  # troque depois

st.set_page_config(page_title="BOT + Wallet PRO", layout="wide")


# =========================
# DB
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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount_usdt REAL NOT NULL,
        txid TEXT,
        status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED')),
        created_at TEXT NOT NULL,
        reviewed_at TEXT,
        reviewed_by INTEGER,
        note TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount_request_usdt REAL NOT NULL,
        fee_rate REAL NOT NULL,
        fee_usdt REAL NOT NULL,
        amount_net_usdt REAL NOT NULL,
        address TEXT,
        status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED','PAID')),
        created_at TEXT NOT NULL,
        reviewed_at TEXT,
        reviewed_by INTEGER,
        note TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

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

    conn.commit()

    # cria admin default se não existir
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
            make_code(DEFAULT_ADMIN_USER)
        ))
        conn.commit()

    conn.close()

def get_user_by_username(username: str):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, pass_hash, role, created_at, referrer_code, my_code FROM users WHERE username=?", (username,))
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

# ----- Deposits
def create_deposit(user_id: int, amount_usdt: float, txid: str):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO deposits (user_id, amount_usdt, txid, status, created_at)
        VALUES (?,?,?,?,?)
    """, (user_id, float(amount_usdt), txid.strip() if txid else None, "PENDING",
          datetime.now().isoformat(sep=" ", timespec="seconds")))
    conn.commit()
    conn.close()

def list_deposits(user_id: int | None = None):
    conn = db()
    cur = conn.cursor()
    if user_id is None:
        cur.execute("""
            SELECT d.id, u.username, d.amount_usdt, d.txid, d.status, d.created_at, d.reviewed_at, d.note
            FROM deposits d JOIN users u ON u.id=d.user_id
            ORDER BY d.id DESC
        """)
    else:
        cur.execute("""
            SELECT d.id, d.amount_usdt, d.txid, d.status, d.created_at, d.reviewed_at, d.note
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

# ----- Withdrawals
def create_withdrawal(user_id: int, amount_usdt: float, address: str):
    bal = user_balance(user_id)
    if amount_usdt <= 0:
        raise ValueError("Valor inválido.")
    if amount_usdt > bal:
        raise ValueError(f"Saldo insuficiente. Saldo atual: {bal:.2f} USDT")

    fee = amount_usdt * WITHDRAW_FEE_RATE
    net = amount_usdt - fee

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO withdrawals
        (user_id, amount_request_usdt, fee_rate, fee_usdt, amount_net_usdt, address, status, created_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, (user_id, float(amount_usdt), float(WITHDRAW_FEE_RATE), float(fee), float(net),
          address.strip(), "PENDING", datetime.now().isoformat(sep=" ", timespec="seconds")))
    conn.commit()
    conn.close()

def list_withdrawals(user_id: int | None = None):
    conn = db()
    cur = conn.cursor()
    if user_id is None:
        cur.execute("""
            SELECT w.id, u.username, w.amount_request_usdt, w.fee_usdt, w.amount_net_usdt,
                   w.address, w.status, w.created_at, w.reviewed_at, w.note
            FROM withdrawals w JOIN users u ON u.id=w.user_id
            ORDER BY w.id DESC
        """)
    else:
        cur.execute("""
            SELECT w.id, w.amount_request_usdt, w.fee_usdt, w.amount_net_usdt,
                   w.address, w.status, w.created_at, w.reviewed_at, w.note
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
        # desconta saldo (reserva) na aprovação
        add_ledger(user_id, "WITHDRAWAL", -float(amt), ref_table="withdrawals", ref_id=withdraw_id)

def admin_mark_withdraw_paid(withdraw_id: int, admin_id: int, note: str = ""):
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
        SET status='PAID', reviewed_at=?, reviewed_by=?, note=?
        WHERE id=?
    """, (datetime.now().isoformat(sep=" ", timespec="seconds"), admin_id, note, withdraw_id))
    conn.commit()
    conn.close()


# =========================
# BOT DASHBOARD (CSV)
# =========================
@st.cache_data(ttl=2)
def load_trades_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()

    df = pd.read_csv(path)

    expected = [
        "time", "symbol", "side", "price", "qty", "fee_usdt",
        "usdt_balance", "asset_balance", "reason", "pnl_usdt"
    ]
    for c in expected:
        if c not in df.columns:
            df[c] = None

    df["time"] = pd.to_datetime(df["time"], errors="coerce")

    for c in ["price", "qty", "fee_usdt", "usdt_balance", "asset_balance", "pnl_usdt"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.sort_values("time").reset_index(drop=True)
    return df

def compute_bot_metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return dict(total=0, wins=0, losses=0, winrate=0.0, pnl=0.0)

    sells = df[df["side"].astype(str).str.upper() == "SELL"].copy()
    sells["pnl_usdt"] = pd.to_numeric(sells["pnl_usdt"], errors="coerce")

    wins = int((sells["pnl_usdt"] > 0).sum()) if not sells.empty else 0
    losses = int((sells["pnl_usdt"] < 0).sum()) if not sells.empty else 0
    total = wins + losses
    winrate = (wins / total * 100.0) if total else 0.0
    pnl = float(sells["pnl_usdt"].sum()) if not sells.empty else 0.0
    return dict(total=total, wins=wins, losses=losses, winrate=winrate, pnl=pnl)

def build_equity(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["time", "equity"])

    d = df.dropna(subset=["time"]).copy()

    # se tiver usdt_balance, usa como equity
    if d["usdt_balance"].notna().sum() >= 2:
        eq = d[["time", "usdt_balance"]].dropna().rename(columns={"usdt_balance": "equity"})
        return eq

    sells = d[d["side"].astype(str).str.upper() == "SELL"].copy()
    sells["pnl_usdt"] = pd.to_numeric(sells["pnl_usdt"], errors="coerce").fillna(0.0)
    sells["equity"] = sells["pnl_usdt"].cumsum()
    return sells[["time", "equity"]]

def build_drawdown(eq: pd.DataFrame) -> pd.DataFrame:
    if eq.empty:
        return pd.DataFrame(columns=["time", "drawdown"])
    x = eq.copy()
    x["peak"] = x["equity"].cummax()
    x["drawdown"] = x["equity"] - x["peak"]
    return x[["time", "drawdown"]]


# =========================
# UI: AUTH
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
    st.caption("⚙️ BOT/CSV")
    trades_csv = st.text_input("Caminho do CSV", value=TRADES_CSV_DEFAULT)
    auto_refresh = st.checkbox("Auto atualizar", value=True)
    refresh_sec = st.slider("Intervalo (seg)", 2, 60, 10)
    if auto_refresh and HAS_AUTOREFRESH:
        st_autorefresh(interval=refresh_sec * 1000, key="ar_key")
    elif auto_refresh and not HAS_AUTOREFRESH:
        st.warning("Instale: pip install streamlit-autorefresh")


st.title("🧩 Plataforma PRO — BOT + Usuários + Aporte + Saque")

if not st.session_state.user:
    st.info("Faça login (barra lateral) para acessar o painel completo.")
    st.stop()

user = st.session_state.user
user_id, username, _, role, created_at, referrer_code, my_code = user

# Tabs principais
tabs = st.tabs([
    "📊 BOT Dashboard",
    "👤 Minha Conta",
    "➕ Aporte USDT",
    "🏧 Saque",
    "📜 Extrato",
] + (["🛡️ Admin"] if role == "admin" else []) + ["⚙️ Config"])

# =========================
# TAB: BOT Dashboard
# =========================
with tabs[0]:
    df = load_trades_csv(trades_csv)

    colA, colB = st.columns([1, 1])
    with colA:
        if st.button("🔄 Atualizar agora", use_container_width=True):
            load_trades_csv.clear()
            st.rerun()
    with colB:
        st.caption("⚠️ O BOT roda separado e gera o CSV. O painel só lê.")

    if df.empty:
        st.warning("Não encontrei o CSV de trades. Verifique o caminho na barra lateral.")
        st.stop()

    m = compute_bot_metrics(df)
    eq = build_equity(df)
    dd = build_drawdown(eq)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SELLs", f"{m['total']}")
    c2.metric("Winrate", f"{m['winrate']:.1f}%")
    c3.metric("PnL Realizado", f"{m['pnl']:.4f} USDT")
    last_usdt = df["usdt_balance"].dropna().iloc[-1] if df["usdt_balance"].notna().any() else None
    c4.metric("Último saldo (USDT)", f"{float(last_usdt):.4f}" if last_usdt is not None else "—")

    left, right = st.columns(2)
    with left:
        st.subheader("📈 Equity")
        st.line_chart(eq.set_index("time")["equity"])
    with right:
        st.subheader("📉 Drawdown")
        if not dd.empty:
            st.line_chart(dd.set_index("time")["drawdown"])
        else:
            st.info("Sem dados suficientes para drawdown.")

    st.subheader("🧾 Últimos trades")
    st.dataframe(df.tail(200), width="stretch")

# =========================
# TAB: Minha Conta
# =========================
with tabs[1]:
    bal = user_balance(user_id)
    c1, c2, c3 = st.columns(3)
    c1.metric("Usuário", username)
    c2.metric("Saldo (USDT)", f"{bal:.2f}")
    c3.metric("Meu código", my_code)
    if referrer_code:
        st.caption(f"Indicado por: `{referrer_code}`")
    st.info("Este módulo é para fluxo: cadastro → aporte → aprovação → saldo → saque (com taxa).")

# =========================
# TAB: Aporte
# =========================
with tabs[2]:
    st.subheader("➕ Aporte em USDT (Pendente → Admin aprova)")
    amount = st.number_input("Valor (USDT)", min_value=0.0, step=10.0, format="%.2f")
    txid = st.text_input("TXID/Hash (opcional)")

    if st.button("Enviar aporte"):
        try:
            if amount <= 0:
                st.error("Informe um valor.")
            else:
                create_deposit(user_id, amount, txid)
                st.success("Aporte criado como PENDENTE. Aguarde aprovação do admin.")
        except Exception as e:
            st.error(str(e))

    st.divider()
    rows = list_deposits(user_id=user_id)
    if rows:
        df_dep = pd.DataFrame(rows, columns=["id","amount_usdt","txid","status","created_at","reviewed_at","note"])
        st.dataframe(df_dep, width="stretch")
    else:
        st.info("Sem aportes ainda.")

# =========================
# TAB: Saque
# =========================
with tabs[3]:
    st.subheader("🏧 Solicitar saque")
    bal = user_balance(user_id)
    st.metric("Saldo (USDT)", f"{bal:.2f}")

    amount_w = st.number_input("Valor para sacar (USDT)", min_value=0.0, step=10.0, format="%.2f")
    address = st.text_input("Endereço USDT", placeholder="TRC20 / ERC20 ...")

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
                st.error("Informe o endereço.")
            else:
                create_withdrawal(user_id, amount_w, address)
                st.success("Saque criado como PENDENTE. Aguarde aprovação do admin.")
        except Exception as e:
            st.error(str(e))

    st.divider()
    rows = list_withdrawals(user_id=user_id)
    if rows:
        df_w = pd.DataFrame(rows, columns=["id","amount_req","fee","net","address","status","created_at","reviewed_at","note"])
        st.dataframe(df_w, width="stretch")
    else:
        st.info("Sem saques ainda.")

# =========================
# TAB: Extrato
# =========================
with tabs[4]:
    st.subheader("📜 Extrato (ledger)")
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
            "⬇️ Baixar extrato CSV",
            data=df_led.to_csv(index=False).encode("utf-8"),
            file_name="extrato.csv",
            mime="text/csv",
            use_container_width=True
        )

# =========================
# TAB: Admin
# =========================
tab_index_admin = 5 if role == "admin" else None
if role == "admin":
    with tabs[5]:
        st.subheader("🛡️ Admin — Aprovar/Recusar Aportes e Saques")

        st.markdown("## Aportes pendentes")
        dep_all = list_deposits(user_id=None)
        dep_df = pd.DataFrame(dep_all, columns=["id","username","amount_usdt","txid","status","created_at","reviewed_at","note"])
        pending_dep = dep_df[dep_df["status"] == "PENDING"].copy()

        if pending_dep.empty:
            st.info("Sem aportes pendentes.")
        else:
            st.dataframe(pending_dep, width="stretch")
            dep_id = st.number_input("ID do depósito", min_value=1, step=1, key="dep_id")
            dep_note = st.text_input("Nota (opcional)", key="dep_note")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ Aprovar depósito", use_container_width=True):
                    try:
                        admin_review_deposit(int(dep_id), True, admin_id=user_id, note=dep_note)
                        st.success("Depósito aprovado e saldo creditado.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with c2:
                if st.button("❌ Rejeitar depósito", use_container_width=True):
                    try:
                        admin_review_deposit(int(dep_id), False, admin_id=user_id, note=dep_note)
                        st.warning("Depósito rejeitado.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

        st.divider()
        st.markdown("## Saques pendentes")
        w_all = list_withdrawals(user_id=None)
        w_df = pd.DataFrame(w_all, columns=["id","username","amount_req","fee","net","address","status","created_at","reviewed_at","note"])
        pending_w = w_df[w_df["status"] == "PENDING"].copy()

        if pending_w.empty:
            st.info("Sem saques pendentes.")
        else:
            st.dataframe(pending_w, width="stretch")
            wid = st.number_input("ID do saque", min_value=1, step=1, key="wid")
            w_note = st.text_input("Nota (opcional)", key="w_note")
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("✅ Aprovar saque (desconta saldo)", use_container_width=True):
                    try:
                        admin_review_withdrawal(int(wid), True, admin_id=user_id, note=w_note)
                        st.success("Saque aprovado e saldo descontado.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with c2:
                if st.button("❌ Rejeitar saque", use_container_width=True):
                    try:
                        admin_review_withdrawal(int(wid), False, admin_id=user_id, note=w_note)
                        st.warning("Saque rejeitado.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with c3:
                if st.button("💸 Marcar como PAGO", use_container_width=True):
                    try:
                        admin_mark_withdraw_paid(int(wid), admin_id=user_id, note=w_note)
                        st.success("Saque marcado como PAGO.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

        st.divider()
        st.markdown("## Usuários")
        conn = db()
        users_df = pd.read_sql_query("""
            SELECT id, username, role, created_at, referrer_code, my_code
            FROM users
            ORDER BY id ASC
        """, conn)
        conn.close()
        st.dataframe(users_df, width="stretch")

# =========================
# TAB: Config
# =========================
with tabs[-1]:
    st.subheader("⚙️ Config")
    st.markdown("""
### Rodar local
- `pip install streamlit pandas streamlit-autorefresh`
- `streamlit run app.py`

### Importante
- O **BOT** roda separado e gera o arquivo `paper_trades.csv`.
- O painel lê esse CSV e mostra gráficos e histórico.
- Depósitos/Saques ficam no SQLite: `mvp_funds.db`
""")
    st.code(f"Admin padrão: {DEFAULT_ADMIN_USER} / {DEFAULT_ADMIN_PASS}", language="text")
