@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 install.py
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python 3.12 is required. Install it, then run this file again.
        start "" "https://www.python.org/downloads/windows/"
        pause
        exit /b 1
    )
    python install.py
)
if errorlevel 1 (
    echo Installation failed. Read the error above and retry.
    pause
    exit /b 1
)
pause
