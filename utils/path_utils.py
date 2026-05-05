from __future__ import annotations

import os
import shutil
from pathlib import Path

def _path_exists(path: str) -> bool:
    return Path(path).exists()

def _normalize_windows_path(path: str, *, absolute: bool = False) -> str:
	"""
	Normalize a path to Windows-style separators and casing.
	"""
	if absolute:
		path = os.path.abspath(path)

	normalized = os.path.normpath(path)
	normalized = os.path.normcase(normalized)

	return normalized.replace("/", "\\")

def _path_size(path: str, format: str = "bytes") -> int | float:
	try:
		p = Path(path)
		if p.is_dir():
			size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
		else:
			size = p.stat().st_size
		if format == "MB":
			size /= (1024 * 1024)
		return int(size) if format == "bytes" else size
	except OSError:
		return 0
	
def _path_free_space(path: str, format: str = "bytes") -> int:
	try:
		path_obj = Path(path)
		free_space = shutil.disk_usage(path_obj).free
		if format == "MB":
			free_space /= (1024 * 1024)
		return free_space
	except OSError:
		return 0