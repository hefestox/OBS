import os
import pandas as pd
import streamlit as st

# auto refresh (opcional)
try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except Exception:
    HAS_AUTOREFRESH = False

st.set_page_config(page_title="Crypto Bot Dashboard", layout="wide")
st.title("📊 Crypto Bot — Painel (PAPER / CSV)")

# =========================
# Sidebar
# =========================
st.sidebar.header("⚙️ Configurações")

csv_path = st.sidebar.text_input("Caminho do CSV", value="paper_trades.csv")
auto = st.sidebar.checkbox("Auto atualizar", value=True)
interval_sec = st.sidebar.slider("Intervalo (seg)", 2, 60, 10)

st.sidebar.caption("Dica: deixe o bot rodando e o dashboard aberto.")

if auto:
    if HAS_AUTOREFRESH:
        st_autorefresh(interval=interval_sec * 1000, key="refresh")
    else:
        st.sidebar.warning("Auto atualizar indisponível. Instale: pip install streamlit-autorefresh")

st.sidebar.divider()
st.sidebar.subheader("📌 Filtros")
only_sells = st.sidebar.checkbox("Mostrar só SELL", value=False)
show_raw = st.sidebar.checkbox("Mostrar tabela completa", value=True)

# =========================
# Helpers
# =========================
@st.cache_data(ttl=2)
def load_trades(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()

    df = pd.read_csv(path)

    # normaliza colunas esperadas
    for col in [
        "time", "symbol", "side", "price", "qty", "fee_usdt",
        "usdt_balance", "asset_balance", "reason", "pnl_usdt"
    ]:
        if col not in df.columns:
            df[col] = None

    df["time"] = pd.to_datetime(df["time"], errors="coerce")

    for c in ["price", "qty", "fee_usdt", "usdt_balance", "asset_balance", "pnl_usdt"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.sort_values("time").reset_index(drop=True)
    return df


def kpi_block(df: pd.DataFrame):
    if df.empty:
        st.info("Ainda não encontrei o CSV. Rode o bot e confira o caminho do arquivo.")
        return

    last = df.iloc[-1]

    sells = df[df["side"].astype(str).str.upper() == "SELL"].copy()
    wins = int((sells["pnl_usdt"] > 0).sum()) if not sells.empty else 0
    losses = int((sells["pnl_usdt"] < 0).sum()) if not sells.empty else 0
    total = wins + losses
    winrate = (wins / total * 100) if total else 0.0

    realized_pnl = float(sells["pnl_usdt"].sum()) if not sells.empty else 0.0

    last_usdt = float(last["usdt_balance"]) if pd.notna(last["usdt_balance"]) else None

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Negociações (SELL)", f"{total}")
    c2.metric("Vitórias", f"{wins}")
    c3.metric("Perdas", f"{losses}")
    c4.metric("Winrate", f"{winrate:.1f}%")
    c5.metric("PnL Realizado (USDT)", f"{realized_pnl:.4f}")
    c6.metric("Último saldo USDT", f"{last_usdt:.4f}" if last_usdt is not None else "—")

    with st.expander("🔎 Último registro (status do bot)"):
        st.write({
            "time": str(last.get("time")),
            "symbol": last.get("symbol"),
            "side": last.get("side"),
            "price": last.get("price"),
            "qty": last.get("qty"),
            "fee_usdt": last.get("fee_usdt"),
            "usdt_balance": last.get("usdt_balance"),
            "asset_balance": last.get("asset_balance"),
            "reason": last.get("reason"),
            "pnl_usdt": last.get("pnl_usdt"),
        })


def charts_block(df: pd.DataFrame):
    if df.empty:
        return

    df_view = df.copy()
    if only_sells:
        df_view = df_view[df_view["side"].astype(str).str.upper() == "SELL"].copy()

    # Equity curve
    eq = df.dropna(subset=["time"]).copy()

    if eq["usdt_balance"].notna().sum() >= 2:
        equity_series = eq[["time", "usdt_balance"]].dropna().rename(columns={"usdt_balance": "equity"})
    else:
        sells = eq[eq["side"].astype(str).str.upper() == "SELL"].copy()
        sells["pnl_usdt"] = pd.to_numeric(sells["pnl_usdt"], errors="coerce").fillna(0.0)
        sells["equity"] = sells["pnl_usdt"].cumsum()
        equity_series = sells[["time", "equity"]].copy()

    sells = df[df["side"].astype(str).str.upper() == "SELL"].copy()
    sells = sells.dropna(subset=["time"])
    sells["pnl_usdt"] = pd.to_numeric(sells["pnl_usdt"], errors="coerce")

    left, right = st.columns(2)

    with left:
        st.subheader("📈 Equidade (curva do saldo)")
        if not equity_series.empty:
            st.line_chart(equity_series.set_index("time")["equity"])
        else:
            st.info("Ainda não há dados suficientes para a curva de equidade.")

    with right:
        st.subheader("💹 PnL por trade (SELL)")
        if not sells.empty and sells["pnl_usdt"].notna().any():
            st.line_chart(sells.set_index("time")["pnl_usdt"])
        else:
            st.info("Sem SELL ainda (ou pnl_usdt vazio).")

    st.subheader("🧾 Histórico (filtrado)")
    if df_view.empty:
        st.info("Sem dados no filtro atual.")
    else:
        st.dataframe(df_view.tail(200), width="stretch")


# =========================
# Main
# =========================
if st.button("🔄 Atualizar agora"):
    load_trades.clear()

df = load_trades(csv_path)

kpi_block(df)
st.divider()
charts_block(df)

if show_raw:
    st.divider()
    st.subheader("📄 Tabela completa (últimas 500 linhas)")
    if df.empty:
        st.info("Sem CSV ainda.")
    else:
        st.dataframe(df.tail(500), width="stretch")
