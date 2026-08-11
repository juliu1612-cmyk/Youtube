@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

echo ============================================
echo   YouTube Downloader - Windows Build Script
echo ============================================
echo.

:: Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ from https://python.org
    echo         Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

:: Show Python version
echo [1/5] Python found:
python --version
echo.

:: Create virtual environment
echo [2/5] Creating virtual environment...
if exist venv (
    echo       venv already exists, reusing...
) else (
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)
echo.

:: Install dependencies
echo [3/5] Installing dependencies...
call venv\Scripts\activate.bat
pip install --upgrade pip >nul 2>&1
pip install yt-dlp pywebview pyinstaller pythonnet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    echo         Try: pip install yt-dlp pywebview pyinstaller pythonnet
    pause
    exit /b 1
)
echo.

:: Build
echo [4/5] Building YouTubeDownloader.exe...
pyinstaller YouTubeDownloader_Windows.spec --noconfirm --clean
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)
echo.

:: Done
echo [5/5] Build complete!
echo.
echo ============================================
echo   SUCCESS!
echo ============================================
echo.
echo   Output folder: dist\YouTubeDownloader\
echo   Main exe:      dist\YouTubeDownloader\YouTubeDownloader.exe
echo.
echo   To distribute: zip the dist\YouTubeDownloader\ folder
echo   and send it to others. They just need to double-click
echo   YouTubeDownloader.exe to run it.
echo.
echo   Note: Windows 10/11 has WebView2 pre-installed.
echo   If it doesn't work, download WebView2 Runtime from:
echo   https://developer.microsoft.com/microsoft-edge/webview2/
echo.
pause
