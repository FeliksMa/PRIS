$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$nightlyScript = Join-Path $PSScriptRoot "run-nightly.ps1"
$feedbackScript = Join-Path $PSScriptRoot "poll-feedback.ps1"

$nightlyAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$nightlyScript`""
$nightlyTrigger = New-ScheduledTaskTrigger -Daily -At 12:30AM
$nightlySettings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 4)
Register-ScheduledTask -TaskName "PRIS Nightly Research" -Action $nightlyAction -Trigger $nightlyTrigger -Settings $nightlySettings -Description "PRIS nightly research brief" -Force

$feedbackAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$feedbackScript`""
$feedbackTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
$feedbackSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "PRIS Telegram Feedback" -Action $feedbackAction -Trigger $feedbackTrigger -Settings $feedbackSettings -Description "PRIS Telegram feedback sync" -Force

Write-Host "Installed PRIS nightly and Telegram feedback tasks. Project: $projectRoot"
