from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional

from core.model.models import (
    NoteDetail,
    NoteSummary,
    SearchHit,
    ServiceSnapshot,
    SQLiteColumnInfo,
    SQLiteTableInfo,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_readonly_uri(db_path: Path) -> str:
    return f"{db_path.resolve(strict=True).as_uri()}?mode=ro"


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _normalize_text(value: Optional[str]) -> str:
    return (value or "").strip()


def _coalesce_preview(*values: Optional[str]) -> Optional[str]:
    for value in values:
        text = _normalize_text(value)
        if text:
            return text
    return None


def _build_snippet(*values: Optional[str], max_length: int = 180) -> str:
    text = _coalesce_preview(*values) or ""
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def _pick_thumbnail_path(row: sqlite3.Row) -> Optional[str]:
    keys = set(row.keys())
    for key in (
        "ThumbnailPath",
        "ThumbnailPathCropped",
        "ThumbnailPathDarkMode",
        "ThumbnailPathDarkModeCropped",
        "HandWritingThumbnailPath",
        "CoverThumbnailPathSquare",
        "CoverThumbnailPathRect",
        "PageThumb",
    ):
        if key not in keys:
            continue
        text = _normalize_text(row[key])
        if text:
            return text
    return None


class SQLiteNoteRepository:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(_as_readonly_uri(self.db_path), uri=True)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def _fetchall(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(sql, params).fetchall()

    def _fetchone(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(sql, params).fetchone()

    def schema(self) -> List[SQLiteTableInfo]:
        rows = self._fetchall(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )

        tables: List[SQLiteTableInfo] = []
        with self.connect() as connection:
            for row in rows:
                table_name = row["name"]
                pragma_rows = connection.execute(
                    f"PRAGMA table_info({_quote_identifier(table_name)})"
                ).fetchall()
                columns = [
                    SQLiteColumnInfo(
                        name=column_row["name"],
                        data_type=column_row["type"],
                        notnull=bool(column_row["notnull"]),
                        default_value=column_row["dflt_value"],
                        is_primary_key=bool(column_row["pk"]),
                    )
                    for column_row in pragma_rows
                ]
                tables.append(SQLiteTableInfo(name=table_name, columns=columns))
        return tables

    def count_notes(self) -> int:
        row = self._fetchone("SELECT COUNT(1) AS total FROM NoteDB")
        return int(row["total"] if row else 0)

    def list_notes(self, limit: int = 100, offset: int = 0) -> List[NoteSummary]:
        rows = self._fetchall(
            """
            SELECT
                n.UUID,
                n.Title,
                n.RecommendedTitle,
                n.CategoryUUID,
                n.LastModifiedAt,
                n.lastDBUpdatedAt,
                n.CreatedAt,
                n.DeletedStatus,
                n.ThumbnailPath,
                n.FilePath,
                n.IsDownloaded,
                n.IsTextOnly,
                n.IsPdfTextSaved,
                n.StrippedContent,
                n.PDFTextContents,
                t.HWTextContent AS HWTextContent,
                t.StrippedContent AS SearchStrippedContent,
                t.PDFTextContents AS SearchPDFTextContents
            FROM NoteDB n
            LEFT JOIN TextSearchDB t ON t.UUID = n.UUID
            ORDER BY COALESCE(n.LastModifiedAt, n.CreatedAt, 0) DESC, n.Id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        return [self._row_to_summary(row) for row in rows]

    def list_changed_notes(self, since: int, limit: int = 500, offset: int = 0) -> List[NoteSummary]:
        rows = self._fetchall(
            """
            SELECT
                n.UUID,
                n.Title,
                n.RecommendedTitle,
                n.CategoryUUID,
                n.LastModifiedAt,
                n.lastDBUpdatedAt,
                n.CreatedAt,
                n.DeletedStatus,
                n.ThumbnailPath,
                n.FilePath,
                n.IsDownloaded,
                n.IsTextOnly,
                n.IsPdfTextSaved,
                n.StrippedContent,
                n.PDFTextContents,
                t.HWTextContent AS HWTextContent,
                t.StrippedContent AS SearchStrippedContent,
                t.PDFTextContents AS SearchPDFTextContents
            FROM NoteDB n
            LEFT JOIN TextSearchDB t ON t.UUID = n.UUID
            WHERE MAX(
                COALESCE(NULLIF(n.lastDBUpdatedAt, 0), 0),
                COALESCE(NULLIF(n.LastModifiedAt, 0), 0),
                COALESCE(NULLIF(n.CreatedAt, 0), 0)
            ) > ?
            ORDER BY MAX(
                COALESCE(NULLIF(n.lastDBUpdatedAt, 0), 0),
                COALESCE(NULLIF(n.LastModifiedAt, 0), 0),
                COALESCE(NULLIF(n.CreatedAt, 0), 0)
            ) DESC, n.Id DESC
            LIMIT ? OFFSET ?
            """,
            (since, limit, offset),
        )
        return [self._row_to_summary(row) for row in rows]

    def get_note(self, uuid: str) -> Optional[NoteDetail]:
        row = self._fetchone(
            """
            SELECT
                n.UUID,
                n.Title,
                n.RecommendedTitle,
                n.CategoryUUID,
                n.LastModifiedAt,
                n.lastDBUpdatedAt,
                n.CreatedAt,
                n.DeletedStatus,
                n.ThumbnailPath,
                n.FilePath,
                n.IsDownloaded,
                n.IsTextOnly,
                n.IsPdfTextSaved,
                n.StrippedContent,
                n.PDFTextContents,
                t.HWTextContent AS HWTextContent,
                t.StrippedContent AS SearchStrippedContent,
                t.PDFTextContents AS SearchPDFTextContents,
                n.DocumentType,
                n.DisplayContent,
                n.DisplayContentDark,
                n.Content,
                n.NoteName,
                n.LastAccessed,
                n.BookmarkList,
                n.Size,
                n.HandWritingThumbnailPath,
                n.CoverThumbnailPathRect,
                n.CoverThumbnailPathSquare,
                n.ThumbnailPathCropped,
                n.ThumbnailPathDarkMode,
                n.ThumbnailPathDarkModeCropped,
                n.PageThumb
            FROM NoteDB n
            LEFT JOIN TextSearchDB t ON t.UUID = n.UUID
            WHERE n.UUID = ?
            """,
            (uuid,),
        )
        if row is None:
            return None
        return self._row_to_detail(row)

    def search_notes(self, query: str, limit: int = 50, offset: int = 0) -> List[SearchHit]:
        term = _normalize_text(query)
        if not term:
            return []
        like = f"%{term}%"
        rows = self._fetchall(
            """
            SELECT
                n.UUID,
                n.Title,
                n.RecommendedTitle,
                n.LastModifiedAt,
                n.ThumbnailPath,
                n.StrippedContent,
                n.PDFTextContents,
                n.StrokeTextContents,
                n.DisplayContent,
                n.DisplayContentDark,
                n.Content,
                t.StrippedContent AS SearchStrippedContent,
                t.PDFTextContents AS SearchPDFTextContents,
                t.HWTextContent AS SearchHWTextContent
            FROM NoteDB n
            LEFT JOIN TextSearchDB t ON t.UUID = n.UUID
            WHERE
                lower(COALESCE(n.Title, '')) LIKE lower(?)
                OR lower(COALESCE(n.RecommendedTitle, '')) LIKE lower(?)
                OR lower(COALESCE(n.StrippedContent, '')) LIKE lower(?)
                OR lower(COALESCE(n.PDFTextContents, '')) LIKE lower(?)
                OR lower(COALESCE(n.DisplayContent, '')) LIKE lower(?)
                OR lower(COALESCE(n.DisplayContentDark, '')) LIKE lower(?)
                OR lower(COALESCE(n.Content, '')) LIKE lower(?)
                OR lower(COALESCE(t.StrippedContent, '')) LIKE lower(?)
                OR lower(COALESCE(t.PDFTextContents, '')) LIKE lower(?)
                OR lower(COALESCE(t.HWTextContent, '')) LIKE lower(?)
            ORDER BY COALESCE(n.LastModifiedAt, n.CreatedAt, 0) DESC, n.Id DESC
            LIMIT ? OFFSET ?
            """,
            (like, like, like, like, like, like, like, like, like, like, limit, offset),
        )

        hits: List[SearchHit] = []
        for row in rows:
            score = 0
            title = row["Title"]
            recommended = row["SearchStrippedContent"]
            if _normalize_text(title):
                score += 3
            if _normalize_text(recommended):
                score += 2
            snippet = _build_snippet(
                row["Title"],
                row["RecommendedTitle"],
                row["SearchStrippedContent"],
                row["SearchPDFTextContents"],
                row["SearchHWTextContent"],
                row["StrippedContent"],
                row["PDFTextContents"],
                row["StrokeTextContents"],
                row["DisplayContent"],
                row["DisplayContentDark"],
                row["Content"],
            )
            hits.append(
                SearchHit(
                    uuid=row["UUID"],
                    title=row["Title"],
                    modified_at=row["LastModifiedAt"],
                    thumbnail_path=_pick_thumbnail_path(row),
                    snippet=snippet,
                    score=score,
                    source="sqlite-text-search",
                )
            )
        return hits

    def get_thumbnail_candidates(self, uuid: str) -> List[str]:
        row = self._fetchone(
            """
            SELECT
                ThumbnailPath,
                ThumbnailPathCropped,
                ThumbnailPathDarkMode,
                ThumbnailPathDarkModeCropped,
                HandWritingThumbnailPath,
                CoverThumbnailPathRect,
                CoverThumbnailPathSquare,
                PageThumb
            FROM NoteDB
            WHERE UUID = ?
            """,
            (uuid,),
        )
        if row is None:
            return []
        candidates = [
            row["ThumbnailPath"],
            row["ThumbnailPathCropped"],
            row["ThumbnailPathDarkMode"],
            row["ThumbnailPathDarkModeCropped"],
            row["HandWritingThumbnailPath"],
            row["CoverThumbnailPathRect"],
            row["CoverThumbnailPathSquare"],
            row["PageThumb"],
        ]
        return [candidate for candidate in ( _normalize_text(value) for value in candidates ) if candidate]

    def _row_to_summary(self, row: sqlite3.Row) -> NoteSummary:
        return NoteSummary(
            uuid=row["UUID"],
            title=row["Title"],
            recommended_title=row["RecommendedTitle"],
            category_uuid=row["CategoryUUID"],
            modified_at=row["LastModifiedAt"],
            last_db_updated_at=row["lastDBUpdatedAt"],
            created_at=row["CreatedAt"],
            deleted_status=row["DeletedStatus"],
            thumbnail_path=_pick_thumbnail_path(row),
            file_path=row["FilePath"],
            is_downloaded=row["IsDownloaded"],
            is_text_only=row["IsTextOnly"],
            is_pdf_text_saved=row["IsPdfTextSaved"],
            stripped_content=row["StrippedContent"],
            pdf_text_contents=row["PDFTextContents"],
            hw_text_content=row["HWTextContent"],
        )

    def _row_to_detail(self, row: sqlite3.Row) -> NoteDetail:
        summary = self._row_to_summary(row)
        return NoteDetail(
            **asdict(summary),
            document_type=row["DocumentType"],
            display_content=row["DisplayContent"],
            display_content_dark=row["DisplayContentDark"],
            content=row["Content"],
            note_name=row["NoteName"],
            last_accessed=row["LastAccessed"],
            bookmark_list=row["BookmarkList"],
            size=row["Size"],
            hand_writing_thumbnail_path=row["HandWritingThumbnailPath"],
            cover_thumbnail_path_rect=row["CoverThumbnailPathRect"],
            cover_thumbnail_path_square=row["CoverThumbnailPathSquare"],
            thumbnail_path_cropped=row["ThumbnailPathCropped"],
            thumbnail_path_dark_mode=row["ThumbnailPathDarkMode"],
            thumbnail_path_dark_mode_cropped=row["ThumbnailPathDarkModeCropped"],
        )


class SQLiteNoteService:
    def __init__(self, db_path: Path, refresh_seconds: int = 30, page_size: int = 500):
        self.repository = SQLiteNoteRepository(db_path)
        self.refresh_seconds = max(int(refresh_seconds), 1)
        self.page_size = max(int(page_size), 1)
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cached_notes: List[NoteSummary] = []
        self._last_refreshed_at: Optional[datetime] = None

    def start(self) -> None:
        self.refresh_now()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="sqlite-note-refresh", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop_event.wait(self.refresh_seconds):
            try:
                self.refresh_now()
            except Exception:
                continue

    def _load_all_notes(self) -> List[NoteSummary]:
        notes: List[NoteSummary] = []
        offset = 0
        while True:
            batch = self.repository.list_notes(limit=self.page_size, offset=offset)
            if not batch:
                break
            notes.extend(batch)
            if len(batch) < self.page_size:
                break
            offset += self.page_size
        return notes

    def refresh_now(self) -> None:
        with self._lock:
            self._cached_notes = self._load_all_notes()
            self._last_refreshed_at = _utc_now()

    def snapshot(self) -> ServiceSnapshot:
        with self._lock:
            return ServiceSnapshot(
                db_path=self.repository.db_path,
                note_count=len(self._cached_notes),
                last_refreshed_at=self._last_refreshed_at,
                tables=self.repository.schema(),
            )

    def list_notes(self, limit: int = 100, offset: int = 0) -> List[NoteSummary]:
        with self._lock:
            if offset == 0 and limit >= len(self._cached_notes):
                return list(self._cached_notes[:limit])
        return self.repository.list_notes(limit=limit, offset=offset)

    def list_changed_notes(self, since: int, limit: int = 500, offset: int = 0) -> List[NoteSummary]:
        return self.repository.list_changed_notes(since=since, limit=limit, offset=offset)

    def search_notes(self, query: str, limit: int = 50, offset: int = 0) -> List[SearchHit]:
        return self.repository.search_notes(query=query, limit=limit, offset=offset)

    def get_note(self, uuid: str) -> Optional[NoteDetail]:
        return self.repository.get_note(uuid)

    def get_thumbnail_candidates(self, uuid: str) -> List[str]:
        return self.repository.get_thumbnail_candidates(uuid)
