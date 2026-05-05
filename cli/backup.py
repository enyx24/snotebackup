import argparse
import sys
from pathlib import Path

from tqdm import tqdm

from core.backup.discovery import discover_blobs
from core.backup.converter import convert_blob
from core.backup.logging import create_run_artifacts, write_csv, write_metadata
from utils.discover_appdata import discover_appdata
from utils.load_config import _load_client_config
from utils.path_utils import _path_exists, _path_size, _path_free_space


def prompt_path(prompt_msg: str, default: str = None) -> str:
    """Interactively prompt user for a path."""
    if default:
        msg = f"{prompt_msg} [{default}]: "
    else:
        msg = f"{prompt_msg}: "
    
    user_input = input(msg).strip()
    return user_input if user_input else default


def prompt_confirm(msg: str) -> bool:
    """Interactively prompt user for y/n confirmation."""
    while True:
        response = input(f"{msg} (y/n): ").strip().lower()
        if response in ("y", "yes"):
            return True
        elif response in ("n", "no"):
            return False
        else:
            print("Please enter 'y' or 'n'.")


def run_cli(source_path: Path) -> int:
    """Interactive CLI mode with prompts and progress bar."""
    print("\n=== Blob Backup to SDOCX (CLI Mode) ===\n")

    if source_path and source_path.exists():
        print(f"Using source from config: {source_path}\n")
        if not _path_exists(source_path):
            print(f"Source directory does not exist: {source_path}")
            return 1
    else:
        # Auto-discover source
        discovered_source = None
        try:
            discovered_source = discover_appdata()
            print(f"Auto-discovered source: {discovered_source}\n")
        except Exception:
            print("Could not auto-discover source folder.\n")
        
        entered_source = prompt_path("Enter source directory", default=discovered_source)
        
        source_path = Path(entered_source)
        if not _path_exists(source_path):
            print(f"Source directory does not exist: {source_path}")
            return 1
    
    # Prompt for destination
    default_dest = str(Path.cwd())
    destination_dir = prompt_path("Enter destination directory", default_dest)
    dest_path = Path(destination_dir)
    dest_path.mkdir(parents=True, exist_ok=True)
    
    # Discover blobs and confirm before running
    print("Discovering blobs...")
    candidates = discover_blobs(source_path)
    print(f"Found {len(candidates)} blob(s).\n")
    
    if not candidates:
        print("No blobs found.")
        return 0

    # Confirm before running
    backup_size_mb = sum(_path_size(str(blob.folder_path), "MB") for blob in candidates)
    free_disk_mb = _path_free_space(str(dest_path), "MB")
    print(f"Source: {source_path}")
    print(f"Destination: {dest_path}")
    print(f"Backup size: {backup_size_mb:.2f} MB")
    print(f"Destination free space: {free_disk_mb:.2f} MB")
    if backup_size_mb > free_disk_mb - 100: # Keep 100MB in case of sth unexpected
        print("Warning: Insufficient disk space for backup.")
        if not prompt_confirm("Continue anyway?"):
            print("Cancelled.")
            return 1
    if not prompt_confirm("Backup confirmation"):
        print("Cancelled.")
        return 1
    
    # Run backup
    artifacts = create_run_artifacts(dest_path)
    results = []
    
    print("Converting blobs...")
    for candidate in tqdm(candidates, desc="Backing up", unit="blob"):
        result = convert_blob(candidate, dest_path)
        results.append(result)
    
    # Write logs
    success_count, failure_count = write_csv(artifacts.csv_path, results)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    started_at = results[0].started_at if results else now
    ended_at = results[-1].ended_at if results else now
    
    write_metadata(
        artifacts.metadata_path,
        started_at=started_at,
        ended_at=ended_at,
        blob_count=len(candidates),
        success_count=success_count,
    )
    
    # Report
    print("\n=== Backup Complete ===")
    print(f"Total blobs: {len(candidates)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {failure_count}")
    print(f"Metadata: {artifacts.metadata_path}")
    print(f"Results: {artifacts.csv_path}")
    print("Finish")
    
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backup blob folders to SDOCX with interactive CLI or web GUI"
    )
    parser.add_argument(
        "--config", "-c",
        type=str,        
        default="config/services.yaml",
        help="Path to configuration file (default: config/services.yaml)"
    )
    args = parser.parse_args()
    src_path = Path(_load_client_config(args.config).get("source", ""))
    return run_cli(src_path)


if __name__ == "__main__":
    sys.exit(main())
