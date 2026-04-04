import argparse
import sys
import webbrowser
import threading
from pathlib import Path

from tqdm import tqdm

from core.backup.discovery import discover_blobs
from core.backup.converter import convert_blob
from core.backup.logging import create_run_artifacts, write_csv, write_metadata
from utils.discover_appdata import discover_appdata


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


def run_cli_mode() -> int:
    """Interactive CLI mode with prompts and progress bar."""
    print("\n=== Blob Backup to SDOCX (CLI Mode) ===\n")
    
    # Auto-discover source
    discovered_source = None
    try:
        discovered_source = discover_appdata()
        print(f"Auto-discovered source: {discovered_source}\n")
    except Exception:
        print("Could not auto-discover source folder.\n")
    
    entered_source = prompt_path("Enter source directory", default=discovered_source)
    
    source_path = Path(entered_source)
    if not source_path.exists():
        print(f"Source directory does not exist: {source_path}")
        return 1
    
    # Prompt for destination
    default_dest = str(Path.cwd())
    destination_dir = prompt_path("Enter destination directory", default_dest)
    dest_path = Path(destination_dir)
    dest_path.mkdir(parents=True, exist_ok=True)
    
    # Confirm before running
    print(f"\nSource: {source_path}")
    print(f"Destination: {dest_path}")
    if not prompt_confirm("Ready to backup?"):
        print("Cancelled.")
        return 1
    
    # Run backup with progress
    print("\nBacking up...\n")
    print("Discovering blobs...")
    candidates = discover_blobs(source_path)
    print(f"Found {len(candidates)} blob(s).\n")
    
    if not candidates:
        print("No blobs found.")
        return 0
    
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
    print(f"Results (CSV): {artifacts.csv_path}")
    print("Finish")
    
    return 0


def run_gui_mode() -> int:
    """Flask web GUI mode."""
    print("\n=== Blob Backup to SDOCX (Web GUI) ===\n")
    
    try:
        from flask import Flask, render_template_string, request
    except ImportError:
        print("Flask is required for GUI mode. Install with: pip install flask")
        return 1
    
    # Discover default source
    discovered_source = None
    try:
        discovered_source = discover_appdata()
    except Exception:
        discovered_source = None
    
    app = Flask(__name__)
    
    default_destination = str(Path.cwd())

    PAGE = f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Blob Backup to SDOCX</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; }}
    .container {{ max-width: 640px; }}
    form {{ display: grid; gap: 0.75rem; }}
    label {{ font-weight: bold; margin-top: 0.5rem; }}
    input {{ width: 100%; padding: 0.5rem; box-sizing: border-box; }}
    button {{ width: 180px; padding: 0.6rem; margin-top: 0.5rem; }}
    .result {{ margin-top: 1.5rem; padding: 1rem; border: 1px solid #ccc; border-radius: 4px; }}
    .success {{ border-color: #0a0; }}
    .error {{ color: #a00; border-color: #a00; }}
    .info {{ color: #666; font-size: 0.9rem; margin-top: 0.3rem; }}
        .status {{ margin: 1rem 0; padding: 0.75rem; background: #f5f5f5; border-left: 4px solid #0078d4; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>Blob Backup to SDOCX</h1>
        <div id="status" class="status">{{{{ status or "Ready" }}}}</div>
    <form method="post">
      <div>
        <label for="source">Source directory</label>
        <input id="source" name="source" required value="{{{{ source_path }}}}" />
        <div class="info">Auto-discovered: {{{{ auto_source or "None" }}}}</div>
      </div>
      <div>
        <label for="destination">Destination directory</label>
        <input id="destination" name="destination" value="{{{{ destination_path or "{default_destination}" }}}}" />
        <div class="info">Default: {default_destination}</div>
      </div>
      <button type="submit">Start Backup</button>
    </form>

        <script>
            const form = document.querySelector('form');
            const statusBox = document.getElementById('status');
            form.addEventListener('submit', () => {{
                statusBox.textContent = 'Backing up...';
            }});
        </script>

    {{% if error %}}
      <div class="result error"><strong>Error:</strong> {{{{ error }}}}</div>
    {{% endif %}}

        {{% if summary %}}
            <div class="result success">
                <strong>Finish</strong>
        <ul>
          <li><strong>Total blobs:</strong> {{{{ summary.blob_count }}}}</li>
          <li><strong>Successful:</strong> {{{{ summary.success_count }}}}</li>
          <li><strong>Failed:</strong> {{{{ summary.failure_count }}}}</li>
          <li><strong>Metadata:</strong> {{{{ summary.metadata_path }}}}</li>
          <li><strong>Results:</strong> {{{{ summary.csv_path }}}}</li>
        </ul>
      </div>
    {{% endif %}}
  </div>
</body>
</html>
"""
    
    @app.route("/", methods=["GET", "POST"])
    def index():
        summary = None
        error = ""
        status = ""
        source = ""
        destination = ""
        
        if request.method == "POST":
            source = request.form.get("source", "").strip()
            destination = request.form.get("destination", "").strip() or str(Path.cwd())
            status = "Backing up..."
            
            try:
                from core.backup.service import run_backup_paths
                run_summary = run_backup_paths(source, destination)
                summary = {
                    "blob_count": run_summary.blob_count,
                    "success_count": run_summary.success_count,
                    "failure_count": run_summary.failure_count,
                    "metadata_path": str(run_summary.artifacts.metadata_path),
                    "csv_path": str(run_summary.artifacts.csv_path),
                }
                status = "Finish"
            except Exception as exc:
                error = str(exc)
        else:
            source = discovered_source or ""
        
        return render_template_string(
            PAGE,
            summary=summary,
            error=error,
            status=status,
            source_path=source,
            destination_path=destination,
            auto_source=discovered_source or "None",
        )
    
    print(f"Launching web GUI at http://127.0.0.1:5050...")
    print("Press Ctrl+C to stop.\n")

    def _open_browser():
        webbrowser.open("http://127.0.0.1:5050", new=1, autoraise=True)

    threading.Timer(0.8, _open_browser).start()
    app.run(host="127.0.0.1", port=5050, debug=False)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backup blob folders to SDOCX with interactive CLI or web GUI"
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch web GUI instead of CLI mode",
    )
    args = parser.parse_args()
    
    if args.gui:
        return run_gui_mode()
    else:
        return run_cli_mode()


if __name__ == "__main__":
    sys.exit(main())
