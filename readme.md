# Samsung Notes Auto Backup
I don't know why such a large ecosystem as Samsung could not implement something just to export all the notes. I'm running out of my tab storage so, I wrote this.<br>
This repo utilizes the Windows Samsung Notes app to read raw data then try to store those notes somewhere else in the import-able format (sdocx). 
## Requirements
- Samsung Notes windows app, synced with your Samsung account
- Samsung Account app (somehow I can't signin without this)
- python
## Installation
```
    pip install -r requirement.txt
```
## Features
- Create the sdocx format that let Samsung Notes able to import
- Fully backup all notes possible from Samsung Note app's 

## Usages:
- [Compress to sdocx](utils/compress_guide.md)
- [Full backup](utils/backup_guide.md)
- [Read-only notes API](utils/note_service.py)
- [Incremental backup service](utils/backup_service.py)
- [Notes browser UI](utils/backup_service.py)
- [YAML config](config/services.yml)

## To do:
- Add an automatic backup service that check the sqlite db & export to other storage
- Create a webUI for review + search before downloading the note.

## Split architecture (2 machines)

The project is now split into 2 roles:

1. **Note API (`utils.note_service`)** runs on Windows where Samsung Notes AppData/SQLite exists.
2. **Backup + WebUI (`utils.backup_service`)** runs on backup machine and talks to Note API over HTTP.

Delete semantics: if a note disappears from app, backup files are kept and note is marked `deleted_on_app` in backup index.

Sync strategy: incremental `changes-since` first, with periodic full-scan reconcile (`full_scan_interval_hours`) as fallback.

## Note API

`utils.note_service` (config-first, CLI > YAML > defaults):

- `py -m utils.note_service --config config/services.yml`

Bearer auth: set `services.note_api.token`. Endpoints except `/health` require `Authorization: Bearer <token>`.

### Endpoints

- `GET /health` - liveness and note count (no auth)
- `GET /meta` - API capabilities and source/db metadata
- `GET /schema` - discovered SQLite tables and columns
- `GET /notes` - list notes
- `GET /notes/<uuid>` - note detail (includes `deleted_on_app`)
- `GET /changes-since?since=<timestamp>` - incremental feed
- `GET /notes/<uuid>/download` - generate and return one `.sdocx`
- `GET /notes/<uuid>/thumbnail` - first available thumbnail file
- `GET /notes/<uuid>/media` and `/notes/<uuid>/media/<relative_path>` - media review
- `POST /refresh` - force cache refresh

## Backup + WebUI

`utils.backup_service` now only talks to Note API (no direct SQLite access):

- `py -m utils.backup_service --config config/services.yml`

### Endpoints

- `GET /` - Backup WebUI with active/deleted groups
- `GET /health` - worker state and checkpoint
- `GET /state` - persisted sync state
- `POST /sync` - trigger one sync run
- `GET /runs/latest`, `GET /runs/recent`
- `GET /source/health`, `GET /source/meta` - upstream Note API checks
- `GET /index/summary` - counts of `active_in_app` and `deleted_on_app`
- `GET /index/notes?deleted=0|1` - indexed notes grouped by status

Backup metadata files in destination folder:

- `.snotebackup_state.json` - checkpoint + sync timestamps
- `.snotebackup_index.json` - note index (`backup_artifacts`, `last_seen_on_app`, `deleted_on_app`, ...)

## Config file

Use [config/services.yml](config/services.yml) to control:

- Note API section: `services.note_api.*`
- Backup/UI section: `services.backup_ui.*`
- shared token for inter-service auth (`token`)
- incremental schedule (`refresh_seconds`) + fallback full scan (`full_scan_interval_hours`)
