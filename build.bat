@echo off
cd /d "%~dp0"

echo.
echo  FinanceTracker - Build
echo  =======================
echo  Dir: %CD%
echo.

REM -- 0. Kill running instance --
taskkill /f /im FinanceTracker.exe >nul 2>&1

REM -- 1. Clean --
echo [1/3] Cleaning...

if exist build (
    rd /s /q build
    if exist build (
        echo  ERROR: Cannot delete "build". Close Explorer / antivirus and retry.
        pause & exit /b 1
    )
)

if exist dist (
    rd /s /q dist
    if exist dist (
        echo  ERROR: Cannot delete "dist". Close Explorer / antivirus and retry.
        pause & exit /b 1
    )
)

echo  Done.
echo.

REM -- 2. PyInstaller --
echo [2/3] Checking PyInstaller...

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo  Installing PyInstaller...
    python -m pip install pyinstaller --quiet
)
echo  Done.
echo.

REM -- 3. Build --
echo [3/3] Building...
echo.

if exist assets\icon.ico (
    python -m PyInstaller --noconfirm --onedir --windowed --name "FinanceTracker" --icon "assets\icon.ico" --add-data "assets;assets" --hidden-import "PyQt6.sip" --hidden-import "PyQt6.QtSvg" --hidden-import "matplotlib.backends.backend_qtagg" --collect-data "PyQt6" --collect-submodules "openpyxl" --collect-submodules "watchdog" main.py
) else (
    python -m PyInstaller --noconfirm --onedir --windowed --name "FinanceTracker" --add-data "assets;assets" --hidden-import "PyQt6.sip" --hidden-import "PyQt6.QtSvg" --hidden-import "matplotlib.backends.backend_qtagg" --collect-data "PyQt6" --collect-submodules "openpyxl" --collect-submodules "watchdog" main.py
)

REM -- Result --
echo.
if exist "dist\FinanceTracker\FinanceTracker.exe" (
    echo  ====================================
    echo   SUCCESS
    echo   dist\FinanceTracker\FinanceTracker.exe
    echo  ====================================
    rd /s /q build >nul 2>&1
) else (
    echo  ====================================
    echo   FAILED - see errors above
    echo  ====================================
)
echo.
pause
