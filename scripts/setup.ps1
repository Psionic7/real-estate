param([string]$Python = "py", [string]$PythonVersion = "-3.12")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    if ($Python -eq "py") { & $Python $PythonVersion -m venv .venv }
    else { & $Python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw "Python virtual environment creation failed." }
}
& ".\.venv\Scripts\python.exe" -m pip install -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw "Package installation failed." }
if (-not (Test-Path -LiteralPath ".env")) { Copy-Item -LiteralPath ".env.example" -Destination ".env" }
& ".\.venv\Scripts\python.exe" -m estate.cli init
if ($LASTEXITCODE -ne 0) { throw "Database initialization failed." }
Write-Host "Ready. Run .\run.bat"
