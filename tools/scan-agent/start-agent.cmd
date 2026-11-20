@echo off
cd /d "%~dp0"
call stop-agent.cmd quiet
for /f "delims=" %%i in ('py -3 -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYW=%%i"
start "" "%PYW%" "%~dp0scan_agent.py"
echo Scan Agent started.
pause
