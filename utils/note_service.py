from __future__ import annotations

import argparse
import mimetypes
import shutil
import tempfile
from dataclasses import asdict, is_dataclass
from functools import wraps
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request, send_file

from core.storage.sqlite_notes import SQLiteNoteService
from utils.app_config import get_service_config, load_yaml_config
from utils.discover_appdata import discover_samsung_notes_storage_db
from utils.to_sdocx import compress_to_sdocx


def _normalize_windows_path_setting(value):
    if not isinstance(value, str):
        return value

    normalized = (
        value.replace("\x08", r"\b")
        .replace("\t", r"\t")
        .replace("\n", r"\n")
        .replace("\r", r"\r")
        .replace("\f", r"\f")
    )
    return normalized


def _serialize(value):
    if value is None:
        return None
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _resolve_candidate_path(candidate: str, db_path: Path) -> Path:
    path = Path(candidate)
    if path.is_absolute():
        return path
    return db_path.parent / path


def _resolve_source_folder(candidate: str, source_root: Optional[Path], db_path: Path) -> Optional[Path]:
    raw = Path(candidate)
    if raw.exists() and raw.is_dir():
        return raw

    if source_root is not None:
        for folder in (source_root / raw.name, source_root / raw.stem, source_root / candidate):
            if folder.exists() and folder.is_dir():
                return folder

    fallback = db_path.parent / raw.name
    if fallback.exists() and fallback.is_dir():
        return fallback
    return None


def _media_root_for_note(note, source_root: Optional[Path], db_path: Path) -> Optional[Path]:
    source_folder = _resolve_source_folder(note.file_path or note.uuid, source_root, db_path)
    if source_folder is None:
        return None
    media_root = source_folder / "media"
    if media_root.exists() and media_root.is_dir():
        return media_root
    return None


def _safe_media_file(media_root: Path, relative_path: str) -> Optional[Path]:
    candidate = (media_root / relative_path).resolve()
    try:
        candidate.relative_to(media_root.resolve())
    except ValueError:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate


def _with_deleted_status(item: dict) -> dict:
    payload = dict(item)
    payload["deleted_on_app"] = bool(payload.get("deleted_status"))
    return payload


def _require_bearer(auth_token: Optional[str]):
    def decorator(handler):
        @wraps(handler)
        def wrapped(*args, **kwargs):
            if not auth_token:
                return handler(*args, **kwargs)

            header = request.headers.get("Authorization", "")
            expected = f"Bearer {auth_token}"
            if header != expected:
                return jsonify({"error": "unauthorized"}), 401
            return handler(*args, **kwargs)

        return wrapped

    return decorator


