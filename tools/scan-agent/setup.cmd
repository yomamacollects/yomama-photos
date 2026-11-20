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
%PY% -m pip install --user --upgrade -q -r requirements.txt
if errorlevel 1 ( echo Library install failed. Send Claude a photo of this window. & pause & exit /b 1 )

rem 3. GitHub key
echo.
%PY% scan_agent.py --setup
if errorlevel 1 ( echo. & echo Setup stopped. Send Claude a photo of this window. & pause & exit /b 1 )

rem 4. Start automatically when you sign in to Windows, and start it now
for /f "delims=" %%i in ('%PY% -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYW=%%i"
schtasks /Create /TN "YoMama Scan Agent" /TR "\"%PYW%\" \"%~dp0scan_agent.py\"" /SC ONLOGON /RL LIMITED /F >nul
if errorlevel 1 ( echo Could not create the startup task. Send Claude a photo of this window. & pause & exit /b 1 )
schtasks /Run /TN "YoMama Scan Agent" >nul

echo.
echo All set. The Scan Agent is running now and starts by itself every time you sign in.
echo Scan into E:\Scans\Claude Scans as usual. About 90 seconds after the last page,
echo the photos are uploaded and the scans move into "do not scan".
echo Its diary is scan_agent.log in this folder.
echo.
pause
