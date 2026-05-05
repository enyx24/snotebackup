# [Client Side] Samsung Notes Auto Backup
This branch include 2 main features: 
- a CLI to manually back up all notes in .sdocx format
- a client service to automate backup progress with server service.
## Requirements
- Samsung Notes windows app, synced with your Samsung account
- Samsung Account windows app
- python
## Installation
Both Samsung apps can be easily install by Microsoft Store.

Python package installation:
```
pip install -r requirement.txt
```
## Run
- Config: You can both manually config the source folder in `config\services.yaml`, or just let the script auto detects the default. You'll need to see the [note](#notes) if it failed to detect.
- CLI:
```
py -m cli.backup
```
You will need to provide where the blobs will be placed.
- Client service:
```
WIP
```
## Notes
- The source folder default directory is at `$LOCALAPPDATA/Packages/SAMSUNGELECTRONICSCoLtd.SamsungNotes_*/LocalState/wdoc"`
- If you have changed your **Settings > System > Storage > Change where new content is saved** setting in Windows, look for it in `$NewPath\WpSystem\S*\AppData\Local\Packages\SAMSUNGELECTRONICSCoLtd.SamsungNotes_*\LocalState\wdoc`
