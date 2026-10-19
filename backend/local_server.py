"""Run the local pilot on explicitly configured IPv4 addresses."""

from __future__ import annotations

import os
import secrets
import subprocess
from contextlib import ExitStack
from ipaddress import IPv4Address
from pathlib import Path
from threading import Thread

from dotenv import load_dotenv
from flask import Flask, Response, abort, jsonify, send_from_directory
from flask.typing import ResponseReturnValue
from flask_login import login_required
from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.serving import make_server

from app.config import Config
from app.db.base import Base
from app.db.session import get_engine, get_session
from app.factory import create_app
from app.models import *  # noqa: F403 — register every mapped table before create_all
from app.models.label_format import FormatKind, LabelFormat
from app.models.user import Role
from app.services.local_printers import list_local_printers
from app.services.users import create_user, get_user_by_email

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".local-data"
DIST = ROOT / "frontend" / "dist"

SYSTEM_FORMATS = (
    ("A4 (210×297 mm)", 210, 297, FormatKind.A_PAPER),
    ("A5 (148×210 mm)", 148, 210, FormatKind.A_PAPER),
    ("A6 (105×148 mm)", 105, 148, FormatKind.A_PAPER),
    ('Zebra 4×6"', 101.6, 152.4, FormatKind.ZEBRA),
    ('Zebra 4×4"', 101.6, 101.6, FormatKind.ZEBRA),
    ('Zebra 3×2"', 76.2, 50.8, FormatKind.ZEBRA),
    ('Zebra 2×1"', 50.8, 25.4, FormatKind.ZEBRA),
    ("Custom (define size)", 100, 100, FormatKind.CUSTOM),
)


def seed_label_formats(session: Session) -> None:
    """create_all does not run Alembic's format seed; fill missing pilot presets."""
    existing = set(
        session.scalars(select(LabelFormat.name).where(LabelFormat.is_system.is_(True))).all()
    )
    for name, width, height, kind in SYSTEM_FORMATS:
        if name not in existing:
            session.add(
                LabelFormat(
                    name=name,
                    width_mm=width,
                    height_mm=height,
                    kind=kind,
                    is_system=True,
                )
            )
    session.commit()


def serve_on_hosts(app: Flask, hosts: list[str], port: int) -> None:
    # Bind every requested address before serving, so a failed second bind
    # cannot leave a partially started service running.
    with ExitStack() as stack:
        servers = []
        for host in hosts:
            server = make_server(host, port, app, threaded=True)
            stack.callback(server.server_close)
            servers.append(server)
        threads = []
        for server in servers[:-1]:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            threads.append(thread)
        for host in hosts:
            print(f"Label Printing System: http://{host}:{port}", flush=True)
        try:
            servers[-1].serve_forever()
        finally:
            for server in servers[:-1]:
                server.shutdown()
            for thread in threads:
                thread.join(timeout=2)


def main() -> None:
    load_dotenv(ROOT / ".env", override=False)
    hosts = list(
        dict.fromkeys(
            str(IPv4Address(value.strip()))
            for value in os.environ.get("LABEL_HOSTS", "127.0.0.1").split(",")
        )
    )
    if not (DIST / "index.html").exists():
        raise SystemExit("Please build the frontend first: cd frontend && npm ci && npm run build")
    DATA.mkdir(exist_ok=True)
    for env, folder in (
        ("UPLOADS_DIR", "uploads"),
        ("PDFS_DIR", "pdfs"),
        ("ASSETS_DIR", "assets"),
    ):
        target = DATA / folder
        target.mkdir(exist_ok=True)
        os.environ.setdefault(env, str(target))
    secret_path = DATA / "secret.key"
    if not secret_path.exists():
        secret_path.write_text(secrets.token_hex(32), encoding="ascii")
    cfg = Config(
        database_url=f"sqlite:///{(DATA / 'pilot.db').as_posix()}",
        redis_url="redis://127.0.0.1:6379/0",
        flask_env="development",
        secret_key=secret_path.read_text(encoding="ascii"),
        cookie_secure=False,
        shared_templates=os.environ.get("SHARED_TEMPLATES", "1") == "1",
    )
    app = create_app(cfg, use_redis_sessions=False)
    app.config["HEALTH_SKIP_REDIS"] = True
    with app.app_context():
        Base.metadata.create_all(get_engine())
        seed_label_formats(get_session())
        email = os.environ.get("LABEL_ADMIN_EMAIL", "admin@local.test")
        if get_user_by_email(get_session(), email) is None:
            password = os.environ.get("LABEL_ADMIN_PASSWORD") or secrets.token_urlsafe(14)
            create_user(
                get_session(),
                email=email,
                plain_password=password,
                role=Role.ADMIN,
                language="en",
                must_change_password=False,
            )
            print(f"Pilot login: {email} / {password}", flush=True)

    @app.get("/api/local-printers")
    @login_required
    def local_printers() -> ResponseReturnValue:
        try:
            return jsonify({"printers": list_local_printers()})
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            app.logger.warning("Windows printer discovery failed: %s", exc)
            return jsonify({"error": "local_printers_unavailable"}), 503

    @app.get("/")
    def index() -> Response:
        return send_from_directory(DIST, "index.html")

    @app.get("/<path:path>")
    def spa(path: str) -> Response:
        if path.startswith("api/"):
            abort(404)
        if (DIST / path).is_file():
            return send_from_directory(DIST, path)
        return send_from_directory(DIST, "index.html")

    serve_on_hosts(app, hosts, int(os.environ.get("LABEL_PORT", "18003")))


if __name__ == "__main__":
    main()
