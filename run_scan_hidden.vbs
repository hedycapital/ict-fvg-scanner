' ICT FVG scan - hidden launcher wrapper for Task Scheduler (no popup window)
' Unicode-safe: derive script directory from ScriptFullName instead of hardcoding.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
batDir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run """" & batDir & "\run_scan.bat""", 0, False
