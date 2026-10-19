param([string]$GoCommand = 'go')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    & $GoCommand test ./...
    if ($LASTEXITCODE -ne 0) { throw 'Connector tests failed' }
    New-Item -ItemType Directory -Force -Path 'dist' | Out-Null
    & $GoCommand build -trimpath -ldflags '-s -w' -o 'dist/blg-connector-windows.exe' .
    if ($LASTEXITCODE -ne 0) { throw 'Connector build failed' }
} finally { Pop-Location }
