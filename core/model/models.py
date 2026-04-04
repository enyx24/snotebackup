from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


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