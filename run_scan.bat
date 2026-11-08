@echo off
rem ICT FVG scan - scheduled task entry (launched hidden via run_scan_hidden.vbs)
rem Keep this file ASCII-only: cmd parses .bat in ANSI/GBK codepage.
cd /d "%~dp0"
if not exist logs mkdir logs
echo ===== %date% %time% ===== >> logs\scan.log
"D:\Users\pc\AppData\Local\Programs\Python\Python311\python.exe" -m ict_scanner scan >> logs\scan.log 2>&1
