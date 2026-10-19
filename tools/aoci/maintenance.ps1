param(
    [ValidateSet('verify', 'check', 'doctor', 'capabilities', 'guide', 'scan')]
    [string]$Action = 'verify'
)

$ErrorActionPreference = 'Stop'
$aociProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$aociExecutable = Join-Path $PSScriptRoot 'aoci.exe'
if (-not (Test-Path -LiteralPath $aociExecutable -PathType Leaf)) {
    throw 'AOCI executable is missing. See docs/aoci/README.md.'
}
if ($Action -eq 'guide') {
    & $aociExecutable --repo $aociProjectRoot --json index agent guide --agent codex
} else {
    & $aociExecutable --repo $aociProjectRoot $Action
}
exit $LASTEXITCODE
