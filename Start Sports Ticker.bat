@echo off
setlocal
title Sports Ticker
cd /d "%~dp0"

call :findpy
if defined PYW goto run

echo.
echo  The Sports Ticker needs Python (free, from python.org), and it isn't
echo  installed on this PC yet. I can install it for you now. It takes about
echo  a minute and doesn't need administrator rights.
echo.
choice /c YN /m " Install Python now"
if errorlevel 2 goto manual

where winget >nul 2>nul
if errorlevel 1 goto manual

echo.
echo  Installing Python... (a progress bar will appear below)
winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
call :findpy
if defined PYW goto run

:manual
echo.
echo  Please install Python yourself:
echo    1. Your browser will open the python.org download page.
echo    2. Click the yellow "Download Python" button and run the installer.
echo    3. On the first screen, tick "Add python.exe to PATH", then click Install Now.
echo    4. When it finishes, double-click "Start Sports Ticker.bat" again.
echo.
start "" "https://www.python.org/downloads/"
pause
exit /b 1

:run
start "" "%PYW%" "%~dp0sports_ticker.pyw"
exit /b 0


REM ---- Look for pythonw.exe / pyw.exe in all the usual places ----
:findpy
set "PYW="
for /f "delims=" %%I in ('where pyw.exe 2^>nul') do if not defined PYW set "PYW=%%I"
for /f "delims=" %%I in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%I"
REM Ignore the Microsoft Store placeholder, which isn't a real Python.
if defined PYW echo "%PYW%" | find /i "WindowsApps" >nul && set "PYW="
if not defined PYW if exist "%LocalAppData%\Programs\Python\Launcher\pyw.exe" set "PYW=%LocalAppData%\Programs\Python\Launcher\pyw.exe"
if not defined PYW if exist "%SystemRoot%\pyw.exe" set "PYW=%SystemRoot%\pyw.exe"
if not defined PYW for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do if exist "%%D\pythonw.exe" set "PYW=%%D\pythonw.exe"
if not defined PYW for /d %%D in ("%ProgramFiles%\Python3*") do if exist "%%D\pythonw.exe" set "PYW=%%D\pythonw.exe"
exit /b
