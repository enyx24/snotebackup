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

## To do:
- Add an automatic backup service that check the sqlite db & export to other storage
- Create a webUI for review + search before downloading the note.
