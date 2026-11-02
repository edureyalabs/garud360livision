REM scripts/setup_windows.bat
REM One-time setup on Windows: creates a virtual environment and installs everything.
@echo off
setlocal
cd /d "%~dp0\.."

echo ================================================
echo  Garud 360 Li-Vision - setup
echo ================================================

set PYEXE=
where py >nul 2>nul
if %errorlevel%==0 (
    py -3.11 --version >nul 2>nul && set PYEXE=py -3.11
    if not defined PYEXE py -3.12 --version >nul 2>nul && set PYEXE=py -3.12
    if not defined PYEXE py -3.10 --version >nul 2>nul && set PYEXE=py -3.10
)
if not defined PYEXE (
    where python >nul 2>nul && set PYEXE=python
)
if not defined PYEXE (
    echo ERROR: Python 3.10, 3.11 or 3.12 was not found.
    echo Install Python 3.11 from https://www.python.org/downloads/windows/ and tick "Add python.exe to PATH".
    pause
    exit /b 1
)
echo Using: %PYEXE%
%PYEXE% --version

if not exist ".venv\Scripts\python.exe" (
    %PYEXE% -m venv .venv
    if errorlevel 1 ( echo Could not create the virtual environment. & pause & exit /b 1 )
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 ( echo pip upgrade failed. & pause & exit /b 1 )

echo.
set /p GPU="Do you have an NVIDIA GPU and want GPU acceleration? (y/N): "
if /i "%GPU%"=="y" (
    echo Installing PyTorch with CUDA 12.4 support ...
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
    if errorlevel 1 ( echo PyTorch GPU install failed. & pause & exit /b 1 )
)

echo Installing application requirements (this can take several minutes) ...
pip install -r requirements.txt
if errorlevel 1 ( echo Installing requirements failed. Check your internet connection and retry. & pause & exit /b 1 )

echo Creating desktop shortcut ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_shortcut.ps1"

echo.
echo ================================================
echo  Setup finished.  Start the app with run_garud360.bat
echo  (or the "Garud 360 Li-Vision" shortcut on your desktop).
echo ================================================
pause
