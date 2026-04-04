from datetime import datetime, timezone
from pathlib import Path
from typing import List

from core.backup.converter import convert_blob
from core.backup.discovery import discover_blobs
from core.backup.logging import create_run_artifacts, write_csv, write_metadata
from core.model.models import BackupConfig, ConversionResult, RunSummary


def run_backup(config: BackupConfig) -> RunSummary:
    config.destination_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc)
    candidates = discover_blobs(config.source_dir)

    artifacts = create_run_artifacts(config.destination_dir)

    results: List[ConversionResult] = []
    for candidate in candidates:
        result = convert_blob(candidate, config.destination_dir)
        results.append(result)

    success_count, failure_count = write_csv(artifacts.csv_path, results)
    ended_at = datetime.now(timezone.utc)

    write_metadata(
        artifacts.metadata_path,
        started_at=started_at,
        ended_at=ended_at,
        blob_count=len(candidates),
        success_count=success_count,
    )

    return RunSummary(
        source_dir=config.source_dir,
        destination_dir=config.destination_dir,
        started_at=started_at,
        ended_at=ended_at,
        blob_count=len(candidates),
        success_count=success_count,
        failure_count=failure_count,
        artifacts=artifacts,
    )


def run_backup_paths(source_dir: str, destination_dir: str) -> RunSummary:
    config = BackupConfig(source_dir=Path(source_dir), destination_dir=Path(destination_dir))
    return run_backup(config)