@echo off
setlocal
cd /d "%~dp0"

if not exist ".deps\python\hid*.pyd" (
    py -3 -m pip install --upgrade --target ".deps\python" hidapi
    if errorlevel 1 exit /b 1
)

if not exist ".deps\python\PyInstaller" (
    py -3 -m pip install --upgrade --target ".deps\python" pyinstaller
    if errorlevel 1 exit /b 1
)

if not exist ".deps\python\pystray" (
    py -3 -m pip install --upgrade --target ".deps\python" pystray
    if errorlevel 1 exit /b 1
)

set PYTHONPATH=%CD%\.deps\python;%PYTHONPATH%

py -3 -m PyInstaller --noconfirm --onefile --windowed --name JoyConGyroAirMouse --paths .deps\python --hidden-import hid --hidden-import pystray --hidden-import pystray._win32 --hidden-import PIL.Image --hidden-import PIL.ImageDraw app.py

if errorlevel 1 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo Built dist\JoyConGyroAirMouse.exe
pause
