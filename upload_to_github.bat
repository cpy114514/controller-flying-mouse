@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "REPO_NAME=controller-flying-mouse"
set "REPO_DESCRIPTION=Joy-Con gyro air mouse for Windows"

echo.
echo ==========================================
echo  Upload Joy-Con Gyro Air Mouse to GitHub
echo ==========================================
echo.

where git >nul 2>nul
if errorlevel 1 (
    echo Git was not found. Please install Git for Windows first:
    echo https://git-scm.com/download/win
    echo.
    pause
    exit /b 1
)

where gh >nul 2>nul
if errorlevel 1 (
    echo GitHub CLI was not found. Please install it first:
    echo https://cli.github.com/
    echo.
    pause
    exit /b 1
)

if not exist ".git" (
    echo Initializing local git repository...
    git init
    if errorlevel 1 goto failed
)

gh auth status >nul 2>nul
if errorlevel 1 (
    echo You are not logged into GitHub yet.
    echo A browser login will open. Finish the GitHub login, then return here.
    echo.
    gh auth login --hostname github.com --web --git-protocol https
    if errorlevel 1 goto failed
)

git status --porcelain > "%TEMP%\controller_flying_mouse_status.txt"
for %%A in ("%TEMP%\controller_flying_mouse_status.txt") do set "STATUS_SIZE=%%~zA"
if not "%STATUS_SIZE%"=="0" (
    echo Saving local changes into a commit...
    git add -A
    if errorlevel 1 goto failed

    git commit -m "Update Joy-Con gyro air mouse"
    if errorlevel 1 goto failed
) else (
    echo No uncommitted local changes.
)
del "%TEMP%\controller_flying_mouse_status.txt" >nul 2>nul

for /f "usebackq delims=" %%B in (`git branch --show-current`) do set "BRANCH=%%B"
if "%BRANCH%"=="" set "BRANCH=master"

git remote get-url origin >nul 2>nul
if errorlevel 1 (
    echo.
    echo Creating GitHub repository: %REPO_NAME%
    gh repo create "%REPO_NAME%" --private --description "%REPO_DESCRIPTION%" --source . --remote origin
    if errorlevel 1 (
        echo.
        echo Automatic repo creation failed.
        echo If the repo already exists, paste its GitHub URL here.
        set /p "REMOTE_URL=GitHub repo URL: "
        if "!REMOTE_URL!"=="" goto failed
        git remote add origin "!REMOTE_URL!"
        if errorlevel 1 goto failed
    )
)

echo.
echo Pushing branch "%BRANCH%" to GitHub...
git push -u origin "%BRANCH%"
if errorlevel 1 goto failed

echo.
echo Upload complete.
gh repo view --web
echo.
pause
exit /b 0

:failed
echo.
echo Upload failed. Read the message above, then try again.
echo.
pause
exit /b 1
