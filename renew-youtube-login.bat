@echo off
rem Renews ClipBot's YouTube login (Google expires it every 7 days while the app is in Testing).
cd /d "%~dp0"
".venv\Scripts\python.exe" -m clipbot.youtube_login
echo.
pause