def create_app(
    service: SQLiteNoteService,
    source_root: Optional[Path] = None,
    auth_token: Optional[str] = None,
    enable_download: bool = True,
    enable_media_review: bool = True,
) -> Flask:
    app = Flask(__name__)
    require_auth = _require_bearer(auth_token)

    @app.get("/health")
    def health():
        snapshot = service.snapshot()
        return jsonify(
            {
                "status": "ok",
                "db_path": str(snapshot.db_path),
                "note_count": snapshot.note_count,
                "last_refreshed_at": snapshot.last_refreshed_at.isoformat() if snapshot.last_refreshed_at else None,
            }
        )

    @app.get("/meta")
    @require_auth
    def meta():
        snapshot = service.snapshot()
        return jsonify(
            {
                "db_path": str(snapshot.db_path),
                "source_root": str(source_root) if source_root else None,
                "supports_download": bool(source_root) and enable_download,
                "supports_media_review": bool(source_root) and enable_media_review,
                "note_count": snapshot.note_count,
                "last_refreshed_at": snapshot.last_refreshed_at.isoformat() if snapshot.last_refreshed_at else None,
            }
        )

    @app.get("/schema")
    @require_auth
    def schema():
        snapshot = service.snapshot()
        return jsonify(
            {
                "db_path": str(snapshot.db_path),
                "tables": [
                    {
                        "name": table.name,
                        "columns": [column.__dict__ for column in table.columns],
                    }
                    for table in snapshot.tables
                ],
            }
        )

    @app.get("/notes")
    @require_auth
    def notes():
        limit = min(max(int(request.args.get("limit", 100)), 1), 500)
        offset = max(int(request.args.get("offset", 0)), 0)
        query = (request.args.get("q") or "").strip()
        if query:
            rows = service.search_notes(query=query, limit=limit, offset=offset)
            return jsonify({"items": [_serialize(row) for row in rows], "mode": "search"})
        rows = service.list_notes(limit=limit, offset=offset)
        return jsonify({"items": [_with_deleted_status(_serialize(row)) for row in rows], "mode": "list"})

    @app.get("/notes/<uuid>")
    @require_auth
    def note_detail(uuid: str):
        note = service.get_note(uuid)
        if note is None:
            return jsonify({"error": "note not found"}), 404
        return jsonify(_with_deleted_status(_serialize(note)))

    @app.get("/notes/<uuid>/thumbnail")
    @require_auth
    def note_thumbnail(uuid: str):
        note = service.get_note(uuid)
        if note is None:
            return jsonify({"error": "note not found"}), 404

        candidates = service.get_thumbnail_candidates(uuid)
        for candidate in candidates:
            path = _resolve_candidate_path(candidate, service.repository.db_path)
            if path.exists() and path.is_file():
                return send_file(path)
        return jsonify({"error": "thumbnail not found", "candidates": candidates}), 404

    @app.get("/notes/<uuid>/download")
    @require_auth
    def note_download(uuid: str):
        if not enable_download:
            return jsonify({"error": "download feature is disabled"}), 403

        note = service.get_note(uuid)
        if note is None:
            return jsonify({"error": "note not found"}), 404

        source_folder = _resolve_source_folder(note.file_path or note.uuid, source_root, service.repository.db_path)
        if source_folder is None:
            return jsonify({"error": "source folder not found", "hint": "pass --source when starting note_api"}), 404

        temp_dir = Path(tempfile.mkdtemp(prefix=f"snote_{uuid}_"))
        output_path = temp_dir / f"{uuid}.sdocx"

        try:
            compress_to_sdocx(str(source_folder), str(output_path))
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return jsonify({"error": str(exc)}), 500

        display_name = f"{(note.title or note.recommended_title or uuid).strip()}.sdocx"
        response = send_file(output_path, as_attachment=True, download_name=display_name)

        @response.call_on_close
        def _cleanup() -> None:
            shutil.rmtree(temp_dir, ignore_errors=True)

        return response

    @app.get("/notes/<uuid>/media")
    @require_auth
    def note_media(uuid: str):
        if not enable_media_review:
            return jsonify({"error": "media review feature is disabled", "items": []}), 403

        note = service.get_note(uuid)
        if note is None:
            return jsonify({"error": "note not found"}), 404

        media_root = _media_root_for_note(note, source_root, service.repository.db_path)
        if media_root is None:
            return jsonify({"error": "media folder not found", "items": []}), 404

        items = []
        for path in sorted(media_root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(media_root).as_posix()
            mime, _ = mimetypes.guess_type(path.name)
            items.append(
                {
                    "name": path.name,
                    "path": rel,
                    "size": path.stat().st_size,
                    "mime": mime or "application/octet-stream",
                }
            )

        return jsonify({"items": items})

    @app.get("/notes/<uuid>/media/<path:relative_path>")
    @require_auth
    def note_media_file(uuid: str, relative_path: str):
        if not enable_media_review:
            return jsonify({"error": "media review feature is disabled"}), 403

        note = service.get_note(uuid)
        if note is None:
            return jsonify({"error": "note not found"}), 404

        media_root = _media_root_for_note(note, source_root, service.repository.db_path)
        if media_root is None:
            return jsonify({"error": "media folder not found"}), 404

        file_path = _safe_media_file(media_root, relative_path)
        if file_path is None:
            return jsonify({"error": "media file not found"}), 404

        return send_file(file_path)

    @app.get("/search")
    @require_auth
    def search():
        query = (request.args.get("q") or "").strip()
        if not query:
            return jsonify({"error": "q is required"}), 400
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
        rows = service.search_notes(query=query, limit=limit, offset=offset)
        return jsonify({"items": [_serialize(row) for row in rows]})

    @app.get("/changes-since")
    @require_auth
    def changes_since():
        since = request.args.get("since")
        if since is None:
            return jsonify({"error": "since is required"}), 400
        try:
            since_value = int(since)
        except ValueError:
            return jsonify({"error": "since must be an integer"}), 400
        limit = min(max(int(request.args.get("limit", 500)), 1), 1000)
        offset = max(int(request.args.get("offset", 0)), 0)
        rows = service.list_changed_notes(since=since_value, limit=limit, offset=offset)
        return jsonify(
            {
                "items": [_with_deleted_status(_serialize(row)) for row in rows],
                "since": since_value,
            }
        )

    @app.post("/refresh")
    @require_auth
    def refresh():
        service.refresh_now()
        return jsonify({"status": "refreshed"})

    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Samsung Notes read-only Note API")
    parser.add_argument("--config", help="Path to YAML config", default="config/services.yml")
    parser.add_argument("--db", help="Path to Storage.sqlite", default=None)
    parser.add_argument("--source", help="Path to Samsung Notes wdoc/source folder", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--refresh-seconds", type=int, default=None)
    parser.add_argument("--token", help="Bearer token used by backup machine", default=None)
    args = parser.parse_args()

    config = load_yaml_config(Path(args.config))
    service_cfg = get_service_config(config, "note_api")
    features_cfg = service_cfg.get("features") if isinstance(service_cfg.get("features"), dict) else {}

    enabled = bool(service_cfg.get("enabled", True))
    if not enabled:
        print("note api is disabled by config")
        return 0

    db_setting = args.db if args.db is not None else service_cfg.get("db")
    source_setting = args.source if args.source is not None else service_cfg.get("source")
    db_setting = _normalize_windows_path_setting(db_setting)
    source_setting = _normalize_windows_path_setting(source_setting)
    host = args.host if args.host is not None else service_cfg.get("host", "127.0.0.1")
    port = args.port if args.port is not None else int(service_cfg.get("port", 5055))
    refresh_seconds = (
        args.refresh_seconds if args.refresh_seconds is not None else int(service_cfg.get("refresh_seconds", 30))
    )
    auth_token = args.token if args.token is not None else service_cfg.get("token")

    enable_download = bool(features_cfg.get("download", True))
    enable_media_review = bool(features_cfg.get("media_review", True))

    db_path = Path(db_setting) if db_setting else Path(discover_samsung_notes_storage_db())
    source_root = Path(source_setting) if source_setting else None

    service = SQLiteNoteService(db_path=db_path, refresh_seconds=refresh_seconds)
    service.start()
    app = create_app(
        service,
        source_root=source_root,
        auth_token=auth_token,
        enable_download=enable_download,
        enable_media_review=enable_media_review,
    )
    app.run(host=host, port=port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
