REM scripts/run_garud360.bat
REM Starts Garud 360 Li-Vision from the source checkout (after setup_windows.bat).
@echo off
cd /d "%~dp0\.."
if not exist ".venv\Scripts\pythonw.exe" (
    echo Please run scripts\setup_windows.bat first.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m garud360 %*
