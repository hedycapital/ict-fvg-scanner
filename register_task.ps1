# ICT FVG scan - register scheduled task (hourly, at :05 — 1h K-line closes at :00 UTC, +5min buffer)
# Unicode-safe: build paths from this script's own directory.
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$vbs = Join-Path $dir "run_scan_hidden.vbs"

$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument ('"' + $vbs + '"')
# Align first fire to next hour boundary + 5 min (1h close at :00 + HL data settle buffer)
$nextRun = (Get-Date).Date.AddHours((Get-Date).Hour + 1).AddMinutes(5)
$trigger = New-ScheduledTaskTrigger -Once -At $nextRun `
    -RepetitionInterval (New-TimeSpan -Minutes 60) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 8) `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "ICT-FVG-Scan" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "ICT FVG gap scan (Hyperliquid HIP-3 xyz 1h, Telegram push)" -Force | Out-Null
Write-Output ("Task registered. Next run: " + $nextRun.ToString("yyyy-MM-dd HH:mm:ss"))
