import os
from pathlib import Path

PATTERN = os.path.join(
    os.environ["LOCALAPPDATA"],
    "Packages",
    "SAMSUNGELECTRONICSCoLtd.SamsungNotes_*",
    "LocalState",
    "wdoc",
)

def discover_appdata() -> str:
    packages_dir = os.path.join(os.environ["LOCALAPPDATA"], "Packages")
    if not os.path.isdir(packages_dir):
        raise FileNotFoundError(f"Packages directory not found: {packages_dir}")
    
    candidates = []
    try:
        entries = os.listdir(packages_dir)
    except OSError as e:
        raise FileNotFoundError(f"Cannot list Packages directory: {e}")
    
    for entry in entries:
        if entry.startswith("SAMSUNGELECTRONICSCoLtd.SamsungNotes_"):
            candidate_path = os.path.join(packages_dir, entry, "LocalState", "wdoc")
            if os.path.isdir(candidate_path):
                candidates.append(candidate_path)

    if not candidates:
        raise FileNotFoundError("No Samsung Notes data directory found in LocalAppData.")
    if len(candidates) > 1:
        raise FileExistsError(f"Multiple Samsung Notes data directories found: {candidates}")
    return candidates[0]


def discover_samsung_notes_storage_db() -> str:
    storage_dir = discover_appdata()
    candidate = Path(storage_dir).parent / "Storage.sqlite"
    if not candidate.is_file():
        raise FileNotFoundError(f"Storage.sqlite not found: {candidate}")
    return str(candidate)


def discover_samsung_notes_pen_storage_db() -> str:
    storage_dir = discover_appdata()
    candidate = Path(storage_dir).parent / "PenStorage.sqlite"
    if not candidate.is_file():
        raise FileNotFoundError(f"PenStorage.sqlite not found: {candidate}")
    return str(candidate)

if __name__ == "__main__":
    try:
        print(f"Found: {discover_appdata()}")
    except Exception as e:
        print(f"Error during discovery: {e}")
