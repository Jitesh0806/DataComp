@echo off
echo.
echo  VIDCOMP - Custom Video Compression Codec v2.4.1
echo  ─────────────────────────────────────────────────
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Python not found. Install from python.org
    pause
    exit /b 1
)

python -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo  Installing dependencies...
    pip install -r requirements.txt
)

echo  Starting backend server...
echo  Open: http://localhost:5000
echo  Press Ctrl+C to stop.
echo.

cd backend && python app.py
pause
