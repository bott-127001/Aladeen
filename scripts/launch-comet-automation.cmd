@echo off
setlocal

:: Target port and profile directory
set PORT=9223
set PROFILE_DIR=%USERPROFILE%\.comet-automation-profile

:: Locate Comet executable
set COMET_EXE=C:\Program Files\Perplexity\Comet\Application\comet.exe
if not exist "%COMET_EXE%" (
    set COMET_EXE=%LOCALAPPDATA%\Perplexity\Comet\Application\comet.exe
)
if not exist "%COMET_EXE%" (
    echo [ERROR] Comet executable not found at either:
    echo   - C:\Program Files\Perplexity\Comet\Application\comet.exe
    echo   - %LOCALAPPDATA%\Perplexity\Comet\Application\comet.exe
    echo Please verify Comet installation.
    exit /b 1
)

:: Detect if port 9223 is already occupied
netstat -ano | findstr /R /C:":%PORT% " >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [INFO] Port %PORT% is already in use by an active Comet automation instance.
    echo Automation endpoint is already listening at http://127.0.0.1:%PORT%
    echo No second instance launched.
    exit /b 0
)

echo Starting Comet automation instance on port %PORT%...
echo Profile: %PROFILE_DIR%
echo Executable: %COMET_EXE%

start "" "%COMET_EXE%" --user-data-dir="%PROFILE_DIR%" --remote-debugging-port=%PORT% --remote-debugging-address=127.0.0.1 --no-first-run --no-default-browser-check "https://www.perplexity.ai/"

echo Launch requested. Endpoint will be available at http://127.0.0.1:%PORT%
echo.
echo Targeted shutdown (leaves everyday Comet untouched):
echo   for /f "tokens=5" %%%%a in ('netstat -aon ^^! findstr :%PORT%') do taskkill /f /pid %%%%a
endlocal
