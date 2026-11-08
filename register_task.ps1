# ICT FVG scan - register scheduled task (every 15 minutes, aligned to :00/:15/:30/:45 UTC close)
# Unicode-safe: build paths from this script's own directory.
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$vbs = Join-Path $dir "run_scan_hidden.vbs"

$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument ('"' + $vbs + '"')
$start = (Get-Date).Date.AddMinutes(0)  # today 00:00; repetition grid derives from trigger start
# Align first fire to next quarter-hour boundary
$minute = (Get-Date).Minute
$nextQuarter = (Get-Date).AddMinutes(15 - ($minute % 15))
$nextQuarter = $nextQuarter.AddSeconds(-$nextQuarter.Second)
$trigger = New-ScheduledTaskTrigger -Once -At $nextQuarter `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 8) `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "ICT-FVG-Scan" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "ICT FVG gap scan (binance USDT-M perp 15m, Telegram push)" -Force | Out-Null
Write-Output ("Task registered. Next run: " + $nextQuarter.ToString("yyyy-MM-dd HH:mm:ss"))
