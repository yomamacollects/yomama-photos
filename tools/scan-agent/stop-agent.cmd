@echo off
rem Stops the Scan Agent until you sign in again (or run start-agent.cmd).
schtasks /End /TN "YoMama Scan Agent" >nul && echo Scan Agent stopped. || echo It was not running.
pause
