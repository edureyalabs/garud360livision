REM scripts/update_windows.bat
REM Pulls the latest code from GitHub and refreshes the dependencies. Your data (database, snapshots) is untouched.
@echo off
cd /d "%~dp0\.."
git pull
if errorlevel 1 ( echo git pull failed. & pause & exit /b 1 )
call ".venv\Scripts\activate.bat"
pip install -r requirements.txt
echo Update finished.
pause
