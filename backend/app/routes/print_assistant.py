"""Authenticated download of the project-built Windows client printing assistant."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from flask import Blueprint, jsonify, request, send_file
from flask.typing import ResponseReturnValue
from flask_login import login_required

print_assistant_bp = Blueprint("print_assistant", __name__)


@print_assistant_bp.get("/print-assistant/windows")
@login_required
def download_windows_assistant() -> ResponseReturnValue:
    root = Path(__file__).resolve().parents[3]
    binary = root / "connector" / "dist" / "blg-connector-windows.exe"
    if not binary.is_file():
        return jsonify({"error": "assistant_not_built"}), 503
    config = "client_only: true\nserver_url: " + json.dumps(request.host_url.rstrip("/")) + "\n"
    script = r'''$ErrorActionPreference = 'Stop'
$installDir = Join-Path $env:LOCALAPPDATA 'LabelPrintingAssistant'
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
$exePath = Join-Path $installDir 'blg-connector.exe'
Get-CimInstance Win32_Process -Filter "Name='blg-connector.exe'" | Where-Object {
    $_.ExecutablePath -eq $exePath
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'blg-connector.exe') -Destination $exePath -Force
$configPath = Join-Path $installDir 'config.yaml'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'config.yaml') -Destination $configPath -Force
$startupPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'LabelPrintingAssistant.vbs'
$command = '"""' + $exePath + '"" -config ""' + $configPath + '"""'
$vbs = 'CreateObject("WScript.Shell").Run ' + $command + ', 0, False'
[IO.File]::WriteAllText($startupPath, $vbs, [Text.Encoding]::Unicode)
Start-Process -FilePath $exePath -ArgumentList ('-config "' + $configPath + '"') `
    -WorkingDirectory $installDir -WindowStyle Hidden
$desktopEntry = Join-Path ([Environment]::GetFolderPath('Desktop')) '标签打印系统.url'
[IO.File]::WriteAllText($desktopEntry, "[InternetShortcut]`r`nURL=http://127.0.0.1:9110/app/`r`n")
Write-Host '安装完成。请双击桌面“标签打印系统”进入。'
Read-Host '按回车关闭'
'''
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("blg-connector.exe", binary.read_bytes())
        archive.writestr("config.yaml", config)
        archive.writestr("install.ps1", script.encode("utf-8-sig"))
        archive.writestr(
            "install.bat",
            '@echo off\r\ncd /d "%~dp0"\r\n'
            "powershell.exe -NoProfile -ExecutionPolicy Bypass "
            '-File "%~dp0install.ps1"\r\nif errorlevel 1 pause\r\n',
        )
    buffer.seek(0)
    response = send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name="LabelPrintingAssistant-Windows.zip",
    )
    response.headers["Cache-Control"] = "no-store"
    return response
