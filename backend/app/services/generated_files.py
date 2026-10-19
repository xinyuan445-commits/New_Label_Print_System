"""Generated-file history + 30-day lazy retention. No Flask coupling."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.generated_file import GeneratedFile
from app.services.jobs import pdfs_dir

GENERATED_RETENTION_DAYS = 30
# Entries whose file never materialized (failed/aborted jobs) are pruned
# once they're older than this — long enough to outlast a slow batch.
_ORPHAN_GRACE = timedelta(hours=1)


@dataclass
class HistoryEntry:
    id: int
    template_name: str
    kind: str
    mode: str
    row_count: int | None
    size_bytes: int
    created_at: datetime
    download_name: str


def download_name_for(row: GeneratedFile) -> str:
    """Use the U8 document number for bill PDFs, the template name otherwise."""
    stem = row.template_name
    storage = Path(row.storage_filename)
    if (
        row.mode in {"bill", "stock", "reprint"}
        and row.kind == "pdf"
        and storage.parent.name == "bill-print-runs"
    ):
        manifest_path = pdfs_dir() / storage.with_suffix(".json")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            bill_number = manifest.get("bill_number")
            if (
                manifest.get("run_id") == storage.stem
                and manifest.get("owner_id") == row.owner_id
                and isinstance(bill_number, str)
                and bill_number.strip()
            ):
                stem = f"{bill_number}_补打" if row.mode == "reprint" else bill_number
        except (OSError, ValueError, TypeError):
            pass
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")[:120].rstrip(" .")
    if not safe:
        safe = "labels"
    return f"{safe}.{row.kind}"


def _prune(session: Session) -> None:
    """Lazy retention, run on every record(): drop rows past 30 days (and
    their files) plus orphaned rows whose file never appeared."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=GENERATED_RETENTION_DAYS)
    orphan_cutoff = now - _ORPHAN_GRACE
    for row in session.scalars(select(GeneratedFile)):
        # SQLite returns DateTime values without timezone information even when
        # the mapped column requests timezone=True.
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        path = pdfs_dir() / row.storage_filename
        exists = path.is_file()
        if created_at < cutoff:
            if exists:
                path.unlink(missing_ok=True)
            session.delete(row)
        elif not exists and created_at < orphan_cutoff:
            session.delete(row)


def record(
    session: Session,
    *,
    owner_id: int,
    template_id: int | None,
    template_name: str,
    kind: str,
    mode: str,
    storage_filename: str,
    row_count: int | None = None,
) -> GeneratedFile:
    row = GeneratedFile(
        owner_id=owner_id,
        template_id=template_id,
        template_name=template_name,
        kind=kind,
        mode=mode,
        storage_filename=storage_filename,
        row_count=row_count,
    )
    session.add(row)
    _prune(session)
    session.commit()
    session.refresh(row)
    return row


def list_for_user(session: Session, *, user_id: int) -> list[HistoryEntry]:
    """Finished files only — an entry whose file isn't on disk yet (batch in
    flight) or ever (failed job) is hidden until/unless the bytes exist."""
    stmt = (
        select(GeneratedFile)
        .where(GeneratedFile.owner_id == user_id)
        .order_by(GeneratedFile.created_at.desc(), GeneratedFile.id.desc())
    )
    out: list[HistoryEntry] = []
    for row in session.scalars(stmt):
        path = pdfs_dir() / row.storage_filename
        if not path.is_file():
            continue
        out.append(
            HistoryEntry(
                id=row.id,
                template_name=row.template_name,
                kind=row.kind,
                mode=row.mode,
                row_count=row.row_count,
                size_bytes=path.stat().st_size,
                created_at=row.created_at,
                download_name=download_name_for(row),
            )
        )
    return out


def get_for_user(session: Session, file_id: int, *, user_id: int) -> GeneratedFile | None:
    row = session.get(GeneratedFile, file_id)
    if row is None or row.owner_id != user_id:
        return None
    return row


def delete(session: Session, file_id: int, *, user_id: int) -> bool:
    row = get_for_user(session, file_id, user_id=user_id)
    if row is None:
        return False
    (pdfs_dir() / row.storage_filename).unlink(missing_ok=True)
    session.delete(row)
    session.commit()
    return True
