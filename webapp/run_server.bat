@echo off
REM Start the Market Big Picture Watch web server.
REM First time: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
cd /d "%~dp0"
call .venv\Scripts\activate.bat
uvicorn app.main:app --host 0.0.0.0 --port 8000
