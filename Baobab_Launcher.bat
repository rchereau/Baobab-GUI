@echo off
setlocal EnableExtensions
title Baobab HPC Launcher
cd /d "%~dp0"

set "VENV=%~dp0.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "VPYW=%VENV%\Scripts\pythonw.exe"
set "KEY=%USERPROFILE%\.ssh\id_rsa"

rem ---------------------------------------------------------------
rem 1. Private environment already set up? Go to dependency check.
rem ---------------------------------------------------------------
if exist "%VPY%" goto :check_deps

echo ==========================================================
echo    Baobab HPC - first-time setup
echo ==========================================================
echo.

rem ---------------------------------------------------------------
rem 2. Find Python 3.9 or newer
rem    py launcher first, then find_python.ps1 (registry, PATH,
rem    conda, usual folders, disk search), then ask the user.
rem ---------------------------------------------------------------
:find_python
set "PYEXE="
for %%V in (3.13 3.12 3.11 3.10 3.9) do call :try_pyver %%V
if defined PYEXE goto :make_venv
echo Looking for Python on this computer ...
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find_python.ps1"`) do set PYEXE="%%P"
if defined PYEXE goto :make_venv
goto :ask_python

:make_venv
echo [Setup] Using Python: %PYEXE%
echo [Setup] Creating a private Python environment in .venv ...
%PYEXE% -m venv "%VENV%"
if errorlevel 1 goto :venv_fail

rem ---------------------------------------------------------------
rem 3. Dependencies (installed once, re-installed if missing)
rem ---------------------------------------------------------------
:check_deps
rem A conda-based Python needs its Library\bin folder on PATH (SSL, etc.)
set "PYBASE="
"%VPY%" -c "import sys;print(sys.base_prefix)" > "%TEMP%\baobab_base.txt" 2>nul
set /p PYBASE=<"%TEMP%\baobab_base.txt"
if defined PYBASE if exist "%PYBASE%\Library\bin" set "PATH=%PYBASE%\Library\bin;%PATH%"
"%VPY%" -c "import PySide6, paramiko" >nul 2>&1
if not errorlevel 1 goto :check_key
echo [Setup] Installing PySide6 and Paramiko - this happens only once
echo         and can take a couple of minutes ...
echo.
"%VPY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%VPY%" -m pip install -r "%~dp0requirements.txt" --disable-pip-version-check
"%VPY%" -c "import PySide6, paramiko" >nul 2>&1
if errorlevel 1 goto :pip_fail
echo.
echo [Setup] Done.
echo.

rem ---------------------------------------------------------------
rem 4. SSH key present? Offer to create one.
rem ---------------------------------------------------------------
:check_key
if exist "%KEY%" goto :launch
if exist "%USERPROFILE%\.ssh\id_ed25519" goto :launch
echo No SSH key found at %KEY%
echo Baobab only accepts SSH-key logins, so you need one.
echo.
echo  IMPORTANT - already using Baobab from another computer?
echo  Then press N, and copy the files id_rsa and id_rsa.pub from that
echo  computer's .ssh folder into %USERPROFILE%\.ssh
echo  my-account.unige.ch keeps only ONE key: registering a new one
echo  REPLACES the old one, and the other computer loses its access.
echo.
choice /C YN /M "Generate a NEW SSH key now"
if errorlevel 2 goto :launch
if not exist "%USERPROFILE%\.ssh" mkdir "%USERPROFILE%\.ssh"
echo.
echo You will be asked for a passphrase. Press Enter twice for none,
echo or choose one - the app will then ask for it at start-up.
echo.
ssh-keygen -t rsa -b 4096 -f "%KEY%"
if errorlevel 1 goto :keygen_fail
type "%KEY%.pub" | clip
echo.
echo ----------------------------------------------------------
echo  Your PUBLIC key is now in the clipboard.
echo  1. The UNIGE account page opens in your browser.
echo  2. Paste it under "My SSH public key" and save.
echo  3. Wait 10-15 minutes before connecting.
echo ----------------------------------------------------------
start "" https://my-account.unige.ch
echo.
pause

rem ---------------------------------------------------------------
rem 5. Check the app loads, then start it without a console window
rem ---------------------------------------------------------------
:launch
rem First run: shortcuts with the app icon (desktop, Start menu, this folder)
if not exist "%~dp0Baobab HPC.lnk" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0make_shortcut.ps1" -AppDir "%~dp0." >nul 2>&1
rem Qt paths set by other programs (Anaconda, QGIS...) break PySide6
set "QT_PLUGIN_PATH="
set "QT_QPA_PLATFORM_PLUGIN_PATH="
"%VPY%" -c "import baobab_app" 2>"%TEMP%\baobab_launch_error.txt"
if errorlevel 1 goto :app_fail
set "APPDATA_DIR=%USERPROFILE%\.baobab_hpc"
if exist "%APPDATA_DIR%\started.txt" del "%APPDATA_DIR%\started.txt" >nul 2>&1
start "" "%VPYW%" "%~dp0baobab_app.py"
echo Opening Baobab HPC ...
rem Wait up to 45 s for the window to confirm it opened
for /l %%i in (1,1,45) do (
    if exist "%APPDATA_DIR%\started.txt" exit /b 0
    timeout /t 1 /nobreak >nul
)
goto :window_fail

