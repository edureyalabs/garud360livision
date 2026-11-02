REM scripts/run_garud360_console.bat
REM Same as run_garud360.bat but keeps a console window open so you can see errors.
@echo off
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
    echo Please run scripts\setup_windows.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m garud360 %*
pause
