@echo off
setlocal
title Build SportsTicker.exe
REM Builds a standalone SportsTicker.exe (no Python needed to run it afterwards).
cd /d "%~dp0"

call :findpy
if not defined PY (
    echo Python isn't installed. Run "Start Sports Ticker.bat" first - it can install it for you.
    pause
    exit /b 1
)

echo Installing PyInstaller...
"%PY%" -m pip install --upgrade pyinstaller || goto :fail
echo Building...
"%PY%" -m PyInstaller --onefile --noconsole --name SportsTicker --icon sports_ticker.ico --add-data "CHANGELOG.md;." --add-data "sports_ticker.ico;." sports_ticker.pyw || goto :fail
echo.
echo Done! Your app is at: %~dp0dist\SportsTicker.exe
explorer "%~dp0dist"
pause
exit /b 0

:fail
echo Build failed.
pause
exit /b 1

:findpy
set "PY="
for /f "delims=" %%I in ('where py.exe 2^>nul') do if not defined PY set "PY=%%I"
for /f "delims=" %%I in ('where python.exe 2^>nul') do if not defined PY set "PY=%%I"
if defined PY echo "%PY%" | find /i "WindowsApps" >nul && set "PY="
if not defined PY if exist "%LocalAppData%\Programs\Python\Launcher\py.exe" set "PY=%LocalAppData%\Programs\Python\Launcher\py.exe"
if not defined PY if exist "%SystemRoot%\py.exe" set "PY=%SystemRoot%\py.exe"
if not defined PY for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if not defined PY for /d %%D in ("%ProgramFiles%\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
exit /b