:window_fail
echo.
echo ==========================================================
echo  The window did not open. Last messages from the app:
echo ==========================================================
powershell -NoProfile -Command "foreach ($f in 'app.log','crash.log') { $p = Join-Path '%APPDATA_DIR%' $f; if (Test-Path $p) { Write-Output ('--- ' + $f); Get-Content -Tail 25 $p } }"
echo.
echo ==========================================================
echo  Running the app again with its messages visible ...
echo ==========================================================
"%VPY%" "%~dp0baobab_app.py"
echo.
echo If you need help, copy everything in this window and send it.
pause
exit /b 1

:app_fail
echo ERROR: the app could not start:
echo.
type "%TEMP%\baobab_launch_error.txt"
echo.
echo Make sure baobab_app.py and baobab_core.py are in this folder.
echo To reinstall the dependencies, delete the .venv folder and relaunch.
pause
exit /b 1

rem ---------------------------------------------------------------
rem Subroutine: accept %1 if it is a working Python 3.9+
rem ---------------------------------------------------------------
:try_py
if defined PYEXE exit /b 0
if not exist "%~1" exit /b 0
"%~1" -c "import sys, struct; sys.exit(0 if sys.version_info >= (3, 9) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
set PYEXE="%~1"
exit /b 0

:try_pyver
if defined PYEXE exit /b 0
py -%1 -c "import sys, struct; sys.exit(0 if struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
set "PYEXE=py -%1"
exit /b 0

:ask_python
echo No usable 64-bit Python 3.9 or newer was found automatically.
echo.
echo Pythons found on this computer:
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find_python.ps1" -List
echo.
echo When you type "python", Windows finds:
where python 2>nul
if errorlevel 1 echo    (nothing)
echo.
echo If you know where python.exe is, drag it into this window and
echo press Enter. Leave empty and press Enter to install Python instead.
echo.
set "USERPY="
set /p USERPY="python.exe: "
if not defined USERPY goto :install_python
set USERPY=%USERPY:"=%
call :try_py "%USERPY%"
if defined PYEXE goto :make_venv
echo.
echo That file is not a working 64-bit Python 3.9 or newer.
echo.
goto :ask_python

:install_python
winget --version >nul 2>&1
if errorlevel 1 goto :no_winget
echo Installing Python 3.12 with winget ...
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
echo.
echo Python is installed. Close this window and run the launcher again.
pause
exit /b 1

:no_winget
echo Please install Python 3 from https://www.python.org/downloads/
echo During installation, tick "Add python.exe to PATH".
echo Then run this launcher again.
start "" https://www.python.org/downloads/
pause
exit /b 1

:venv_fail
echo ERROR: could not create the Python environment.
echo Delete the .venv folder and run the launcher again.
pause
exit /b 1

:pip_fail
rem Built with a 32-bit or too-new Python? Rebuild once with another one.
if defined REBUILT goto :pip_fail_msg
"%VPY%" -c "import sys, struct; sys.exit(0 if struct.calcsize('P') == 8 and sys.version_info < (3, 14) else 1)" >nul 2>&1
if not errorlevel 1 goto :pip_fail_msg
echo.
echo The environment was built with a Python that PySide6 does not support.
echo Rebuilding it with another Python ...
echo.
set "REBUILT=1"
rmdir /s /q "%VENV%"
goto :find_python

:pip_fail_msg
echo.
echo ==========================================================
echo  ERROR: PySide6 / Paramiko could not be installed.
echo ==========================================================
echo The private environment uses this Python:
"%VPY%" -c "import sys, platform; print('   ', sys.version.split()[0], platform.architecture()[0], platform.machine()); print('   ', sys.base_prefix)"
echo.
echo  - "No matching distribution found for PySide6" means this Python
echo    is 32-bit or too new for PySide6. Delete the .venv folder and
echo    run the launcher again: it will pick another Python. If none is
echo    suitable, install 64-bit Python 3.12 from python.org.
echo  - Network errors: check your internet connection and retry.
echo.
echo The messages above show pip's exact error.
pause
exit /b 1

:keygen_fail
echo ERROR: ssh-keygen failed. See the manual procedure in README.md.
pause
exit /b 1
