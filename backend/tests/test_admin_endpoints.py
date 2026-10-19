from __future__ import annotations

from flask import Flask
from flask.testing import FlaskClient

from app.db.session import get_session
from app.models.user import Role
from app.services.users import create_user
from tests.conftest import CsrfHelper


def _login_as(app: Flask, client: FlaskClient, csrf: CsrfHelper, role: Role) -> None:
    email = "actor@example.com"
    password = "actorPassword123"
    with app.app_context():
        create_user(get_session(), email=email, plain_password=password, role=role)
    client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers=csrf.headers(),
    )


def test_admin_can_list_users(app: Flask, client: FlaskClient, csrf: CsrfHelper) -> None:
    _login_as(app, client, csrf, Role.ADMIN)
    response = client.get("/api/admin/users")
    assert response.status_code == 200
    users = response.get_json()["users"]
    assert any(u["role"] == "admin" for u in users)


def test_non_admin_cannot_list_users(app: Flask, client: FlaskClient, csrf: CsrfHelper) -> None:
    _login_as(app, client, csrf, Role.EDITOR)
    response = client.get("/api/admin/users")
    assert response.status_code == 403


def test_unauthenticated_cannot_list_users(client: FlaskClient) -> None:
    response = client.get("/api/admin/users")
    assert response.status_code == 401


def test_admin_can_create_user(app: Flask, client: FlaskClient, csrf: CsrfHelper) -> None:
    _login_as(app, client, csrf, Role.ADMIN)
    response = client.post(
        "/api/admin/users",
        json={
            "email": "new@example.com",
            "role": "editor",
            "language": "pl",
            "temporary_password": "tempPassword123",
        },
        headers=csrf.headers(),
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body["user"]["email"] == "new@example.com"
    assert body["user"]["must_change_password"] is False
    assert body["temporary_password"] == "tempPassword123"


def test_create_user_duplicate_email_returns_409(
    app: Flask, client: FlaskClient, csrf: CsrfHelper
) -> None:
    _login_as(app, client, csrf, Role.ADMIN)
    payload = {"email": "dup@example.com", "temporary_password": "tempPassword123"}
    client.post("/api/admin/users", json=payload, headers=csrf.headers())
    response = client.post("/api/admin/users", json=payload, headers=csrf.headers())
    assert response.status_code == 409
    assert response.get_json()["error"] == "email_already_exists"


def test_admin_can_update_user_role(app: Flask, client: FlaskClient, csrf: CsrfHelper) -> None:
    _login_as(app, client, csrf, Role.ADMIN)
    create_response = client.post(
        "/api/admin/users",
        json={"email": "promote@example.com", "temporary_password": "tempPassword123"},
        headers=csrf.headers(),
    )
    new_id = create_response.get_json()["user"]["id"]

    response = client.patch(
        f"/api/admin/users/{new_id}",
        json={"role": "admin"},
        headers=csrf.headers(),
    )
    assert response.status_code == 200
    assert response.get_json()["role"] == "admin"


def test_admin_cannot_disable_self(app: Flask, client: FlaskClient, csrf: CsrfHelper) -> None:
    _login_as(app, client, csrf, Role.ADMIN)
    me_id = client.get("/api/me").get_json()["id"]

    response = client.patch(
        f"/api/admin/users/{me_id}",
        json={"is_active": False},
        headers=csrf.headers(),
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "cannot_disable_self"


def test_admin_can_reset_user_password(app: Flask, client: FlaskClient, csrf: CsrfHelper) -> None:
    _login_as(app, client, csrf, Role.ADMIN)
    create_response = client.post(
        "/api/admin/users",
        json={"email": "reset@example.com", "temporary_password": "originalPassword123"},
        headers=csrf.headers(),
    )
    target_id = create_response.get_json()["user"]["id"]

    response = client.post(
        f"/api/admin/users/{target_id}/reset-password",
        json={"new_temporary_password": "freshTemp789"},
        headers=csrf.headers(),
    )
    assert response.status_code == 200
    assert response.get_json()["temporary_password"] == "freshTemp789"


def test_update_unknown_user_returns_404(app: Flask, client: FlaskClient, csrf: CsrfHelper) -> None:
    _login_as(app, client, csrf, Role.ADMIN)
    response = client.patch(
        "/api/admin/users/999999",
        json={"role": "viewer"},
        headers=csrf.headers(),
    )
    assert response.status_code == 404


def test_account_name_short_password_and_page_permissions(
    app: Flask, client: FlaskClient, csrf: CsrfHelper
) -> None:
    _login_as(app, client, csrf, Role.ADMIN)
    created = client.post(
        "/api/admin/users",
        json={"email": "warehouse1", "temporary_password": "1"},
        headers=csrf.headers(),
    )
    assert created.status_code == 201
    user_id = created.get_json()["user"]["id"]
    updated = client.patch(
        f"/api/admin/users/{user_id}",
        json={"permissions": {"bills": False, "templates": True}},
        headers=csrf.headers(),
    )
    assert updated.status_code == 200
    assert updated.get_json()["permissions"]["bills"] is False

    client.post("/api/auth/logout", headers=csrf.headers())
    login = client.post(
        "/api/auth/login",
        json={"email": "warehouse1", "password": "1"},
        headers=csrf.headers(),
    )
    assert login.status_code == 200
    assert client.get("/api/me").get_json()["permissions"]["bills"] is False
    denied = client.get("/api/u8/bill-types")
    assert denied.status_code == 403
    assert denied.get_json()["error"] == "feature_disabled"


def test_page_visibility_is_per_user_and_does_not_revoke_access(
    app: Flask, client: FlaskClient, csrf: CsrfHelper
) -> None:
    _login_as(app, client, csrf, Role.ADMIN)
    admin_id = client.get("/api/me").get_json()["id"]
    created = client.post(
        "/api/admin/users",
        json={"email": "operator", "temporary_password": "1"},
        headers=csrf.headers(),
    )
    user_id = created.get_json()["user"]["id"]
    changed = client.patch(
        f"/api/admin/users/{user_id}",
        json={"visibility": {"dashboard": False, "templates": False}},
        headers=csrf.headers(),
    )
    assert changed.status_code == 200
    assert changed.get_json()["visibility"]["templates"] is False
    assert changed.get_json()["permissions"]["templates"] is True
    users = client.get("/api/admin/users").get_json()["users"]
    assert next(user for user in users if user["id"] == admin_id)["visibility"]["templates"] is True

    invalid = client.patch(
        f"/api/admin/users/{user_id}",
        json={"visibility": {"unknown": False}},
        headers=csrf.headers(),
    )
    assert invalid.status_code == 400

    client.post("/api/auth/logout", headers=csrf.headers())
    login = client.post(
        "/api/auth/login",
        json={"email": "operator", "password": "1"},
        headers=csrf.headers(),
    )
    assert login.status_code == 200
    me = client.get("/api/me").get_json()
    assert me["visibility"]["dashboard"] is False
    assert me["visibility"]["templates"] is False
    assert me["permissions"]["templates"] is True
    assert client.get("/api/templates").status_code == 200
