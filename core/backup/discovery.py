from pathlib import Path
from typing import List

from core.model.backup import BlobCandidate

from config.constants import MARKER_FILES


def _has_note_markers(folder_path: Path) -> bool:
    try:
        entries = list(folder_path.iterdir())
    except OSError:
        return False

    entry_names = {entry.name for entry in entries}
    if MARKER_FILES & entry_names:
        return True
    if any(entry.is_file() and entry.suffix == ".page" for entry in entries):
        return True
    if "media" in entry_names and (folder_path / "media").is_dir():
        return True
    return False


def discover_blobs(source_dir: Path) -> List[BlobCandidate]:
    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory does not exist: {source_dir}")
    if not source_dir.is_dir():
        raise NotADirectoryError(f"Source path is not a directory: {source_dir}")

    candidates: List[BlobCandidate] = []
    for child in sorted(source_dir.iterdir(), key=lambda item: item.name):
        if not child.is_dir():
            continue
        if _has_note_markers(child):
            candidates.append(BlobCandidate(hash_name=child.name, folder_path=child))

    return candidates