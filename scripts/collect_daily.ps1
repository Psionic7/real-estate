param([string]$Region = "41465", [string]$RegionName = "경기도 용인시 수지구", [int]$Months = 3)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
& ".\.venv\Scripts\python.exe" -m estate.cli refresh --region $Region --region-name $RegionName --months $Months
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& ".\.venv\Scripts\python.exe" -m estate.cli search-addresses --region $Region --limit 200
if ($LASTEXITCODE -ne 0) { Write-Warning "Address lookup failed; continuing coordinate refresh." }
& ".\.venv\Scripts\python.exe" -m estate.cli geocode --limit 200
exit $LASTEXITCODE
