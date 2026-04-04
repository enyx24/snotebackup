import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

from core.model.models import ConversionResult, RunArtifacts


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def create_run_artifacts(destination_dir: Path) -> RunArtifacts:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_folder = destination_dir / f"backup_run_{stamp}"
    run_folder.mkdir(parents=True, exist_ok=False)

    metadata_path = run_folder / "metadata.json"
    csv_path = run_folder / "results.csv"
    return RunArtifacts(run_folder=run_folder, metadata_path=metadata_path, csv_path=csv_path)


def write_metadata(
    metadata_path: Path,
    started_at: datetime,
    ended_at: datetime,
    blob_count: int,
    success_count: int,
) -> None:
    payload = {
        "blob_count": blob_count,
        "successful_converted_count": success_count,
        "failed_count": blob_count - success_count,
        "time_started": _iso_utc(started_at),
        "time_done": _iso_utc(ended_at),
    }
    with metadata_path.open("w", encoding="utf-8") as target:
        json.dump(payload, target, ensure_ascii=False, indent=2)


def write_csv(csv_path: Path, rows: List[ConversionResult]) -> Tuple[int, int]:
    success_count = 0
    failure_count = 0

    with csv_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(
            target,
            fieldnames=[
                "hash",
                "exported_name",
                "successful",
                "timeline_start",
                "timeline_end",
                "duration_ms",
                "error",
            ],
        )
        writer.writeheader()

        for row in rows:
            if row.successful:
                success_count += 1
            else:
                failure_count += 1

            writer.writerow(
                {
                    "hash": row.hash_name,
                    "exported_name": row.exported_name,
                    "successful": "yes" if row.successful else "no",
                    "timeline_start": _iso_utc(row.started_at),
                    "timeline_end": _iso_utc(row.ended_at),
                    "duration_ms": row.duration_ms,
                    "error": row.error or "",
                }
            )

    return success_count, failure_count