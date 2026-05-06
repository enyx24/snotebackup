import sqlite3
import sys
from typing import Dict, Optional, Tuple
from utils.load_config import _load_client_config
from pathlib import Path
from utils.log import get_logger

logger = get_logger(__name__)

class AppDBReader():
    def __init__(self, sql_file_path: Path):
        # Read only mode to prevent any accidental modifications to the database
        self.connection = sqlite3.connect(f"file:{sql_file_path}?mode=ro", uri=True)
        self.sql_file_path = sql_file_path
        if not self.sql_file_path.exists():
            raise FileNotFoundError(f"SQL file not found at path: {self.sql_file_path}")

    def _read_sql_file(self) -> str:
        with open(self.sql_file_path, 'r') as file:
            sql_query = file.read()
        return sql_query

    # Helper function to study the database schema
    def _list_tables(self):
        cursor = self.connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print("Database Schema:")
        for table in tables:
            print(f"Table: {table[0]}")
        return tables

    def _list_columns(self, table_name: str):
        cursor = self.connection.cursor()
        cursor.execute(f"PRAGMA table_info('{table_name}');")
        columns = cursor.fetchall()
        print(f"Columns in {table_name}:")
        for column in columns:
            print(f" - {column[1]} ({column[2]})")
        return columns
    
    def _print_schema(self):
        tables = self._list_tables()
        for table in tables:
            self._list_columns(table[0])

    def _print_sample_data(self, table_name: str, columns: list, limit: int = 5):
        cursor = self.connection.cursor()
        if len(columns) > 1:
            column_names = ", ".join([col for col in columns])
        else:
            column_names = columns[0]
        cursor.execute(f"SELECT {column_names} FROM {table_name} LIMIT {limit};")
        rows = cursor.fetchall()
        print(f"Sample data from {table_name}:")
        stdout_encoding = sys.stdout.encoding or "utf-8"
        for row in rows:
            safe_row = tuple("" if value is None else str(value) for value in row)
            safe_text = str(safe_row).encode(stdout_encoding, errors="replace").decode(stdout_encoding, errors="replace")
            print(safe_text)
        return rows
    
    

    def close_connection(self):
        self.connection.close()

    # ---------- Sync methods ----------
    def fetch_note_index(self) -> Dict[str, Tuple[int, dict]]:
        """
        Returns mapping uuid -> (lastModifiedAt, row_dict).
        Queries NoteDB for sync purposes.
        """
        cursor = self.connection.cursor()
        cursor.row_factory = sqlite3.Row
        
        # Discover available columns
        cursor.execute("PRAGMA table_info('NoteDB')")
        schema_cols = {r[1] for r in cursor.fetchall()}
        
        wanted_cols = ["UUID", "LastModifiedAt", "FilePath", "DeletedAt", "ThumbnailPath", 
                       "CoverThumbnailPathRect", "ThumbnailPathCropped"]
        available_cols = [c for c in wanted_cols if c in schema_cols]
        
        select_cols = ", ".join(available_cols) if available_cols else "UUID, LastModifiedAt"
        cursor.execute(f"SELECT {select_cols} FROM NoteDB")
        rows = cursor.fetchall()
        
        out = {}
        for r in rows:
            uuid = r["UUID"]
            last = int(r["LastModifiedAt"] or 0)
            rowd = {k: r[k] for k in available_cols if k in r.keys()}
            out[uuid] = (last, rowd)
        
        return out

    def fetch_textsearch_by_uuid(self, uuid: str) -> Optional[dict]:
        """
        Fetch textsearch record by UUID. Returns dict or None.
        """
        cursor = self.connection.cursor()
        cursor.row_factory = sqlite3.Row
        cursor.execute("SELECT * FROM TextSearchDB WHERE UUID = ?", (uuid,))
        row = cursor.fetchone()
        
        if not row:
            return None
        return {k: row[k] for k in row.keys()}


if __name__ == "__main__":
    config = _load_client_config("config/services.yaml")
    db_path = config['db']
    sql_file_path = Path(db_path)
    
    app_db_reader = AppDBReader(sql_file_path)
    
    rows = app_db_reader._print_sample_data("TextSearchDB", ["PDFTextContents", "StrippedContent", "HWTextContent"], limit=100)
    print(f"Fetched {len(rows)} rows.")