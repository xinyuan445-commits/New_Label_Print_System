"""Read Windows print queues for the single-computer pilot server."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys


def list_local_printers() -> list[str]:
    if sys.platform != "win32":
        raise RuntimeError("Windows printer discovery is unavailable")
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        raise RuntimeError("PowerShell is unavailable")

    command = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "ConvertTo-Json -InputObject @(Get-Printer -ErrorAction Stop | "
        "Select-Object -ExpandProperty Name) -Compress"
    )
    result = subprocess.run(  # noqa: S603 — fixed command, no user-supplied arguments
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    names = json.loads(result.stdout)
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise ValueError("Unexpected printer list from Windows")
    return names
