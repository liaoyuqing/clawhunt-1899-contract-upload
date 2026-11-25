"""Minimal HTTP helper so the evidence can quote the real status line."""

from __future__ import annotations

import urllib.error
import urllib.request


def get(url: str) -> tuple[int, str, int]:
    """GET ``url`` and return ``(status, error_code_or_empty, body_len)``."""
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            body = response.read()
            return response.status, "", len(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        code = ""
        if "<Code>" in body:
            code = body.split("<Code>", 1)[1].split("</Code>", 1)[0]
        return exc.code, code, len(body)
