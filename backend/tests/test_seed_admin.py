"""Bootstrap credentials must be usable with Compose's empty env placeholders."""

import re

from app.auth.password import verify_password
from app.db.session import get_session
from app.services.users import get_user_by_email


def test_empty_password_env_displays_generated_password(app):
    result = app.test_cli_runner().invoke(
        args=["seed-admin"],
        env={"ADMIN_EMAIL": "bootstrap", "ADMIN_PASSWORD": ""},
    )
    assert result.exit_code == 0
    match = re.search(r"password:\s+(\S+)", result.output)
    assert match is not None
    with app.app_context():
        user = get_user_by_email(get_session(), "bootstrap")
        assert user is not None
        assert verify_password(user.password_hash, match.group(1))


def test_provided_password_is_not_echoed_or_reset(app):
    runner = app.test_cli_runner()
    result = runner.invoke(
        args=["seed-admin"],
        env={"ADMIN_EMAIL": "bootstrap", "ADMIN_PASSWORD": "chosen-for-test"},
    )
    assert result.exit_code == 0
    assert "password:" not in result.output
    again = runner.invoke(
        args=["seed-admin"],
        env={"ADMIN_EMAIL": "bootstrap", "ADMIN_PASSWORD": "another-for-test"},
    )
    assert again.exit_code == 0
    assert "skipping" in again.output
    with app.app_context():
        user = get_user_by_email(get_session(), "bootstrap")
        assert user is not None
        assert verify_password(user.password_hash, "chosen-for-test")
