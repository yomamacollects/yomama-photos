@echo off
cd /d "%~dp0"
call stop-agent.cmd quiet
schtasks /Delete /TN "YoMama Scan Agent" /F >nul 2>nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\YoMama Scan Agent.lnk" >nul 2>nul
powershell -NoProfile -Command "Remove-Item -ErrorAction SilentlyContinue ([Environment]::GetFolderPath('Startup')+'\YoMama Scan Agent.lnk')"
py -3 -c "import keyring;keyring.delete_password('yomama-scan-agent','github-token')" 2>nul
echo Scan Agent removed from startup and its GitHub key deleted. You can delete this folder.
pause
