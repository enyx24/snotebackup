import re
lines = open('core/backup/incremental_service.py').readlines()
for i, line in enumerate(lines[202:270], start=203):
    if '# Phase' in line or 'with self._lock:' in line:
        indent = len(line) - len(line.lstrip())
        print(f"Line {i}: indent={indent:2d} | {line.rstrip()}")
