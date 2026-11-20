@echo off
setlocal
cd /d "%~dp0"
title YoMama Scan Agent setup
echo.
echo === YoMama Scan Agent setup ===
echo.

rem 1. Python
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo Python is not installed. Installing it now with winget...
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  echo.
  echo Python was installed. Close this window and double-click setup.cmd again.
  pause
  exit /b 1
)

rem 2. Libraries
echo Installing the picture and upload libraries (one time, about a minute)...
%PY% -m pip install --user --upgrade -q --no-warn-script-location -r requirements.txt
if errorlevel 1 ( echo Library install failed. Send Claude a photo of this window. & pause & exit /b 1 )

rem 3. GitHub key (skipped when a saved key still works)
echo.
%PY% scan_agent.py --setup
if errorlevel 1 ( echo. & echo Setup stopped. Send Claude a photo of this window. & pause & exit /b 1 )

rem 4. Start automatically at sign-in: a scheduled task, or a Startup-folder shortcut if Windows refuses the task
for /f "delims=" %%i in ('%PY% -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYW=%%i"
call stop-agent.cmd quiet
schtasks /Create /TN "YoMama Scan Agent" /TR "\"%PYW%\" \"%~dp0scan_agent.py\"" /SC ONLOGON /RL LIMITED /F >nul 2>nul
if errorlevel 1 (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\YoMama Scan Agent.lnk'); $s.TargetPath='%PYW%'; $s.Arguments='\"%~dp0scan_agent.py\"'; $s.WorkingDirectory='%~dp0'; $s.Save()"
  if errorlevel 1 ( echo Could not set up auto-start. Send Claude a photo of this window. & pause & exit /b 1 )
  echo Auto-start: shortcut added to your Startup folder.
) else (
  echo Auto-start: scheduled task created.
)

rem 5. Start it now
start "" "%PYW%" "%~dp0scan_agent.py"

echo.
echo All set. The Scan Agent is running now and starts by itself every time you sign in.
echo Scan into E:\Scans\Claude Scans as usual. About 90 seconds after the last page,
echo the photos are uploaded and the scans move into "do not scan".
echo Its diary is scan_agent.log in this folder.
echo.
pause
