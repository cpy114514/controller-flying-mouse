@echo off
setlocal
cd /d "%~dp0"

if not exist ".deps\python\hid*.pyd" (
    echo Installing local Python dependency: hidapi
    py -3 -m pip install --upgrade --target ".deps\python" hidapi
    if errorlevel 1 (
        echo.
        echo Failed to install hidapi.
        pause
        exit /b 1
    )
)

if not exist ".deps\python\pystray" (
    echo Installing local Python dependency: pystray
    py -3 -m pip install --upgrade --target ".deps\python" pystray
    if errorlevel 1 (
        echo.
        echo Failed to install pystray.
        pause
        exit /b 1
    )
)

set PYTHONPATH=%CD%\.deps\python;%PYTHONPATH%

py -3 app.py
if errorlevel 1 (
    echo.
    echo Python was not found.
    echo Install Python from https://www.python.org/downloads/
    echo During install, enable "Add python.exe to PATH".
    echo.
    pause
)
