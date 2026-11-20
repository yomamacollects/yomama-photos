@echo off
schtasks /Delete /TN "YoMama Scan Agent" /F
py -3 -c "import keyring;keyring.delete_password('yomama-scan-agent','github-token')" 2>nul
echo Scan Agent removed from startup and its GitHub key deleted. You can delete this folder.
pause
