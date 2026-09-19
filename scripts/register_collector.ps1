param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$TaskName = 'KH-Property-Collector'
if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output 'Collector task removed.'
    exit
}
$Python = Join-Path $ProjectRoot '.venv\Scripts\pythonw.exe'
$Entry = Join-Path $ProjectRoot 'scripts\worker_entry.py'
if (-not (Test-Path -LiteralPath $Python)) { throw 'Project virtual environment is missing.' }
$Action = New-ScheduledTaskAction -Execute $Python -Argument ('"' + $Entry + '"') -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$Principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$Task = New-ScheduledTask -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description 'Checks saved region schedules every 5 minutes; collects only due or user-requested jobs.'
Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Select-Object TaskName,State
