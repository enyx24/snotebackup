from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple
from urllib import parse as urllib_parse
from urllib import request as urllib_request


class NoteApiClient:
    def __init__(self, base_url: str, token: Optional[str] = None, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = max(int(timeout), 1)

    def _headers(self, accept: str = "application/json") -> Dict[str, str]:
        headers = {"Accept": accept}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _build_url(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if params:
            query = urllib_parse.urlencode({key: value for key, value in params.items() if value is not None})
            if query:
                url = f"{url}?{query}"
        return url

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        req = urllib_request.Request(
            self._build_url(path, params=params),
            method="GET",
            headers=self._headers(),
        )
        with urllib_request.urlopen(req, timeout=self.timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    def post_json(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        body = json.dumps(payload or {}).encode("utf-8")
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        req = urllib_request.Request(
            self._build_url(path),
            method="POST",
            headers=headers,
            data=body,
        )
        with urllib_request.urlopen(req, timeout=self.timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    def get_bytes(self, path: str) -> bytes:
        req = urllib_request.Request(
            self._build_url(path),
            method="GET",
            headers=self._headers(accept="*/*"),
        )
        with urllib_request.urlopen(req, timeout=self.timeout) as response:
            return response.read()

    def get_raw(self, path: str) -> Tuple[bytes, str]:
        req = urllib_request.Request(
            self._build_url(path),
            method="GET",
            headers=self._headers(accept="*/*"),
        )
        with urllib_request.urlopen(req, timeout=self.timeout) as response:
            payload = response.read()
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            return payload, content_type

    def health(self) -> Dict[str, Any]:
        return self.get_json("/health")

    def meta(self) -> Dict[str, Any]:
        return self.get_json("/meta")

    def list_notes(self, limit: int, offset: int) -> Dict[str, Any]:
        return self.get_json("/notes", params={"limit": limit, "offset": offset})

    def list_changes_since(self, since: int, limit: int, offset: int) -> Dict[str, Any]:
        return self.get_json("/changes-since", params={"since": since, "limit": limit, "offset": offset})

    def download_note(self, uuid: str) -> bytes:
        return self.get_bytes(f"/notes/{uuid}/download")
