@echo off
setlocal

REM PillClear one-click launcher: backend uvicorn :8000 + frontend vite :5173
REM Keep this file ASCII-only: cmd.exe parses batch files in the system
REM codepage, and UTF-8 Chinese text corrupts block parsing on zh-CN Windows.

cd /d "%~dp0"
if errorlevel 1 (
    echo [PillClear] ERROR: cannot enter script directory: %~dp0
    exit /b 1
)

REM -- backend environment check --
where uvicorn >nul 2>&1
if errorlevel 1 (
    echo [PillClear] ERROR: uvicorn not found. Install backend dependencies first:
    echo     pip install -e ".[dev]"
    exit /b 1
)
if not exist ".env" echo [PillClear] WARNING: .env not found. Copy .env.example to .env and set DEEPSEEK_API_KEY, the only required variable.

REM -- frontend dependencies: check the vite executable, not just the folder;
REM -- a partially installed node_modules still counts as missing.
if exist "web\node_modules\.bin\vite.cmd" goto deps_ok
echo [PillClear] First run: installing frontend dependencies...
pushd "web"
call npm install
set "NPM_ERR=%ERRORLEVEL%"
popd
if %NPM_ERR% neq 0 (
    echo [PillClear] ERROR: npm install failed with exit code %NPM_ERR%. Check network or registry, then re-run this script.
    exit /b %NPM_ERR%
)
if not exist "web\node_modules\.bin\vite.cmd" (
    echo [PillClear] ERROR: npm install finished but vite is missing. Delete web\node_modules and re-run.
    exit /b 1
)
:deps_ok

echo [PillClear] Starting backend:  http://localhost:8000
start "PillClear-backend-8000" cmd /k "cd /d "%~dp0" && uvicorn app.main:app --reload"

echo [PillClear] Starting frontend: http://localhost:5173
start "PillClear-frontend-5173" cmd /k "cd /d "%~dp0web" && npm run dev"

echo.
echo [PillClear] Open http://localhost:5173 in your browser.
echo [PillClear] Close the backend/frontend windows to stop.
pause
