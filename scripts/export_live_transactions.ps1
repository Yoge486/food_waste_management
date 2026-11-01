param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonPath = "",
    [string]$OutputPath = "",
    [string]$StatusPath = ""
)

$ErrorActionPreference = "Stop"

if (-not $PythonPath) {
    $PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
}
if (-not $OutputPath) {
    $OutputPath = Join-Path $ProjectRoot "ml-service\data\live_transactions.csv"
}
if (-not $StatusPath) {
    $StatusPath = Join-Path $ProjectRoot "ml-service\data\live_transactions_status.json"
}

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python executable not found: $PythonPath"
}

Push-Location $ProjectRoot
try {
    & $PythonPath manage.py export_transactions `
        --output $OutputPath `
        --status-file $StatusPath
    if ($LASTEXITCODE -ne 0) {
        throw "Transaction export failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
