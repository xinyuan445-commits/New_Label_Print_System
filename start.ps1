param([switch]$BuildFrontend)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env') -PathType Leaf)) {
    throw 'Create .env from .env.example and configure it before starting.'
}
foreach ($projectCommand in @('uv', 'npm.cmd')) {
    if (-not (Get-Command $projectCommand -ErrorAction SilentlyContinue)) {
        throw "Missing command: $projectCommand. Install uv and Node.js 22 first."
    }
}

Push-Location $projectRoot
try {
    if ($BuildFrontend -or -not (Test-Path -LiteralPath 'frontend/dist/index.html')) {
        & npm.cmd --prefix frontend ci
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        & npm.cmd --prefix frontend run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    }
    Push-Location backend
    try {
        & uv sync --frozen
        if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
        & uv run --frozen python local_server.py
        if ($LASTEXITCODE -ne 0) { throw 'Label service stopped with an error.' }
    } finally {
        Pop-Location
    }
} finally {
    Pop-Location
}
