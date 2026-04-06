#!/usr/bin/env python3
"""Regression test: worker continues syncing after first checkpoint advance."""

from pathlib import Path
import shutil
import time

from core.backup.incremental_service import IncrementalBackupService


class SequencedClient:
    def __init__(self):
        self.calls = []

    def list_changes_since(self, since, limit, offset):
        self.calls.append((since, limit, offset, time.time()))
        if offset != 0:
            return {"items": []}

        if since < 100:
            return {
                "items": [
                    {
                        "uuid": "note-first",
                        "title": "first",
                        "deleted_on_app": False,
                        "deleted_status": 0,
                        "last_db_updated_at": 100,
                        "modified_at": 100,
                        "created_at": 10,
                    }
                ]
            }

        if since < 200:
            return {
                "items": [
                    {
                        "uuid": "note-second",
                        "title": "second",
                        "deleted_on_app": False,
                        "deleted_status": 0,
                        "last_db_updated_at": 50,
                        "modified_at": 200,
                        "created_at": 20,
                    }
                ]
            }

        return {"items": []}

    def list_notes(self, limit, offset):
        return {"items": []}

    def download_note(self, uuid):
        return f"content-for-{uuid}".encode("utf-8")

    def health(self):
        return {"status": "ok"}

    def meta(self):
        return {"supports_download": True}

    def get_raw(self, path):
        return b"", "application/octet-stream"


def main() -> int:
    out_dir = Path("test_output_cli/worker_post_first_sync")
    shutil.rmtree(out_dir, ignore_errors=True)

    service = IncrementalBackupService(
        destination_dir=out_dir,
        note_api_base_url="http://127.0.0.1:5999",
        note_api_token="tt",
        refresh_seconds=1,
        full_scan_interval_hours=999,
    )
    client = SequencedClient()
    service.client = client

    service.start()
    time.sleep(4)
    service.stop()

    checkpoint = service.state().checkpoint
    first_file = out_dir / "note-first.sdocx"
    second_file = out_dir / "note-second.sdocx"

    print("checkpoint:", checkpoint)
    print("calls:", len(client.calls))
    print("first_file_exists:", first_file.exists())
    print("second_file_exists:", second_file.exists())

    passed = checkpoint >= 200 and first_file.exists() and second_file.exists()
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
