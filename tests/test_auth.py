# tests/test_auth.py
import pytest

from garud360.auth.service import AuthError, AuthService
from garud360.config import defaults as cfg


@pytest.fixture()
def auth(repos):
    return AuthService(repos["users"], repos["events"])


def test_default_admin_created_once_and_forced_change(auth):
    assert auth.ensure_default_admin() is True
    assert auth.ensure_default_admin() is False
    u = auth.login(cfg.DEFAULT_ADMIN_USERNAME, cfg.DEFAULT_ADMIN_PASSWORD)
    assert u.role == "admin" and u.must_change_password == cfg.FORCE_PASSWORD_CHANGE_ON_FIRST_LOGIN


def test_login_failures_and_lockout(auth, monkeypatch):
    auth.ensure_default_admin()
    with pytest.raises(AuthError, match="Incorrect"):
        auth.login("admin", "wrong")
    with pytest.raises(AuthError, match="Incorrect"):
        auth.login("nobody", "x")
    for _ in range(cfg.LOGIN_MAX_ATTEMPTS - 2):
        with pytest.raises(AuthError):
            auth.login("admin", "bad")
    with pytest.raises(AuthError):
        auth.login("admin", "bad")
    with pytest.raises(AuthError, match="Too many"):
        auth.login("admin", cfg.DEFAULT_ADMIN_PASSWORD)          # locked even with the right password


def test_username_case_insensitive(auth):
    auth.ensure_default_admin()
    assert auth.login("ADMIN", cfg.DEFAULT_ADMIN_PASSWORD).username == "admin"


def test_change_password_rules(auth):
    auth.ensure_default_admin()
    u = auth.login("admin", cfg.DEFAULT_ADMIN_PASSWORD)
    with pytest.raises(AuthError, match="incorrect"):
        auth.change_own_password(u, "nope", "NewPassw0rd!")
    with pytest.raises(AuthError, match="at least"):
        auth.change_own_password(u, cfg.DEFAULT_ADMIN_PASSWORD, "short")
    with pytest.raises(AuthError, match="different"):
        auth.change_own_password(u, cfg.DEFAULT_ADMIN_PASSWORD, cfg.DEFAULT_ADMIN_PASSWORD)
    auth.change_own_password(u, cfg.DEFAULT_ADMIN_PASSWORD, "NewPassw0rd!")
    assert not auth.login("admin", "NewPassw0rd!").must_change_password
    with pytest.raises(AuthError):
        auth.login("admin", cfg.DEFAULT_ADMIN_PASSWORD)


def test_user_management_and_last_admin_protection(auth):
    auth.ensure_default_admin()
    admin = auth.login("admin", cfg.DEFAULT_ADMIN_PASSWORD)
    op = auth.create_user(admin, "operator1", "OperatorPass1", "operator")
    assert op.must_change_password
    with pytest.raises(AuthError, match="Administrator"):
        auth.create_user(op, "x" * 5, "Password123", "operator")
    with pytest.raises(AuthError, match="already exists"):
        auth.create_user(admin, "OPERATOR1", "OperatorPass1", "operator")
    with pytest.raises(AuthError, match="own account"):
        auth.delete_user(admin, admin.id)
    with pytest.raises(AuthError, match="At least one"):
        auth.set_role(admin, admin.id, "operator")
    auth.set_active(admin, op.id, False)
    with pytest.raises(AuthError, match="Incorrect"):
        auth.login("operator1", "OperatorPass1")
    auth.delete_user(admin, op.id)


def test_reset_default_admin(auth):
    auth.ensure_default_admin()
    admin = auth.login("admin", cfg.DEFAULT_ADMIN_PASSWORD)
    auth.change_own_password(admin, cfg.DEFAULT_ADMIN_PASSWORD, "Another#Pass1")
    auth.reset_default_admin()
    assert auth.login("admin", cfg.DEFAULT_ADMIN_PASSWORD).role == "admin"


def test_password_with_unicode_and_length_limit(auth):
    auth.ensure_default_admin()
    admin = auth.login("admin", cfg.DEFAULT_ADMIN_PASSWORD)
    with pytest.raises(AuthError, match="too long"):
        auth.create_user(admin, "longpw", "x" * 80, "operator")
    auth.create_user(admin, "uni", "pässwörd-ñ-123", "operator")
    assert auth.login("uni", "pässwörd-ñ-123").username == "uni"
