@echo off
REM Download fresh data and rebuild figures. Called by Windows Task Scheduler
REM (see register_task.bat) or run manually. Logs to data\update.log.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m app.update >> data\update.log 2>&1
