@echo off
REM Run the FastAPI server from the correct directory
echo Starting FastAPI server...
echo.
echo Current directory: %cd%
echo.

REM Check if we're in the right directory
if not exist "app\main.py" (
    echo ERROR: Not in the correct directory!
    echo Please run this from the candidate_kit folder
    echo.
    pause
    exit /b 1
)

REM Check if venv exists
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found!
    echo Please create it first with: python -m venv .venv
    echo.
    pause
    exit /b 1
)

REM Run uvicorn
echo Starting server with auto-reload...
echo Open http://localhost:8000/docs in your browser
echo Press Ctrl+C to stop the server
echo.

.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --reload
