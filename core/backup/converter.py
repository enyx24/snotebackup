from datetime import datetime, timezone
from pathlib import Path

from utils.to_sdocx import compress_to_sdocx

from core.model.models import BlobCandidate, ConversionResult


def convert_blob(candidate: BlobCandidate, destination_dir: Path) -> ConversionResult:
    started_at = datetime.now(timezone.utc)
    exported_name = f"{candidate.hash_name}.sdocx"
    output_path = destination_dir / exported_name

    successful = False
    error = None
    try:
        compress_to_sdocx(str(candidate.folder_path), str(output_path))
        successful = True
    except Exception as exc:
        error = str(exc)

    ended_at = datetime.now(timezone.utc)
    duration_ms = int((ended_at - started_at).total_seconds() * 1000)
    return ConversionResult(
        hash_name=candidate.hash_name,
        folder_path=candidate.folder_path,
        exported_name=exported_name,
        output_path=output_path,
        successful=successful,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        error=error,
    )