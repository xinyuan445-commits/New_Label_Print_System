from __future__ import annotations

import io
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image

from app.db.session import get_session
from app.models.bill_favorite import BillFavorite
from app.models.label_format import FormatKind, LabelFormat
from app.services import assets as asset_svc
from app.services import templates as tpl_svc
from app.services.users import create_user, update_user
from tests.conftest import CsrfHelper


def test_templates_shared_but_favorites_personal(
    app: Flask,
    client: FlaskClient,
    csrf: CsrfHelper,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.config["SHARED_TEMPLATES"] = True
    monkeypatch.setenv("ASSETS_DIR", str(tmp_path / "assets"))
    with app.app_context():
        session = get_session()
        owner = create_user(session, email="designer", plain_password="a")
        create_user(session, email="operator", plain_password="b")
        library_user = create_user(session, email="library", plain_password="c")
        update_user(
            session,
            library_user.id,
            permissions={"templates": False, "bills": False, "library": True},
        )
        fmt = LabelFormat(name="Custom", width_mm=100, height_mm=180, kind=FormatKind.CUSTOM)
        session.add(fmt)
        session.commit()
        image = io.BytesIO()
        Image.new("RGB", (10, 10), "red").save(image, format="PNG")
        asset = asset_svc.save_image(
            session,
            owner_id=owner.id,
            original_filename="mark.png",
            raw=image.getvalue(),
            declared_mime="image/png",
        )
        template = tpl_svc.create(
            session,
            owner_id=owner.id,
            name="Shared label",
            format_id=fmt.id,
            description=None,
            canvas_data={
                "version": 1,
                "stage": {"width_mm": 100, "height_mm": 180, "corner_radius_mm": 2},
                "objects": [{"id": "img", "type": "image", "assetId": asset.id}],
            },
            featured_asset_id=asset.id,
        )
        template_id = template.id
        asset_id = asset.id
        session.add(BillFavorite(user_id=owner.id, bill_type="CGDH", position=0))
        session.commit()

    login = client.post(
        "/api/auth/login",
        json={"email": "operator", "password": "b"},
        headers=csrf.headers(),
    )
    assert login.status_code == 200
    listed = client.get("/api/templates")
    assert [item["id"] for item in listed.get_json()["templates"]] == [template_id]
    assert client.get(f"/api/templates/{template_id}").status_code == 200
    assert client.get(f"/api/assets/images/{asset_id}").status_code == 200
    assert client.get(f"/api/templates/{template_id}/featured-image").status_code == 200
    updated = client.put(
        f"/api/templates/{template_id}",
        json={"name": "Shared label edited"},
        headers=csrf.headers(),
    )
    assert updated.status_code == 200
    assert updated.get_json()["name"] == "Shared label edited"
    assert client.get(f"/api/templates/{template_id}/versions").status_code == 200
    exported = client.get(f"/api/templates/{template_id}/export")
    assert exported.status_code == 200
    payload = exported.get_json()
    assert payload["featured_asset_ref"]
    assert payload["canvas_data"]["stage"]["corner_radius_mm"] == 2
    assert client.get("/api/u8/bill-types").get_json()["favorites"] == []

    shared = client.put(
        f"/api/templates/{template_id}", json={"is_shared": True}, headers=csrf.headers()
    )
    assert shared.status_code == 200
    client.post("/api/auth/logout", headers=csrf.headers())
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "library", "password": "c"},
            headers=csrf.headers(),
        ).status_code
        == 200
    )
    assert client.get("/api/templates").status_code == 403
    library_list = client.get("/api/templates?scope=library")
    assert [row["id"] for row in library_list.get_json()["templates"]] == [template_id]
    assert client.get(f"/api/templates/{template_id}/featured-image").status_code == 200
    denied = client.post("/api/library/starters/example/use", headers=csrf.headers())
    assert denied.status_code == 403
