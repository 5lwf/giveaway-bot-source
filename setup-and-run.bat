@echo off
setlocal
title GiveawayBot Setup and Launcher
cd /d "%~dp0"

echo ========================================
echo        GiveawayBot Setup and Run
echo ========================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_CMD=py"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PYTHON_CMD=python"
    ) else (
        echo Python was not found on this PC.
        echo Install Python 3.11 or newer from https://www.python.org/downloads/
        echo IMPORTANT: enable "Add Python to PATH" during installation.
        echo.
        pause
        exit /b 1
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating the private Python environment...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto :failed
) else (
    echo [1/4] Python environment is ready.
)

echo [2/4] Installing or updating requirements...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :failed

if not exist ".env" (
    echo [3/4] Creating your private configuration file...
    copy /y ".env.example" ".env" >nul
    echo.
    echo Add your Discord bot token after DISCORD_TOKEN= in the file that opens.
    echo Save it, close Notepad, then return here.
    start "" /wait notepad.exe ".env"
) else (
    echo [3/4] Configuration file found.
)

findstr /r /c:"^DISCORD_TOKEN=..*" ".env" >nul 2>nul
if errorlevel 1 (
    echo.
    echo Your bot token is missing from .env.
    echo Add it after DISCORD_TOKEN=, save the file, then run this BAT again.
    start "" notepad.exe ".env"
    pause
    exit /b 1
)

findstr /x /c:"DISCORD_TOKEN=paste-your-bot-token-here" ".env" >nul 2>nul
if not errorlevel 1 (
    echo.
    echo Replace the example token in .env with your real Discord bot token.
    start "" notepad.exe ".env"
    pause
    exit /b 1
)

echo [4/4] Starting GiveawayBot...
echo Close this window or press Ctrl+C to stop the bot.
echo.
".venv\Scripts\python.exe" main.py

echo.
echo GiveawayBot stopped.
pause
exit /b 0

:failed
echo.
echo Setup failed. Read the error above, then run this BAT again.
pause
exit /b 1
