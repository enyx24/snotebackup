import sqlite3
from pathlib import Path
from utils.log import get_logger

logger = get_logger(__name__)


class SyncCheckpointDB:
    """
    Manages sync checkpoint state in a local SQLite DB.
    Stores last_full_sync_at, last_sync_count, etc.
    """

    def __init__(self, checkpoint_db_path: Path = Path(".sync_checkpoint.db")):
        self.checkpoint_db = checkpoint_db_path
        self._ensure_db()

    def _ensure_db(self):
        """Initialize checkpoint DB schema if not exists."""
        conn = sqlite3.connect(str(self.checkpoint_db))
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS checkpoint (
                id INTEGER PRIMARY KEY,
                last_full_sync_at INTEGER,
                last_sync_count INTEGER
            )"""
        )
        # Ensure one row exists
        c.execute("SELECT COUNT(1) FROM checkpoint")
        if c.fetchone()[0] == 0:
            c.execute(
                "INSERT INTO checkpoint (last_full_sync_at, last_sync_count) VALUES (?, ?)",
                (0, 0),
            )
        conn.commit()
        conn.close()

    def get_checkpoint(self) -> dict:
        """Fetch current checkpoint state."""
        conn = sqlite3.connect(str(self.checkpoint_db))
        c = conn.cursor()
        c.execute("SELECT last_full_sync_at, last_sync_count FROM checkpoint WHERE id = 1")
        row = c.fetchone()
        conn.close()

        if row:
            return {"last_full_sync_at": row[0], "last_sync_count": row[1]}
        return {"last_full_sync_at": 0, "last_sync_count": 0}

    def update_checkpoint(self, last_full_sync_at: int, last_sync_count: int):
        """Update checkpoint state."""
        conn = sqlite3.connect(str(self.checkpoint_db))
        c = conn.cursor()
        c.execute(
            "UPDATE checkpoint SET last_full_sync_at = ?, last_sync_count = ? WHERE id = 1",
            (last_full_sync_at, last_sync_count),
        )
        conn.commit()
        conn.close()
        logger.debug(
            "Checkpoint updated: last_full_sync_at=%s, last_sync_count=%s",
            last_full_sync_at,
            last_sync_count,
        )
