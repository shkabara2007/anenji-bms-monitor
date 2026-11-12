@echo off
setlocal
cd /d "%~dp0"
title ANENJI BMS Monitor 8.13 - Windows EXE

echo [1/4] Checking Python...
py --version
if errorlevel 1 goto ERROR

echo [2/4] Checking installed packages...
py -m PyInstaller --version
if errorlevel 1 goto ERROR
py -c "import bleak, aiobmsble, tkinter; print('BLE dependencies OK')"
if errorlevel 1 goto ERROR
py -m py_compile battery_gui_v8_13.py anenji_ble_direct.py
if errorlevel 1 goto ERROR

echo [3/4] Building ANENJI BMS 8.13...
py -m PyInstaller --noconfirm --clean --onefile --windowed --collect-all aiobmsble --collect-all bleak --name ANENJI_BMS_v8_13 battery_gui_v8_13.py
if errorlevel 1 goto ERROR

echo [4/4] Copying Windows EXE...
copy /Y "dist\ANENJI_BMS_v8_13.exe" "ANENJI_BMS_v8_13.exe" >nul
if errorlevel 1 goto ERROR
copy /Y "batteries.json" "dist\batteries.json" >nul
if errorlevel 1 goto ERROR

echo.
echo SUCCESS: %CD%\ANENJI_BMS_v8_13.exe
explorer.exe /select,"%CD%\ANENJI_BMS_v8_13.exe"
pause
exit /b 0

:ERROR
echo.
echo BUILD FAILED. Keep this window open and report the error text.
pause
exit /b 1
