param([ValidateSet('install','verify','restore','check')][string]$Action = 'install')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false
$env:PYTHONUTF8 = '1'
$packRoot = Split-Path $PSScriptRoot -Parent
Set-Location $packRoot
$candidates = New-Object System.Collections.Generic.List[object]
if ($env:YUYU_PYTHON) { $candidates.Add(@{Exe=$env:YUYU_PYTHON; Prefix=@()}) }
foreach ($name in @('py','python','python3')) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notlike '*\WindowsApps\*') {
        $prefix = @()
        if ($name -eq 'py') { $prefix = @('-3') }
        $candidates.Add(@{Exe=$command.Source; Prefix=$prefix})
    }
}
$instanceRoot = Join-Path $env:USERPROFILE '.astrbot_launcher\instances'
if (Test-Path $instanceRoot) {
    foreach ($instance in Get-ChildItem $instanceRoot -Directory -ErrorAction SilentlyContinue) {
        foreach ($relative in @('venv\Scripts\python.exe','.venv\Scripts\python.exe')) {
            $candidatePath = Join-Path $instance.FullName $relative
            if (Test-Path $candidatePath) { $candidates.Add(@{Exe=$candidatePath; Prefix=@()}) }
        }
    }
}
foreach ($candidate in $candidates) {
    $exe = $candidate.Exe
    $prefix = $candidate.Prefix
    try {
        & $exe @prefix -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) {
            & $exe @prefix -X utf8 (Join-Path $PSScriptRoot 'manage.py') $Action
            exit $LASTEXITCODE
        }
    } catch { continue }
}
Write-Host 'Python 3.10+ was not found. Set YUYU_PYTHON to an existing python.exe, or use INSTALL.md.'
exit 1
