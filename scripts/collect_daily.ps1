param([string]$Region = "11680", [string]$RegionName = "서울특별시 강남구", [int]$Months = 3)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
& ".\.venv\Scripts\python.exe" -m estate.cli refresh --region $Region --region-name $RegionName --months $Months
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& ".\.venv\Scripts\python.exe" -m estate.cli geocode --limit 200
exit $LASTEXITCODE
