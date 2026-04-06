from __future__ import annotations

import argparse
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib import error as urllib_error

from flask import Flask, jsonify, render_template_string, request, send_file

from core.backup.incremental_service import IncrementalBackupService
from utils.app_config import get_service_config, load_yaml_config


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
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


class SyncController:
    def __init__(self, service: IncrementalBackupService):
        self.service = service
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._last_result = None
        self._last_error = None

    def start(self, force_reconcile: bool = False) -> dict:
        with self._lock:
            if self._running:
                return {"accepted": False, "running": True, "message": "sync already running"}
            self._running = True
            self._last_error = None

        def _worker():
            try:
                self._last_result = _serialize(self.service.sync_now(force_reconcile=force_reconcile))
            except Exception as exc:
                self._last_error = str(exc)
            finally:
                with self._lock:
                    self._running = False

        self._thread = threading.Thread(target=_worker, name="backup-sync-ui", daemon=True)
        self._thread.start()
        return {"accepted": True, "running": True}

    def status(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "last_result": self._last_result,
                "last_error": self._last_error,
            }


def _ui_template() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Samsung Notes Backup UI</title>
    <style>
        :root { color-scheme: dark; }
        body { margin: 0; font-family: Inter, Segoe UI, Arial, sans-serif; background: #0b1020; color: #e5e7eb; }
        header { padding: 14px 20px; display: flex; gap: 10px; align-items: center; background: #111827; border-bottom: 1px solid #1f2937; }
        .pill { padding: 4px 10px; border-radius: 999px; background: #1f2937; font-size: 12px; color: #cbd5e1; }
        main { padding: 16px; display: grid; gap: 12px; }
        .card { background: #0f172a; border: 1px solid #1f2937; border-radius: 12px; padding: 12px; }
        .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
        button { border: none; border-radius: 10px; padding: 10px 12px; background: linear-gradient(135deg, #2563eb, #7c3aed); color: #fff; cursor: pointer; }
        button.secondary { background: #1f2937; }
        button.danger { background: #b91c1c; }
        .small { color: #94a3b8; font-size: 12px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        .item { border-bottom: 1px solid #1f2937; padding: 8px 0; }
        .item:last-child { border-bottom: none; }
        .title { font-weight: 600; }
        .tag { display:inline-block; font-size:11px; border-radius:999px; padding:2px 8px; margin-right:6px; background:#1f2937; color:#cbd5e1; }
        .tag.active { background:#14532d; color:#bbf7d0; }
        .tag.deleted { background:#7f1d1d; color:#fecaca; }
        .list-wrap { max-height: 70vh; overflow: auto; }
        .note-item { cursor: pointer; padding: 10px; border-bottom: 1px solid #1f2937; }
        .note-item:hover, .note-item.selected { background: #111827; }
        .review-thumb { width: 100%; max-height: 340px; object-fit: contain; border: 1px solid #1f2937; border-radius: 8px; background:#111827; }
        .review-meta { display:grid; gap:6px; margin-top:10px; }
    </style>
</head>
<body>
<header>
    <strong>Samsung Notes Backup UI</strong>
    <span class="pill" id="status">loading...</span>
    <span class="pill" id="summary">0</span>
</header>
<main>
    <div class="card">
        <div class="row">
            <button id="syncBtn">Run Sync</button>
            <button id="quickSyncBtn" class="secondary">Quick Sync</button>
            <button id="refreshBtn" class="secondary">Refresh</button>
            <input id="searchInput" placeholder="Search by note content/title" style="flex:1; min-width:220px; border:1px solid #1f2937; background:#111827; color:#e5e7eb; border-radius:10px; padding:10px 12px;" />
            <button id="searchBtn">Search</button>
            <span id="syncState" class="small"></span>
        </div>
    </div>
    <div class="grid">
        <div class="card">
            <div class="title">Notes</div>
            <div id="notesList" class="list-wrap small">loading...</div>
            <div style="margin-top:10px"><button id="loadMoreBtn" class="secondary">Load More</button></div>
        </div>
        <div class="card">
            <div class="title">Note Review</div>
            <div id="reviewPanel" class="small">Select a note</div>
        </div>
    </div>
</main>
<script>
let offset = 0;
let limit = 40;
let selectedUuid = null;
let activeQuery = '';
let loading = false;

function toDateText(marker) {
    if (!marker) return '-';
    const n = Number(marker);
    if (!Number.isFinite(n)) return String(marker);
    const value = n > 100000000000 ? n : n * 1000;
    const d = new Date(value);
    if (isNaN(d.getTime())) return String(marker);
    return d.toLocaleString();
}

function dayKey(marker) {
    if (!marker) return 'unknown';
    const n = Number(marker);
    if (!Number.isFinite(n)) return 'unknown';
    const value = n > 100000000000 ? n : n * 1000;
    const d = new Date(value);
    if (isNaN(d.getTime())) return 'unknown';
    return d.toISOString().slice(0, 10);
}

function tag(item) {
    return item.deleted_on_app ? `<span class='tag deleted'>deleted</span>` : `<span class='tag active'>active</span>`;
}

function renderItems(items, append=false) {
    const el = document.getElementById('notesList');
    if (!append) el.innerHTML = '';
    if (!items.length && !append) {
        el.innerHTML = 'no notes';
        return;
    }

    let lastGroup = append ? el.getAttribute('data-last-group') : null;
    const parts = [];
    for (const item of items) {
        const group = dayKey(item.last_marker);
        if (group !== lastGroup) {
            parts.push(`<div class='small' style='padding:8px 10px;color:#93c5fd'>${group}</div>`);
            lastGroup = group;
        }
        parts.push(`
            <div class='note-item ${selectedUuid === item.uuid ? 'selected' : ''}' data-uuid='${item.uuid}'>
                <div>${tag(item)} ${item.title || item.uuid}</div>
                <div class='small'>${item.uuid}</div>
                <div class='small'>modified: ${toDateText(item.last_marker)}</div>
            </div>
        `);
    }
    el.insertAdjacentHTML('beforeend', parts.join(''));
    el.setAttribute('data-last-group', lastGroup || '');

    el.querySelectorAll('.note-item').forEach(node => {
        node.onclick = () => loadReview(node.getAttribute('data-uuid'));
    });
}

async function loadNotes(reset=true) {
    if (loading) return;
    loading = true;
    if (reset) {
        offset = 0;
    }
    let url = '';
    if (activeQuery) {
        url = `/index/search?q=${encodeURIComponent(activeQuery)}&limit=${limit}&offset=${offset}`;
    } else {
        url = `/index/notes?limit=${limit}&offset=${offset}`;
    }
    const data = await fetch(url).then(r => r.json());
    const items = data.items || [];
    renderItems(items, !reset);
    offset += items.length;
    document.getElementById('loadMoreBtn').disabled = items.length < limit;
    loading = false;
}

async function loadReview(uuid) {
    selectedUuid = uuid;
    const data = await fetch(`/index/notes/${encodeURIComponent(uuid)}`).then(r => r.json());
    if (data.error) {
        document.getElementById('reviewPanel').innerHTML = data.error;
        return;
    }
    const purgeBtn = data.deleted_on_app ? `<button id='purgeBtn' class='danger'>Delete Backed-up File</button>` : '';
    document.getElementById('reviewPanel').innerHTML = `
        <div><strong>${data.title || data.uuid}</strong></div>
        <div style='margin-top:8px'>
            <img class='review-thumb' src='/notes/${encodeURIComponent(data.uuid)}/thumbnail' onerror="this.style.display='none'" />
        </div>
        <div class='review-meta'>
            <div>${tag(data)}</div>
            <div>modified: ${toDateText(data.last_marker)}</div>
            <div>last sync: ${data.last_synced_at || '-'}</div>
            <div><a href='/backup/${encodeURIComponent(data.uuid)}/download'>Download backup file</a></div>
            ${purgeBtn}
        </div>
    `;
    const purge = document.getElementById('purgeBtn');
    if (purge) {
        purge.onclick = async () => {
            if (!confirm(`Delete backed-up file for "${data.title || data.uuid}"? This action cannot be undone.`)) {
                return;
            }
            const resp = await fetch(`/backup/${encodeURIComponent(data.uuid)}/purge`, { method: 'POST' });
            const payload = await resp.json();
            alert(payload.status || payload.error || 'done');
            await refreshSummary();
            await loadNotes(true);
            document.getElementById('reviewPanel').innerHTML = 'Select a note';
        };
    }
}

async function refreshSummary() {
    const health = await fetch('/health').then(r => r.json());
    document.getElementById('status').textContent = `checkpoint ${health.state?.checkpoint ?? 0}`;

    const summary = await fetch('/index/summary').then(r => r.json());
    document.getElementById('summary').textContent = `active ${summary.active} • deleted ${summary.deleted_on_app} • total ${summary.total}`;
}

let lastSyncResult = null;

async function pollSyncStatus() {
    const s = await fetch('/sync/status').then(r => r.json());
    if (s.running) {
        document.getElementById('syncState').textContent = 'syncing in background...';
    } else if (s.last_error) {
        document.getElementById('syncState').textContent = 'sync error: ' + s.last_error;
        lastSyncResult = null;
    } else if (s.last_result) {
        // When sync completes, auto-refresh notes if result changed
        if (lastSyncResult !== JSON.stringify(s.last_result)) {
            lastSyncResult = JSON.stringify(s.last_result);
            await refreshSummary();
            await loadNotes(true);
        }
        document.getElementById('syncState').textContent = `last sync changed ${s.last_result.changed_count || 0}`;
    }
}

async function refresh() {
    await refreshSummary();
    await loadNotes(true);
}

async function search() {
    activeQuery = document.getElementById('searchInput').value.trim();
    await loadNotes(true);
}

document.getElementById('syncBtn').addEventListener('click', async () => {
    const state = document.getElementById('syncState');
    state.textContent = 'starting sync...';
    const resp = await fetch('/sync/start', { method: 'POST' });
    const payload = await resp.json();
    state.textContent = resp.ok ? (payload.message || 'sync started') : (payload.error || 'sync error');
});

document.getElementById('quickSyncBtn').addEventListener('click', async () => {
    const state = document.getElementById('syncState');
    state.textContent = 'starting quick sync...';
    const resp = await fetch('/sync/quick', { method: 'POST' });
    const payload = await resp.json();
    state.textContent = resp.ok ? (payload.message || 'quick sync started') : (payload.error || 'sync error');
});

document.getElementById('refreshBtn').addEventListener('click', async () => refresh());
document.getElementById('loadMoreBtn').addEventListener('click', async () => loadNotes(false));

document.getElementById('searchBtn').addEventListener('click', search);
document.getElementById('searchInput').addEventListener('keydown', async (e) => {
    if (e.key === 'Enter') {
        await search();
    }
});

refresh();
setInterval(pollSyncStatus, 2500);
</script>
</body>
</html>
"""


def create_app(service: IncrementalBackupService) -> Flask:
    app = Flask(__name__)
    sync_controller = SyncController(service)

    @app.get("/")
    def index():
        return render_template_string(_ui_template())

    @app.get("/health")
    def health():
        state = service.state()
        return jsonify({"status": "ok", "state": _serialize(state)})

    @app.get("/state")
    def state():
        return jsonify(_serialize(service.state()))

    @app.get("/source/health")
    def source_health():
        return jsonify(service.client.health())

    @app.get("/source/meta")
    def source_meta():
        return jsonify(service.client.meta())

    @app.post("/sync")
    def sync():
        payload = sync_controller.start(force_reconcile=True)
        return jsonify(payload), (202 if payload.get("accepted") else 200)

    @app.post("/sync/start")
    def sync_start():
        payload = sync_controller.start(force_reconcile=True)
        return jsonify(payload), (202 if payload.get("accepted") else 200)

    @app.post("/sync/quick")
    def sync_quick():
        payload = sync_controller.start(force_reconcile=False)
        return jsonify(payload), (202 if payload.get("accepted") else 200)

    @app.get("/sync/status")
    def sync_status():
        return jsonify(sync_controller.status())

    @app.get("/runs/latest")
    def latest_run():
        state = service.state()
        return jsonify(
            {
                "checkpoint": state.checkpoint,
                "last_synced_at": state.last_synced_at.isoformat() if state.last_synced_at else None,
                "last_run_folder": str(state.last_run_folder) if state.last_run_folder else None,
                "last_run_count": state.last_run_count,
                "last_success_count": state.last_success_count,
                "last_failure_count": state.last_failure_count,
            }
        )

    @app.get("/runs/recent")
    def recent_runs():
        limit = max(min(int(request.args.get("limit", 10)), 100), 1)
        return jsonify({"items": _serialize(service.recent_runs(limit=limit))})

    @app.get("/index/summary")
    def index_summary():
        return jsonify(_serialize(service.index_summary()))

    @app.get("/index/notes")
    def index_notes():
        deleted_arg = request.args.get("deleted")
        deleted: Optional[bool] = None
        if deleted_arg in {"0", "1"}:
            deleted = deleted_arg == "1"
        limit = max(min(int(request.args.get("limit", 100)), 500), 1)
        offset = max(int(request.args.get("offset", 0)), 0)
        items = service.list_notes_any(deleted_on_app=deleted, limit=limit, offset=offset)
        return jsonify({"items": _serialize(items), "deleted_on_app": deleted})

    @app.get("/index/notes/<uuid>")
    def index_note_detail(uuid: str):
        note = service.get_index_note(uuid)
        if note is None:
            return jsonify({"error": "note not found"}), 404
        return jsonify(_serialize(note))

    @app.get("/index/search")
    def index_search():
        query = (request.args.get("q") or "").strip()
        if not query:
            return jsonify({"error": "q is required", "items": []}), 400

        deleted_arg = request.args.get("deleted")
        deleted_filter = None
        if deleted_arg in {"0", "1"}:
            deleted_filter = deleted_arg == "1"

        limit = max(min(int(request.args.get("limit", 100)), 500), 1)
        offset = max(int(request.args.get("offset", 0)), 0)
        items = service.search_index_notes(
            query=query,
            deleted_on_app=deleted_filter,
            limit=limit,
            offset=offset,
        )
        return jsonify({"items": _serialize(items), "query": query})

    @app.get("/backup/<uuid>/download")
    def download_backup_file(uuid: str):
        file_path = service.get_backup_file(uuid)
        if file_path is None:
            return jsonify({"error": "backup file not found", "uuid": uuid}), 404
        return send_file(file_path, as_attachment=True, download_name=file_path.name)

    @app.post("/backup/<uuid>/purge")
    def purge_backup_file(uuid: str):
        result = service.purge_deleted_backup(uuid)
        status = result.get("status")
        if status == "deleted":
            return jsonify(result)
        if status == "not_found":
            return jsonify(result), 404
        if status == "rejected":
            return jsonify(result), 409
        return jsonify(result), 400

    @app.get("/notes/<uuid>/thumbnail")
    def note_thumbnail(uuid: str):
        try:
            payload, content_type = service.get_note_thumbnail(uuid)
        except urllib_error.HTTPError as exc:
            return jsonify({"error": f"upstream returned {exc.code}", "uuid": uuid}), exc.code
        except Exception as exc:
            return jsonify({"error": str(exc), "uuid": uuid}), 502
        return payload, 200, {"Content-Type": content_type}

    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="Run remote incremental backup + web UI")
    parser.add_argument("--config", help="Path to YAML config", default="config/services.yml")
    parser.add_argument("--note-api-url", help="Note API base URL", default=None)
    parser.add_argument("--token", help="Bearer token for Note API", default=None)
    parser.add_argument("--destination", help="Destination backup directory", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--refresh-seconds", type=int, default=None)
    parser.add_argument("--full-scan-hours", type=int, default=None)
    args = parser.parse_args()

    config = load_yaml_config(Path(args.config))
    service_cfg = get_service_config(config, "backup_ui")

    enabled = bool(service_cfg.get("enabled", True))
    if not enabled:
        print("backup service is disabled by config")
        return 0

    note_api_url = args.note_api_url if args.note_api_url is not None else service_cfg.get("note_api_url")
    if not note_api_url:
        raise RuntimeError("note_api_url is required (CLI --note-api-url or config.services.backup_ui.note_api_url)")

    token = args.token if args.token is not None else service_cfg.get("token")
    destination_setting = args.destination if args.destination is not None else service_cfg.get("destination")
    destination_setting = _normalize_windows_path_setting(destination_setting)
    host = args.host if args.host is not None else service_cfg.get("host", "127.0.0.1")
    port = args.port if args.port is not None else int(service_cfg.get("port", 5056))
    refresh_seconds = (
        args.refresh_seconds if args.refresh_seconds is not None else int(service_cfg.get("refresh_seconds", 60))
    )
    full_scan_hours = (
        args.full_scan_hours
        if args.full_scan_hours is not None
        else int(service_cfg.get("full_scan_interval_hours", 6))
    )

    destination_dir = Path(destination_setting) if destination_setting else Path.cwd() / "incremental_backup"

    service = IncrementalBackupService(
        destination_dir=destination_dir,
        note_api_base_url=note_api_url,
        note_api_token=token,
        refresh_seconds=refresh_seconds,
        full_scan_interval_hours=full_scan_hours,
    )
    service.start()

    app = create_app(service)
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
