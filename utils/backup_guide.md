# Backup blobs to SDOCX

## Overview

Interactive backup utility that discovers blob folders from a source directory, converts each blob to `.sdocx`, and writes two run logs:

- `metadata.json`: run-level metadata (`blob_count`, `successful_converted_count`, `time_started`, `time_done`, `failed_count`)
- `results.csv`: per-blob result (`hash`, `exported_name`, `successful`, `timeline_start`, `timeline_end`, `duration_ms`, `error`)

Each run creates a timestamped folder in destination: `backup_run_YYYYMMDD_HHMMSS`.

## Usage

### CLI Mode (Default)

Interactive command-line mode with prompts and progress bar:

```bash
py -m utils.backup
```

Flow:
1. **Source discovery**: Auto-discovers Samsung Notes data folder and asks for confirmation
2. **Source input**: If auto-discovery fails, prompts you to enter source directory
3. **Destination input**: Prompts for destination (default: current directory)
4. **Confirmation**: Shows summary and asks to confirm before running
5. **Backup**: Runs conversion with tqdm progress bar
6. **Report**: Shows summary of successful/failed conversions and log file locations

### Web GUI Mode

Simple web interface accessible in browser:

```bash
py -m utils.backup --gui
```

Then open: `http://127.0.0.1:5050`

Will:
- Pre-fill source with auto-discovered path (if available)
- Allow manual entry of source and destination
- Display results and log file paths after completion

## Discovery behavior

- Scans only top-level subfolders under source directory.
- A subfolder is considered a blob candidate if it has any note marker (`note.note`, `end_tag.bin`, `pageIdInfo.dat`, `.page`, or `media/`).

## Failure behavior

- If a blob conversion fails, the module logs the failure and continues with the next blob.
- Results CSV shows `successful: no` and includes error message.