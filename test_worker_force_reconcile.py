#!/usr/bin/env python3
"""Regression: force reconcile repairs missing backup when delta feed is empty."""

from pathlib import Path
import shutil

from core.backup.incremental_service import IncrementalBackupService


class ForceReconcileClient:
    def __init__(self):
        self.delta_calls = 0
        self.download_calls = []

    def list_changes_since(self, since, limit, offset):
        self.delta_calls += 1
        return {"items": []}

    def list_notes(self, limit, offset):
        if offset > 0:
            return {"items": []}
        return {
            "items": [
                {
                    "uuid": "force-note",
                    "title": "force",
                    "deleted_on_app": False,
                    "deleted_status": 0,
                    "last_db_updated_at": 123,
                    "modified_at": 123,
                    "created_at": 100,
                }
            ]
        }

    def download_note(self, uuid):
        self.download_calls.append(uuid)
        return f"payload-{uuid}".encode("utf-8")

    def health(self):
        return {"status": "ok"}

    def meta(self):
        return {"supports_download": True}

    def get_raw(self, path):
        return b"", "application/octet-stream"


def main() -> int:
    out_dir = Path("test_output_cli/worker_force_reconcile")
    shutil.rmtree(out_dir, ignore_errors=True)

    service = IncrementalBackupService(
        destination_dir=out_dir,
        note_api_base_url="http://127.0.0.1:5999",
        note_api_token="tt",
        refresh_seconds=60,
        full_scan_interval_hours=999,
    )
    client = ForceReconcileClient()
    service.client = client

    result = service.sync_now(force_reconcile=True)

    backup_file = out_dir / "force-note.sdocx"
    state = service.state()

    print("delta_calls:", client.delta_calls)
    print("download_calls:", client.download_calls)
    print("backup_exists:", backup_file.exists())
    print("checkpoint:", state.checkpoint)
    print("changed_count:", result.changed_count)

    passed = backup_file.exists() and client.download_calls.count("force-note") == 1 and state.checkpoint >= 123
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
