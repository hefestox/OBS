import types
import threading
import sys
from pathlib import Path

import pytest


DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "dashboard.py"


def load_dashboard_core_module(monkeypatch, tmp_path):
    source = DASHBOARD_PATH.read_text(encoding="utf-8")
    marker = "\nif BOT_MODE:\n"
    cutoff = source.index(marker)
    core_source = source[:cutoff]

    module = types.ModuleType("dashboard")
    module.__file__ = str(DASHBOARD_PATH)

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DEFAULT_ADMIN_PASS", "admin_test_pass_123")
    monkeypatch.setenv("SESSION_SECRET", "test_session_secret")

    exec(compile(core_source, str(DASHBOARD_PATH), "exec"), module.__dict__)
    sys.modules["dashboard"] = module

    module.DB_PATH = str(tmp_path / "test.db")
    module.DEFAULT_ADMIN_PASS = "admin_test_pass_123"
    module.SESSION_SECRET = "test_session_secret"

    return module


def query_one(mod, sql, params=()):
    with mod._DB_LOCK:
        conn = mod.db()
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        conn.close()
    return row


def test_password_hash_verify_and_legacy_migration(monkeypatch, tmp_path):
    mod = load_dashboard_core_module(monkeypatch, tmp_path)
    mod.init_db()

    mod.create_user("alice", "s3cret", "user")
    user = mod.get_user_by_username("alice")
    assert mod.is_bcrypt_hash(user[2])
    assert mod.verify_password("s3cret", user[2])

    legacy_hash = mod.sha256("legacy_pass")
    with mod._DB_LOCK:
        conn = mod.db()
        cur = conn.cursor()
        cur.execute("UPDATE users SET pass_hash=? WHERE username='alice'", (legacy_hash,))
        conn.commit()
        conn.close()

    logged_user = mod.auth("alice", "legacy_pass")
    assert logged_user is not None
    migrated = mod.get_user_by_username("alice")
    assert mod.is_bcrypt_hash(migrated[2])
    assert migrated[2] != legacy_hash


def test_session_token_is_non_deterministic(monkeypatch, tmp_path):
    mod = load_dashboard_core_module(monkeypatch, tmp_path)
    mod.init_db()
    mod.create_user("bob", "pass123", "user")
    bob = mod.get_user_by_username("bob")

    t1 = mod.create_session(bob[0])
    t2 = mod.create_session(bob[0])

    assert t1 != t2
    assert isinstance(t1, str) and isinstance(t2, str)
    assert len(t1) >= 32 and len(t2) >= 32


def test_admin_review_deposit_is_atomic_with_ledger(monkeypatch, tmp_path):
    mod = load_dashboard_core_module(monkeypatch, tmp_path)
    mod.init_db()

    admin = mod.get_user_by_username(mod.DEFAULT_ADMIN_USER)
    mod.create_user("carol", "pass123", "user")
    user = mod.get_user_by_username("carol")

    mod.create_deposit(user[0], 50, "tx-001")
    dep_id = query_one(mod, "SELECT id FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 1", (user[0],))[0]

    original_add_ledger_tx = mod._add_ledger_tx

    def fail_add_ledger(*args, **kwargs):
        raise RuntimeError("ledger failure")

    mod._add_ledger_tx = fail_add_ledger
    with pytest.raises(RuntimeError, match="ledger failure"):
        mod.admin_review_deposit(dep_id, True, admin[0], "approve")
    mod._add_ledger_tx = original_add_ledger_tx

    status = query_one(mod, "SELECT status FROM deposits WHERE id=?", (dep_id,))[0]
    ledger_count = query_one(mod, "SELECT COUNT(*) FROM ledger WHERE ref_table='deposits' AND ref_id=?", (dep_id,))[0]
    assert status == "PENDING"
    assert ledger_count == 0


def test_admin_review_withdrawal_is_atomic_with_ledger(monkeypatch, tmp_path):
    mod = load_dashboard_core_module(monkeypatch, tmp_path)
    mod.init_db()

    admin = mod.get_user_by_username(mod.DEFAULT_ADMIN_USER)
    mod.create_user("dave", "pass123", "user")
    user = mod.get_user_by_username("dave")

    mod.add_ledger(user[0], "DEPOSIT", 100, "seed", 1)
    mod.create_withdrawal(user[0], 40, "TRC20", "TADDR")
    wid = query_one(mod, "SELECT id FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 1", (user[0],))[0]

    original_add_ledger_tx = mod._add_ledger_tx

    def fail_add_ledger(*args, **kwargs):
        raise RuntimeError("ledger failure")

    mod._add_ledger_tx = fail_add_ledger
    with pytest.raises(RuntimeError, match="ledger failure"):
        mod.admin_review_withdrawal(wid, True, admin[0], "approve")
    mod._add_ledger_tx = original_add_ledger_tx

    status = query_one(mod, "SELECT status FROM withdrawals WHERE id=?", (wid,))[0]
    ledger_count = query_one(mod, "SELECT COUNT(*) FROM ledger WHERE ref_table='withdrawals' AND ref_id=?", (wid,))[0]
    assert status == "PENDING"
    assert ledger_count == 0


