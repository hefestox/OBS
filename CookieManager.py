import os
import streamlit as st

# IMPORT opcional
try:
    import extra_streamlit_components as stx
    HAS_COOKIE_LIB = True
except Exception:
    HAS_COOKIE_LIB = False
    stx = None

# Detecta cloud
IS_CLOUD = bool(os.environ.get("STREAMLIT_CLOUD")) or bool(os.environ.get("STREAMLIT_SHARING"))

cookie_manager = None
if HAS_COOKIE_LIB and not IS_CLOUD:
    try:
        cookie_manager = stx.CookieManager()
    except Exception:
        cookie_manager = None

# Inicia sessão
if "user" not in st.session_state:
    st.session_state.user = None

def do_login(user):
    st.session_state.user = user
    # só tenta cookie se TUDO existir
    if cookie_manager and "COOKIE_NAME" in globals() and "make_session_token" in globals():
        try:
            token = make_session_token(user[0])
            cookie_manager.set(COOKIE_NAME, token, key="cookie_set")
        except Exception:
            pass

def do_logout():
    st.session_state.user = None
    if cookie_manager and "COOKIE_NAME" in globals():
        try:
            cookie_manager.delete(COOKIE_NAME, key="cookie_del")
        except Exception:
            pass
    st.rerun()

# Recupera do cookie (apenas se funções existirem)
if st.session_state.user is None and cookie_manager:
    if ("COOKIE_NAME" in globals()
        and "validate_session_token" in globals()
        and "get_user_by_id" in globals()):
        try:
            token = cookie_manager.get(COOKIE_NAME)
            if token:
                uid = validate_session_token(token)
                if uid:
                    u = get_user_by_id(uid)
                    if u:
                        st.session_state.user = u
        except Exception:
            pass

# Debug para garantir que a página não fica “branca”
st.write("UI carregou ✅")