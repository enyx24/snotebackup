#!/usr/bin/env python3
"""Test that worker thread repeatedly syncs without blocking."""
from pathlib import Path
from core.storage.sqlite_notes import SQLiteNoteService  
from utils.note_service import create_app as create_note_app
from core.backup.incremental_service import IncrementalBackupService
import time
import threading

note_service = SQLiteNoteService(Path("test_data/db/Storage.sqlite"), refresh_seconds=60)
note_service.start()
note_app = create_note_app(note_service, source_root=Path("test_data"), auth_token="tt")

backup_service = IncrementalBackupService(
    destination_dir=Path("test_output_cli/worker_test2"),
    note_api_base_url="http://127.0.0.1:5999",
    note_api_token="tt",
    refresh_seconds=2,  # 2 second refresh for testing
    full_scan_interval_hours=999,
)

call_log = []

class TestClient:
    def __init__(self, note_client):
        self.note_client = note_client
    def list_changes_since(self, since, limit, offset):
        call_log.append(('list_changes_since', since, offset, time.time()))
        r = self.note_client.get(f"/changes-since?since={since}&limit={limit}&offset={offset}", 
                                headers={"Authorization":"Bearer tt"})
        return r.get_json()
    def list_notes(self, limit, offset):
        call_log.append(('list_notes', offset, time.time()))
        return {"items": []}
    def download_note(self, u):
        return f"mock-content-for-{u}".encode("utf-8")
    def health(self):
        return self.note_client.get("/health").get_json()
    def meta(self):
        return self.note_client.get("/meta", headers={"Authorization":"Bearer tt"}).get_json()
    def get_raw(self, path):
        r = self.note_client.get(path, headers={"Authorization":"Bearer tt"})
        return r.data, r.headers.get("Content-Type", "application/octet-stream")

note_client = note_app.test_client()
backup_service.client = TestClient(note_client)

print("Starting service with 2-sec refresh...")
backup_service.start()

print("Waiting 8 seconds for worker to sync...")
time.sleep(8)

print(f"Stopping... (Call log has {len(call_log)} entries)")
backup_service.stop()
note_service.stop()

# Analyze call log
print("\nCall log:")
for i, entry in enumerate(call_log):
    print(f"  {i+1}. {entry[0]} at t={entry[-1]:.1f}s")

# Check if we have multiple sync cycles
sync_count = sum(1 for e in call_log if e[0] == 'list_changes_since')
print(f"\nTotal list_changes_since calls: {sync_count}")
print(f"Expected: 4-5 calls (initial + 3-4 from 2-sec intervals in 8s)")
print(f"PASS" if sync_count >= 3 else f"FAIL - worker thread not syncing repeatedly")