def test_create_withdrawal_validates_balance_inside_critical_section(monkeypatch, tmp_path):
    mod = load_dashboard_core_module(monkeypatch, tmp_path)
    mod.init_db()

    mod.create_user("erin", "pass123", "user")
    user = mod.get_user_by_username("erin")

    mod.user_balance = lambda _uid: 999999  # não deve ser usado pela implementação transacional

    with pytest.raises(ValueError, match="Saldo insuficiente"):
        mod.create_withdrawal(user[0], 10, "TRC20", "TADDR")


def test_get_session_user_returns_none_for_expired_token(monkeypatch, tmp_path):
    mod = load_dashboard_core_module(monkeypatch, tmp_path)
    mod.init_db()
    mod.create_user("frank", "pass123", "user")
    user = mod.get_user_by_username("frank")

    token = mod.create_session(user[0])
    with mod._DB_LOCK:
        conn = mod.db()
        cur = conn.cursor()
        cur.execute("UPDATE sessions SET expires_at='2000-01-01 00:00:00' WHERE token=?", (token,))
        conn.commit()
        conn.close()

    assert mod.get_session_user(token) is None


def test_create_session_invalidates_previous_session_for_same_user(monkeypatch, tmp_path):
    mod = load_dashboard_core_module(monkeypatch, tmp_path)
    mod.init_db()
    mod.create_user("gina", "pass123", "user")
    user = mod.get_user_by_username("gina")

    old_token = mod.create_session(user[0])
    new_token = mod.create_session(user[0])

    assert old_token != new_token
    assert mod.get_session_user(old_token) is None
    current = mod.get_session_user(new_token)
    assert current is not None
    assert current[0] == user[0]


def test_get_session_user_returns_none_for_invalid_or_malformed_token(monkeypatch, tmp_path):
    mod = load_dashboard_core_module(monkeypatch, tmp_path)
    mod.init_db()
    mod.create_user("hank", "pass123", "user")
    user = mod.get_user_by_username("hank")
    mod.create_session(user[0])

    assert mod.get_session_user("not-a-valid-token") is None
    assert mod.get_session_user("%%%malformed%%%") is None


def test_admin_review_deposit_success_sets_approved_and_inserts_ledger(monkeypatch, tmp_path):
    mod = load_dashboard_core_module(monkeypatch, tmp_path)
    mod.init_db()

    admin = mod.get_user_by_username(mod.DEFAULT_ADMIN_USER)
    mod.create_user("ivan", "pass123", "user")
    user = mod.get_user_by_username("ivan")

    mod.create_deposit(user[0], 75, "tx-approve-001")
    dep_id = query_one(mod, "SELECT id FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 1", (user[0],))[0]

    mod.admin_review_deposit(dep_id, True, admin[0], "ok")

    status = query_one(mod, "SELECT status FROM deposits WHERE id=?", (dep_id,))[0]
    ledger = query_one(
        mod,
        "SELECT kind, amount_usdt, ref_table, ref_id FROM ledger WHERE ref_table='deposits' AND ref_id=?",
        (dep_id,),
    )
    assert status == "APPROVED"
    assert ledger == ("DEPOSIT", 75.0, "deposits", dep_id)


def test_admin_review_withdrawal_success_sets_approved_and_inserts_ledger_debit(monkeypatch, tmp_path):
    mod = load_dashboard_core_module(monkeypatch, tmp_path)
    mod.init_db()

    admin = mod.get_user_by_username(mod.DEFAULT_ADMIN_USER)
    mod.create_user("jane", "pass123", "user")
    user = mod.get_user_by_username("jane")

    mod.add_ledger(user[0], "DEPOSIT", 120, "seed", 1)
    mod.create_withdrawal(user[0], 50, "TRC20", "TADDR")
    wid = query_one(mod, "SELECT id FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 1", (user[0],))[0]

    mod.admin_review_withdrawal(wid, True, admin[0], "ok")

    status = query_one(mod, "SELECT status FROM withdrawals WHERE id=?", (wid,))[0]
    ledger = query_one(
        mod,
        "SELECT kind, amount_usdt, ref_table, ref_id FROM ledger WHERE ref_table='withdrawals' AND ref_id=?",
        (wid,),
    )
    assert status == "APPROVED"
    assert ledger == ("WITHDRAWAL", -50.0, "withdrawals", wid)


def test_create_withdrawal_concurrent_requests_only_one_persists(monkeypatch, tmp_path):
    mod = load_dashboard_core_module(monkeypatch, tmp_path)
    mod.init_db()
    mod.create_user("karl", "pass123", "user")
    user = mod.get_user_by_username("karl")
    mod.add_ledger(user[0], "DEPOSIT", 100, "seed", 1)

    barrier = threading.Barrier(3)
    successes = []
    errors = []

    def worker():
        try:
            barrier.wait()
            mod.create_withdrawal(user[0], 80, "TRC20", "TADDR")
            successes.append(True)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    barrier.wait()
    t1.join()
    t2.join()

    persisted = query_one(mod, "SELECT COUNT(*) FROM withdrawals WHERE user_id=?", (user[0],))[0]
    assert len(successes) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert "Saldo insuficiente" in str(errors[0])
    assert persisted == 1
