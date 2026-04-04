from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class BackupConfig:
    source_dir: Path
    destination_dir: Path


@dataclass(frozen=True)
class BlobCandidate:
    hash_name: str
    folder_path: Path


@dataclass(frozen=True)
class ConversionResult:
    hash_name: str
    folder_path: Path
    exported_name: str
    output_path: Path
    successful: bool
    started_at: datetime
    ended_at: datetime
    duration_ms: int
    error: Optional[str] = None


@dataclass(frozen=True)
class RunArtifacts:
    run_folder: Path
    metadata_path: Path
    csv_path: Path


@dataclass(frozen=True)
class RunSummary:
    source_dir: Path
    destination_dir: Path
    started_at: datetime
    ended_at: datetime
    blob_count: int
    success_count: int
    failure_count: int
    artifacts: RunArtifacts


@dataclass(frozen=True)
class SQLiteColumnInfo:
    name: str
    data_type: str
    notnull: bool
    default_value: Optional[str]
    is_primary_key: bool


@dataclass(frozen=True)
class SQLiteTableInfo:
    name: str
    columns: List[SQLiteColumnInfo]


@dataclass(frozen=True)
class NoteSummary:
    uuid: str
    title: Optional[str]
    recommended_title: Optional[str]
    category_uuid: Optional[str]
    modified_at: Optional[int]
    last_db_updated_at: Optional[int]
    created_at: Optional[int]
    deleted_status: Optional[int]
    thumbnail_path: Optional[str]
    file_path: Optional[str]
    is_downloaded: Optional[int]
    is_text_only: Optional[int]
    is_pdf_text_saved: Optional[int]
    stripped_content: Optional[str]
    pdf_text_contents: Optional[str]
    hw_text_content: Optional[str]


@dataclass(frozen=True)
class NoteDetail(NoteSummary):
    document_type: Optional[int]
    display_content: Optional[str]
    display_content_dark: Optional[str]
    content: Optional[str]
    note_name: Optional[str]
    last_accessed: Optional[str]
    bookmark_list: Optional[str]
    size: Optional[int]
    hand_writing_thumbnail_path: Optional[str]
    cover_thumbnail_path_rect: Optional[str]
    cover_thumbnail_path_square: Optional[str]
    thumbnail_path_cropped: Optional[str]
    thumbnail_path_dark_mode: Optional[str]
    thumbnail_path_dark_mode_cropped: Optional[str]


@dataclass(frozen=True)
class SearchHit:
    uuid: str
    title: Optional[str]
    modified_at: Optional[int]
    thumbnail_path: Optional[str]
    snippet: str
    score: int
    source: str


@dataclass(frozen=True)
class ServiceSnapshot:
    db_path: Path
    note_count: int
    last_refreshed_at: Optional[datetime]
    tables: List[SQLiteTableInfo]


@dataclass(frozen=True)
class IncrementalBackupState:
    checkpoint: int
    last_synced_at: Optional[datetime]
    last_run_folder: Optional[Path]
    last_run_count: int
    last_success_count: int
    last_failure_count: int


@dataclass(frozen=True)
class IncrementalBackupResult:
    checkpoint_before: int
    checkpoint_after: int
    changed_count: int
    success_count: int
    failure_count: int
    started_at: datetime
    ended_at: datetime
    run_artifacts: Optional[RunArtifacts]