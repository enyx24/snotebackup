from pathlib import Path
from core.storage.sqlite_notes import SQLiteNoteService  
from utils.note_service import create_app as create_note_app
from core.backup.incremental_service import IncrementalBackupService
import time

note_service = SQLiteNoteService(Path("test_data/db/Storage.sqlite"), refresh_seconds=60)
note_service.start()
note_app = create_note_app(note_service, source_root=Path("test_data"), auth_token="tt")

backup_service = IncrementalBackupService(
    destination_dir=Path("test_output_cli/worker_test"),
    note_api_base_url="http://127.0.0.1:5999",
    note_api_token="tt",
    refresh_seconds=2,
    full_scan_interval_hours=999,
)

class LocalClient:
    def __init__(self, note_client):
        self.note_client = note_client
        self.call_count = 0
    def list_changes_since(self, since, limit, offset):
        self.call_count += 1
        print(f"[list_changes_since] call #{self.call_count}, since={since}")
        r = self.note_client.get(f"/changes-since?since={since}&limit={limit}&offset={offset}", headers={"Authorization":"Bearer tt"})
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
client = LocalClient(note_client)
backup_service.client = client

print("Starting service with 2-sec refresh...")
backup_service.start()

print("Wait 8 seconds...")
for i in range(8):
    time.sleep(1)
    print(f"[{i+1}s] call_count={client.call_count}, checkpoint={backup_service._checkpoint}")

print("Stopping...")
backup_service.stop()
note_service.stop()
print("Done")
