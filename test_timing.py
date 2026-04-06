#!/usr/bin/env python3
"""Test worker thread with timing analysis."""
from pathlib import Path
from core.storage.sqlite_notes import SQLiteNoteService  
from utils.note_service import create_app as create_note_app
from core.backup.incremental_service import IncrementalBackupService
import time

note_service = SQLiteNoteService(Path("test_data/db/Storage.sqlite"), refresh_seconds=60)
note_service.start()
note_app = create_note_app(note_service, source_root=Path("test_data"), auth_token="tt")

backup_service = IncrementalBackupService(
    destination_dir=Path("test_output_cli/worker_timing_test"),
    note_api_base_url="http://127.0.0.1:5999",
    note_api_token="tt",
    refresh_seconds=1,  # 1 second refresh for faster testing
    full_scan_interval_hours=999,
)

call_times = []

class TimingClient:
    def __init__(self, note_client):
        self.note_client = note_client
    def list_changes_since(self, since, limit, offset):
        t0 = time.time()
        r = self.note_client.get(f"/changes-since?since={since}&limit={limit}&offset={offset}", 
                                headers={"Authorization":"Bearer tt"})
        δt = time.time() - t0
        call_times.append(('list_changes_since', t0, δt))
        return r.get_json()
    def list_notes(self, limit, offset):
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
backup_service.client = TimingClient(note_client)

print("Starting service with 1-sec refresh...")
t_start = time.time()
backup_service.start()

print(f"Waiting 5 seconds for syncs...")
time.sleep(5)

print(f"Stopping...")
backup_service.stop()
note_service.stop()

# Analyze
t_elapsed = time.time() - t_start
print(f"\nTotal elapsed: {t_elapsed:.1f}s")
print(f"Sync calls: {len(call_times)}")
for i, (method, t, δt) in enumerate(call_times):
    print(f"  {i+1}. {method} at t={t-t_start:.2f}s (took {δt*1000:.0f}ms)")

print(f"\nExpected 4-5+ calls (initial + loop with 1-sec interval over 5s)")
print(f"Result: {'PASS' if len(call_times) >= 3 else 'FAIL'}")
