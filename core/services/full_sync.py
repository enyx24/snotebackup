import json
import tempfile
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

from utils.load_config import _load_client_config
from utils.log import get_logger

from core.backup.converter import convert_blob
from core.models.backup import BlobCandidate
from core.db.app_db import AppDBReader
from core.db.client_db import SyncCheckpointDB

logger = get_logger(__name__)


class FullSyncService:
    """
    Full sync implementation (client-side). Behavior:
    - fetch server index from {note_api_url}/full_index (expects JSON list of {uuid, lastModifiedAt})
    - read local NoteDB and TextSearchDB from app sqlite via AppDBReader
    - decide which notes to upload (missing on server or local.lastModifiedAt > server)
    - for each note: create .sdocx (via convert_blob), collect thumbnail and textsearch rows, POST multipart to {note_api_url}/upload_note
    - store checkpoint in a small sqlite file via SyncCheckpointDB
    """

    def __init__(self, cfg_path: str = "config/services.yaml"):
        cfg = _load_client_config(cfg_path)
        self.client_cfg = cfg.get("services", {}).get("client", {}) if isinstance(cfg, dict) else cfg
        self.server_cfg = cfg.get("services", {}).get("server", {}) if isinstance(cfg, dict) else {}
        self.app_db_path = Path(self.client_cfg.get("db"))
        self.source_dir = Path(self.client_cfg.get("source"))
        self.note_api_url = self.server_cfg.get("note_api_url") or self.client_cfg.get("host")
        self.token = self.client_cfg.get("token") or self.server_cfg.get("token")
        
        # Use DB layer classes
        self.app_db = AppDBReader(self.app_db_path)
        self.checkpoint_db = SyncCheckpointDB()

    # ---------- server interactions ----------
    def fetch_server_index(self) -> Dict[str, int]:
        """
        GET {note_api_url}/full_index
        Expect JSON: [{"uuid": "...", "lastModifiedAt": 123456789}, ...]
        If server not reachable, return empty dict.
        """
        if not self.note_api_url:
            logger.warning("note_api_url not configured; assuming empty server index")
            return {}

        url = f"{self.note_api_url.rstrip('/')}/full_index"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return {item["uuid"]: int(item.get("lastModifiedAt", 0)) for item in data}
        except Exception as exc:
            logger.warning("Failed to fetch server index: %s", exc)
            return {}

    def upload_note_package(self, uuid: str, last_modified: int, sdocx_path: Path, thumbnail_path: Optional[Path], textsearch_payload: Optional[dict]) -> bool:
        """
        POST multipart to {note_api_url}/upload_note
        fields:
          uuid, last_modified, sdocx file, optional thumbnail file, optional textsearch json
        Returns True on 2xx.
        """
        if not self.note_api_url:
            logger.info("No server URL configured; skipping upload for %s", uuid)
            return True

        url = f"{self.note_api_url.rstrip('/')}/upload_note"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}

        files = {}
        try:
            files["sdocx"] = ("note.sdocx", open(sdocx_path, "rb"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        except Exception as exc:
            logger.error("Cannot open sdocx for %s: %s", uuid, exc)
            return False

        if thumbnail_path and thumbnail_path.exists():
            try:
                files["thumbnail"] = ("thumb", open(thumbnail_path, "rb"), "application/octet-stream")
            except Exception:
                logger.warning("Could not attach thumbnail for %s", uuid)

        data = {"uuid": uuid, "last_modified": str(last_modified)}
        if textsearch_payload is not None:
            data["textsearch"] = json.dumps(textsearch_payload, ensure_ascii=False)

        try:
            resp = requests.post(url, headers=headers, data=data, files=files, timeout=60)
            success = 200 <= resp.status_code < 300
            if not success:
                logger.error("Upload failed for %s: %s %s", uuid, resp.status_code, resp.text)
            return success
        except Exception as exc:
            logger.error("Upload exception for %s: %s", uuid, exc)
            return False
        finally:
            # close file handles
            for f in files.values():
                try:
                    f[1].close()
                except Exception:
                    pass

    # ---------- helpers ----------
    def _locate_note_folder(self, rowd: dict) -> Optional[Path]:
        """
        Try heuristics to find the folder containing the note blobs:
        - If FilePath is absolute and exists: if dir -> use it; if file -> parent
        - Else try self.source_dir / FilePath
        - Else try self.source_dir / UUID
        """
        fp = rowd.get("FilePath")
        # 1) absolute
        if fp:
            p = Path(fp)
            if p.exists():
                return p if p.is_dir() else p.parent
            # try join source_dir
            candidate = self.source_dir / fp
            if candidate.exists():
                return candidate if candidate.is_dir() else candidate.parent

        # 2) try UUID folder in source_dir
        uuid_guess = rowd.get("UUID")
        if uuid_guess:
            candidate = self.source_dir / uuid_guess
            if candidate.exists() and candidate.is_dir():
                return candidate

        # none found
        return None

    def _make_sdocx_for_folder(self, folder_path: Path) -> Optional[Path]:
        # use convert_blob (converts folder -> .sdocx)
        tmpdir = Path(tempfile.mkdtemp(prefix="fullsync_"))
        candidate = BlobCandidate(hash_name=folder_path.name, folder_path=folder_path)
        try:
            result = convert_blob(candidate, tmpdir)
            if result.successful:
                return result.output_path
            else:
                logger.error("Conversion failed for %s: %s", folder_path, result.error)
                return None
        except Exception as exc:
            logger.exception("Exception during conversion for %s: %s", folder_path, exc)
            return None

    # ---------- main run ----------
    def run(self):
        logger.info("Starting full sync")
        server_index = self.fetch_server_index()
        local_index = self.app_db.fetch_note_index()

        # decide to_upload: uuid not in server OR local.lastModifiedAt > server.lastModifiedAt
        to_upload = []
        for uuid, (local_last, rowd) in local_index.items():
            server_last = server_index.get(uuid)
            if server_last is None or local_last > server_last:
                to_upload.append((uuid, local_last, rowd))

        logger.info("Full sync decided to upload %d notes", len(to_upload))

        success_count = 0
        for uuid, last_mod, rowd in to_upload:
            logger.info("Preparing upload for %s", uuid)
            folder = self._locate_note_folder(rowd)
            if not folder:
                logger.warning("Could not locate folder for %s; skipping", uuid)
                continue

            sdocx = self._make_sdocx_for_folder(folder)
            if not sdocx:
                logger.warning("Could not create sdocx for %s; skipping", uuid)
                continue

            # thumbnail heuristics: try ThumbnailPath, CoverThumbnailPathRect, ThumbnailPathCropped
            thumbnail_path = None
            for key in ("ThumbnailPath", "CoverThumbnailPathRect", "ThumbnailPathCropped"):
                val = rowd.get(key)
                if val:
                    p = Path(val)
                    if not p.exists():
                        p = self.source_dir / val
                    if p.exists():
                        thumbnail_path = p
                        break

            textsearch = self.app_db.fetch_textsearch_by_uuid(uuid)

            ok = self.upload_note_package(uuid, last_mod, sdocx, thumbnail_path, textsearch)
            if ok:
                success_count += 1
            else:
                logger.warning("Upload failed for %s", uuid)

            # small delay to avoid hammering
            time.sleep(0.2)

        # update checkpoint
        ts = int(time.time())
        self.checkpoint_db.update_checkpoint(ts, success_count)
        logger.info("Full sync finished: uploaded %d notes", success_count)
        return {"uploaded": success_count, "decided": len(to_upload)}