from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
import traceback

from core.backup.index_store import BackupIndexStore
from core.backup.logging import create_run_artifacts, write_csv, write_metadata
from core.backup.note_api_client import NoteApiClient
from core.model.models import ConversionResult, IncrementalBackupResult, IncrementalBackupState, RunArtifacts


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _marker(note: Dict) -> int:
    candidates: List[int] = []
    for key in ("last_db_updated_at", "modified_at", "created_at"):
        value = note.get(key)
        if value is None:
            continue
        try:
            marker = int(value)
        except Exception:
            continue
        if marker > 0:
            candidates.append(marker)
    return max(candidates) if candidates else 0


class IncrementalBackupService:
    def __init__(
        self,
        destination_dir: Path,
        note_api_base_url: str,
        note_api_token: Optional[str] = None,
        refresh_seconds: int = 60,
        page_size: int = 250,
        full_scan_interval_hours: int = 6,
        state_file: str = ".snotebackup_state.json",
        index_file: str = ".snotebackup_index.sqlite",
    ):
        self.destination_dir = Path(destination_dir).resolve()
        self.refresh_seconds = max(int(refresh_seconds), 1)
        self.page_size = max(int(page_size), 1)
        self.full_scan_interval_hours = max(int(full_scan_interval_hours), 1)
        self.state_path = self.destination_dir / state_file
        self.index_path = self.destination_dir / index_file
        self.client = NoteApiClient(base_url=note_api_base_url, token=note_api_token)
        self.index_store = BackupIndexStore(self.index_path)

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._checkpoint = 0
        self._last_synced_at: Optional[datetime] = None
        self._last_full_scan_at: Optional[datetime] = None
        self._last_run_folder: Optional[Path] = None
        self._last_run_count = 0
        self._last_success_count = 0
        self._last_failure_count = 0
        self._last_run_artifacts: Optional[RunArtifacts] = None

        self._load_state()

    def _log(self, message: str) -> None:
        timestamp = _utc_now().isoformat()
        print(f"[{timestamp}] [incremental-backup] {message}", flush=True)

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return

        self._checkpoint = int(payload.get("checkpoint", 0) or 0)
        self._last_synced_at = _parse_iso(payload.get("last_synced_at"))
        self._last_full_scan_at = _parse_iso(payload.get("last_full_scan_at"))
        run_folder = payload.get("last_run_folder")
        self._last_run_folder = Path(run_folder) if run_folder else None
        self._last_run_count = int(payload.get("last_run_count", 0) or 0)
        self._last_success_count = int(payload.get("last_success_count", 0) or 0)
        self._last_failure_count = int(payload.get("last_failure_count", 0) or 0)

    def _save_state(self) -> None:
        self.destination_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "checkpoint": self._checkpoint,
            "last_synced_at": self._last_synced_at.isoformat() if self._last_synced_at else None,
            "last_full_scan_at": self._last_full_scan_at.isoformat() if self._last_full_scan_at else None,
            "last_run_folder": str(self._last_run_folder) if self._last_run_folder else None,
            "last_run_count": self._last_run_count,
            "last_success_count": self._last_success_count,
            "last_failure_count": self._last_failure_count,
        }
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def start(self) -> None:
        self._stop_event.clear()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="incremental-backup", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        try:
            self._log("worker starting immediate sync")
            self.sync_now()
        except Exception:
            self._log("initial sync failed; worker will continue")
            traceback.print_exc()

        while not self._stop_event.wait(self.refresh_seconds):
            try:
                self._log("worker running scheduled sync")
                self.sync_now()
            except Exception:
                self._log("scheduled sync failed; worker will retry next cycle")
                traceback.print_exc()
                continue

    def _download_to_destination(self, uuid: str) -> ConversionResult:
        started_at = _utc_now()
        output_path = self.destination_dir / f"{uuid}.sdocx"
        successful = False
        error = None

        try:
            data = self.client.download_note(uuid)
            output_path.write_bytes(data)
            successful = True
        except Exception as exc:
            error = str(exc)

        ended_at = _utc_now()
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)
        return ConversionResult(
            hash_name=uuid,
            folder_path=Path(uuid),
            exported_name=output_path.name,
            output_path=output_path,
            successful=successful,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            error=error,
        )

    def _update_index_from_sync(self, note: Dict, now: datetime, conversion: Optional[ConversionResult]) -> None:
        backup_artifact = str(conversion.output_path) if (conversion and conversion.successful) else None
        self.index_store.upsert_note(note=note, now_iso=now.isoformat(), backup_artifact=backup_artifact)

    def _run_full_scan_reconcile(
        self,
        now: datetime,
        processed_uuids: set[str],
        force_repair: bool = False,
    ) -> tuple[List[ConversionResult], int]:
        repair_results: List[ConversionResult] = []
        active_uuids = set()
        max_seen_marker = 0
        offset = 0

        while True:
            payload = self.client.list_notes(limit=self.page_size, offset=offset)
            items = payload.get("items") or []
            if not items:
                break

            for note in items:
                uuid = note.get("uuid")
                if not uuid:
                    continue

                remote_marker = _marker(note)
                if remote_marker > max_seen_marker:
                    max_seen_marker = remote_marker

                deleted_on_app = bool(note.get("deleted_on_app") or note.get("deleted_status"))
                conversion = None

                if not deleted_on_app:
                    active_uuids.add(uuid)

                    if force_repair and uuid not in processed_uuids:
                        indexed = self.index_store.get_note(uuid)

                        indexed_marker = 0
                        if indexed is not None:
                            try:
                                indexed_marker = int(indexed.get("last_marker") or 0)
                            except Exception:
                                indexed_marker = 0

                        artifact_exists = False
                        if indexed is not None:
                            last_backup_artifact = indexed.get("last_backup_artifact")
                            if last_backup_artifact:
                                artifact_exists = Path(last_backup_artifact).exists()
                        if not artifact_exists:
                            artifact_exists = (self.destination_dir / f"{uuid}.sdocx").exists()

                        repair_needed = (
                            indexed is None
                            or bool(indexed.get("deleted_on_app"))
                            or remote_marker > indexed_marker
                            or not artifact_exists
                        )

                        if repair_needed:
                            conversion = self._download_to_destination(uuid)
                            processed_uuids.add(uuid)
                            repair_results.append(conversion)

                self._update_index_from_sync(note, now=now, conversion=conversion)

            if len(items) < self.page_size:
                break
            offset += self.page_size

        if active_uuids:
            self.index_store.reconcile_full_scan(active_uuids=active_uuids)

        self._last_full_scan_at = now
        return repair_results, max_seen_marker

    def _should_full_scan(self, now: datetime) -> bool:
        if self._last_full_scan_at is None:
            return True
        return now - self._last_full_scan_at >= timedelta(hours=self.full_scan_interval_hours)

    def sync_now(self, force_reconcile: bool = False) -> IncrementalBackupResult:
        started_at = _utc_now()
        with self._lock:
            checkpoint_before = self._checkpoint
            next_checkpoint = checkpoint_before
            changed: List[Dict] = []
            offset = 0
            mode = "force-reconcile" if force_reconcile else "incremental"
            self._log(
                f"sync start mode={mode} checkpoint={checkpoint_before} page_size={self.page_size}"
            )

            while True:
                payload = self.client.list_changes_since(since=checkpoint_before, limit=self.page_size, offset=offset)
                batch = payload.get("items") or []
                self._log(f"delta page offset={offset} items={len(batch)}")
                if not batch:
                    break
                changed.extend(batch)
                if len(batch) < self.page_size:
                    break
                offset += self.page_size

        results: List[ConversionResult] = []
        processed_uuids: set[str] = set()
        self.destination_dir.mkdir(parents=True, exist_ok=True)

        for note in changed:
            marker = _marker(note)
            if marker > next_checkpoint:
                next_checkpoint = marker

            uuid = note.get("uuid") or ""
            deleted_on_app = bool(note.get("deleted_on_app") or note.get("deleted_status"))

            conversion = None
            if (not deleted_on_app) and uuid and (uuid not in processed_uuids):
                conversion = self._download_to_destination(uuid)
                processed_uuids.add(uuid)

            if conversion and conversion.successful:
                results.append(conversion)

            self._update_index_from_sync(note, now=_utc_now(), conversion=conversion)

        run_artifacts = None
        success_count = 0
        failure_count = 0

        now = _utc_now()
        repair_results: List[ConversionResult] = []
        full_scan_max_marker = 0
        try:
            if force_reconcile or self._should_full_scan(now):
                repair_results, full_scan_max_marker = self._run_full_scan_reconcile(
                    now=now,
                    processed_uuids=processed_uuids,
                    force_repair=force_reconcile,
                )
        except Exception:
            pass

        if repair_results:
            results.extend(repair_results)

        if full_scan_max_marker > next_checkpoint:
            next_checkpoint = full_scan_max_marker

        if results:
            run_artifacts = create_run_artifacts(self.destination_dir)
            success_count, failure_count = write_csv(run_artifacts.csv_path, results)
            write_metadata(
                run_artifacts.metadata_path,
                started_at=started_at,
                ended_at=_utc_now(),
                blob_count=len(results),
                success_count=success_count,
            )

        with self._lock:
            if next_checkpoint < checkpoint_before:
                next_checkpoint = checkpoint_before

            self._checkpoint = next_checkpoint
            self._last_synced_at = now
            self._last_run_folder = run_artifacts.run_folder if run_artifacts else None
            self._last_run_count = len(changed) + len(repair_results)
            self._last_success_count = success_count
            self._last_failure_count = failure_count
            self._last_run_artifacts = run_artifacts

            self._save_state()

        self._log(
            f"sync done changed={len(changed)} repaired={len(repair_results)} "
            f"checkpoint_before={checkpoint_before} checkpoint_after={next_checkpoint} "
            f"success={success_count} failure={failure_count}"
        )

        return IncrementalBackupResult(
            checkpoint_before=checkpoint_before,
            checkpoint_after=next_checkpoint,
            changed_count=len(changed),
            success_count=success_count,
            failure_count=failure_count,
            started_at=started_at,
            ended_at=now,
            run_artifacts=run_artifacts,
        )

    def state(self) -> IncrementalBackupState:
        with self._lock:
            return IncrementalBackupState(
                checkpoint=self._checkpoint,
                last_synced_at=self._last_synced_at,
                last_run_folder=self._last_run_folder,
                last_run_count=self._last_run_count,
                last_success_count=self._last_success_count,
                last_failure_count=self._last_failure_count,
            )

    def index_summary(self) -> Dict[str, int]:
        return self.index_store.summary()

    def list_index_notes(self, deleted_on_app: bool, limit: int = 100, offset: int = 0) -> List[Dict]:
        return self.index_store.list_notes_any(deleted_on_app=deleted_on_app, limit=limit, offset=offset)

    def list_notes_any(self, deleted_on_app: Optional[bool], limit: int = 100, offset: int = 0) -> List[Dict]:
        return self.index_store.list_notes_any(deleted_on_app=deleted_on_app, limit=limit, offset=offset)

    def search_index_notes(
        self,
        query: str,
        deleted_on_app: Optional[bool],
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        return self.index_store.search_notes(
            query=query,
            deleted_on_app=deleted_on_app,
            limit=limit,
            offset=offset,
        )

    def get_backup_file(self, uuid: str) -> Optional[Path]:
        artifact = self.index_store.get_last_backup_artifact(uuid)
        if artifact:
            path = Path(artifact)
            if path.exists() and path.is_file():
                return path

        fallback = self.destination_dir / f"{uuid}.sdocx"
        if fallback.exists() and fallback.is_file():
            return fallback
        return None

    def get_index_note(self, uuid: str) -> Optional[Dict]:
        return self.index_store.get_note(uuid)

    def purge_deleted_backup(self, uuid: str) -> Dict:
        note = self.index_store.get_note(uuid)
        if note is None:
            return {"status": "not_found", "uuid": uuid, "deleted_files": []}
        if not note.get("deleted_on_app"):
            return {"status": "rejected", "reason": "note is still active_on_app", "uuid": uuid, "deleted_files": []}

        deleted_files: List[str] = []
        for candidate in note.get("backup_artifacts") or []:
            path = Path(candidate)
            if path.exists() and path.is_file():
                try:
                    path.unlink()
                    deleted_files.append(str(path))
                except Exception:
                    continue

        fallback = self.destination_dir / f"{uuid}.sdocx"
        if fallback.exists() and fallback.is_file():
            try:
                fallback.unlink()
                deleted_files.append(str(fallback))
            except Exception:
                pass

        self.index_store.delete_note(uuid)
        return {"status": "deleted", "uuid": uuid, "deleted_files": deleted_files}

    def get_note_thumbnail(self, uuid: str) -> tuple[bytes, str]:
        return self.client.get_raw(f"/notes/{uuid}/thumbnail")

    def recent_runs(self, limit: int = 10) -> List[dict]:
        safe_limit = max(int(limit), 1)
        self.destination_dir.mkdir(parents=True, exist_ok=True)

        run_folders = sorted(
            [path for path in self.destination_dir.glob("backup_run_*") if path.is_dir()],
            key=lambda item: item.name,
            reverse=True,
        )

        runs: List[dict] = []
        for run_folder in run_folders[:safe_limit]:
            metadata_path = run_folder / "metadata.json"
            csv_path = run_folder / "results.csv"

            metadata = {}
            if metadata_path.exists() and metadata_path.is_file():
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except Exception:
                    metadata = {}

            runs.append(
                {
                    "run_folder": str(run_folder),
                    "metadata_path": str(metadata_path) if metadata_path.exists() else None,
                    "results_path": str(csv_path) if csv_path.exists() else None,
                    "time_started": metadata.get("time_started"),
                    "time_done": metadata.get("time_done"),
                    "blob_count": metadata.get("blob_count"),
                    "successful_converted_count": metadata.get("successful_converted_count"),
                    "failed_count": metadata.get("failed_count"),
                }
            )

        return runs
