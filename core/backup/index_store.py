from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional


def _normalize_text(value: Optional[str]) -> str:
    return (value or "").strip()


def _content_from_note(note: Dict) -> str:
    parts = [
        note.get("title"),
        note.get("recommended_title"),
        note.get("stripped_content"),
        note.get("pdf_text_contents"),
        note.get("hw_text_content"),
    ]
    merged = "\n".join(_normalize_text(part) for part in parts if _normalize_text(part))
    return merged[:20000]


class BackupIndexStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS note_index (
                    uuid TEXT PRIMARY KEY,
                    title TEXT,
                    content_text TEXT,
                    thumbnail_path TEXT,
                    deleted_on_app INTEGER NOT NULL DEFAULT 0,
                    active_in_app INTEGER NOT NULL DEFAULT 1,
                    last_seen_on_app TEXT,
                    last_synced_at TEXT,
                    last_marker INTEGER,
                    last_backup_artifact TEXT,
                    backup_artifacts_json TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_note_index_deleted_seen
                ON note_index(deleted_on_app, last_seen_on_app DESC)
                """
            )
            connection.commit()

    def upsert_note(self, note: Dict, now_iso: str, backup_artifact: Optional[str] = None) -> None:
        uuid = note.get("uuid")
        if not uuid:
            return

        deleted_on_app = int(bool(note.get("deleted_on_app") or note.get("deleted_status")))
        marker = 0
        for key in ("last_db_updated_at", "modified_at", "created_at"):
            value = note.get(key)
            if value:
                try:
                    marker = int(value)
                    break
                except Exception:
                    continue

        title = note.get("title") or note.get("recommended_title")
        thumbnail_path = note.get("thumbnail_path")
        content_text = _content_from_note(note)

        with self._connect() as connection:
            row = connection.execute(
                "SELECT backup_artifacts_json, last_backup_artifact FROM note_index WHERE uuid = ?",
                (uuid,),
            ).fetchone()

            artifacts: List[str] = []
            if row and row["backup_artifacts_json"]:
                try:
                    artifacts = json.loads(row["backup_artifacts_json"])
                except Exception:
                    artifacts = []

            last_backup_artifact = row["last_backup_artifact"] if row else None
            if backup_artifact:
                if backup_artifact not in artifacts:
                    artifacts.append(backup_artifact)
                last_backup_artifact = backup_artifact

            connection.execute(
                """
                INSERT INTO note_index(
                    uuid, title, content_text, thumbnail_path,
                    deleted_on_app, active_in_app, last_seen_on_app, last_synced_at,
                    last_marker, last_backup_artifact, backup_artifacts_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uuid) DO UPDATE SET
                    title = excluded.title,
                    content_text = excluded.content_text,
                    thumbnail_path = excluded.thumbnail_path,
                    deleted_on_app = excluded.deleted_on_app,
                    active_in_app = excluded.active_in_app,
                    last_seen_on_app = excluded.last_seen_on_app,
                    last_synced_at = excluded.last_synced_at,
                    last_marker = excluded.last_marker,
                    last_backup_artifact = excluded.last_backup_artifact,
                    backup_artifacts_json = excluded.backup_artifacts_json
                """,
                (
                    uuid,
                    title,
                    content_text,
                    thumbnail_path,
                    deleted_on_app,
                    0 if deleted_on_app else 1,
                    now_iso,
                    now_iso,
                    marker,
                    last_backup_artifact,
                    json.dumps(artifacts, ensure_ascii=False),
                ),
            )
            connection.commit()

    def reconcile_full_scan(self, active_uuids: set[str]) -> None:
        if not active_uuids:
            return
        placeholders = ",".join("?" for _ in active_uuids)
        with self._connect() as connection:
            connection.execute(
                f"""
                UPDATE note_index
                SET active_in_app = 0, deleted_on_app = 1
                WHERE uuid NOT IN ({placeholders}) AND COALESCE(last_backup_artifact, '') <> ''
                """,
                tuple(active_uuids),
            )
            connection.commit()

    def summary(self) -> Dict[str, int]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(1) AS total,
                    SUM(CASE WHEN deleted_on_app = 0 THEN 1 ELSE 0 END) AS active,
                    SUM(CASE WHEN deleted_on_app = 1 THEN 1 ELSE 0 END) AS deleted_on_app
                FROM note_index
                """
            ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "active": int(row["active"] or 0),
            "deleted_on_app": int(row["deleted_on_app"] or 0),
        }

    def list_notes(self, deleted_on_app: bool, limit: int, offset: int) -> List[Dict]:
        return self.list_notes_any(deleted_on_app=deleted_on_app, limit=limit, offset=offset)

    def list_notes_any(self, deleted_on_app: Optional[bool], limit: int, offset: int) -> List[Dict]:
        where_clause = ""
        params: List[object] = []
        if deleted_on_app is not None:
            where_clause = "WHERE deleted_on_app = ?"
            params.append(1 if deleted_on_app else 0)
        params.extend([int(limit), int(offset)])

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    uuid, title, deleted_on_app, active_in_app, last_seen_on_app, last_synced_at,
                    last_marker, last_backup_artifact, backup_artifacts_json, thumbnail_path
                FROM note_index
                {where_clause}
                ORDER BY COALESCE(last_marker, 0) DESC, COALESCE(last_seen_on_app, '') DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()

        items: List[Dict] = []
        for row in rows:
            try:
                artifacts = json.loads(row["backup_artifacts_json"] or "[]")
            except Exception:
                artifacts = []
            items.append(
                {
                    "uuid": row["uuid"],
                    "title": row["title"],
                    "deleted_on_app": bool(row["deleted_on_app"]),
                    "active_in_app": bool(row["active_in_app"]),
                    "last_seen_on_app": row["last_seen_on_app"],
                    "last_synced_at": row["last_synced_at"],
                    "last_marker": row["last_marker"],
                    "last_backup_artifact": row["last_backup_artifact"],
                    "backup_artifacts": artifacts,
                    "thumbnail_path": row["thumbnail_path"],
                }
            )
        return items

    def get_note(self, uuid: str) -> Optional[Dict]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    uuid, title, content_text, deleted_on_app, active_in_app, last_seen_on_app, last_synced_at,
                    last_marker, last_backup_artifact, backup_artifacts_json, thumbnail_path
                FROM note_index
                WHERE uuid = ?
                """,
                (uuid,),
            ).fetchone()

        if row is None:
            return None

        try:
            artifacts = json.loads(row["backup_artifacts_json"] or "[]")
        except Exception:
            artifacts = []

        return {
            "uuid": row["uuid"],
            "title": row["title"],
            "content_text": row["content_text"],
            "deleted_on_app": bool(row["deleted_on_app"]),
            "active_in_app": bool(row["active_in_app"]),
            "last_seen_on_app": row["last_seen_on_app"],
            "last_synced_at": row["last_synced_at"],
            "last_marker": row["last_marker"],
            "last_backup_artifact": row["last_backup_artifact"],
            "backup_artifacts": artifacts,
            "thumbnail_path": row["thumbnail_path"],
        }

    def delete_note(self, uuid: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM note_index WHERE uuid = ?", (uuid,))
            connection.commit()

    def search_notes(self, query: str, deleted_on_app: Optional[bool], limit: int, offset: int) -> List[Dict]:
        term = _normalize_text(query)
        if not term:
            return []

        where_parts = ["(lower(COALESCE(title, '')) LIKE lower(?) OR lower(COALESCE(content_text, '')) LIKE lower(?) OR lower(uuid) LIKE lower(?))"]
        params: List[object] = [f"%{term}%", f"%{term}%", f"%{term}%"]

        if deleted_on_app is not None:
            where_parts.append("deleted_on_app = ?")
            params.append(1 if deleted_on_app else 0)

        params.extend([int(limit), int(offset)])
        where_clause = " AND ".join(where_parts)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    uuid, title, deleted_on_app, active_in_app, last_seen_on_app, last_synced_at,
                    last_marker, last_backup_artifact, backup_artifacts_json, thumbnail_path
                FROM note_index
                WHERE {where_clause}
                ORDER BY COALESCE(last_seen_on_app, '') DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()

        items: List[Dict] = []
        for row in rows:
            try:
                artifacts = json.loads(row["backup_artifacts_json"] or "[]")
            except Exception:
                artifacts = []
            items.append(
                {
                    "uuid": row["uuid"],
                    "title": row["title"],
                    "deleted_on_app": bool(row["deleted_on_app"]),
                    "active_in_app": bool(row["active_in_app"]),
                    "last_seen_on_app": row["last_seen_on_app"],
                    "last_synced_at": row["last_synced_at"],
                    "last_marker": row["last_marker"],
                    "last_backup_artifact": row["last_backup_artifact"],
                    "backup_artifacts": artifacts,
                    "thumbnail_path": row["thumbnail_path"],
                }
            )
        return items

    def get_last_backup_artifact(self, uuid: str) -> Optional[str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT last_backup_artifact FROM note_index WHERE uuid = ?",
                (uuid,),
            ).fetchone()
        if row is None:
            return None
        return row["last_backup_artifact"]
