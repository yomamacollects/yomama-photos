@echo off
schtasks /Run /TN "YoMama Scan Agent" >nul && echo Scan Agent started. || echo Could not start it. Run setup.cmd first.
pause
