param([string]$PythonExe = (Get-Command python.exe).Source)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonWindowless = Join-Path (Split-Path -Parent $PythonExe) "pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonWindowless)) { throw "pythonw.exe not found" }
$action = New-ScheduledTaskAction -Execute $pythonWindowless -Argument "-m pris.app --root `"$projectRoot`" ui" -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "PRIS Research Desk" -Action $action -Trigger $trigger -Settings $settings -Description "PRIS local research dashboard" -Force | Out-Null
Start-ScheduledTask -TaskName "PRIS Research Desk"
Write-Host "PRIS Research Desk starts at sign-in: http://127.0.0.1:8765"
