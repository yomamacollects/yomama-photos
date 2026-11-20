@echo off
rem Stops the Scan Agent until you sign in again (or run start-agent.cmd).
schtasks /End /TN "YoMama Scan Agent" >nul 2>nul
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name='pythonw.exe' or name='python.exe'\" | Where-Object { $_.CommandLine -like '*scan_agent.py*' -and $_.CommandLine -notlike '*--setup*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
if not "%~1"=="quiet" ( echo Scan Agent stopped. & pause )
