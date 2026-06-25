@echo off
echo Starting RIWI Match API (FastAPI + Celery)...

REM FastAPI
start "RIWI API" cmd /k ".venv\Scripts\uvicorn.exe src.api.main:app --reload --port 8000"

REM Celery worker (pool=solo para Windows con Python 3.13)
start "RIWI Celery" cmd /k ".venv\Scripts\celery.exe -A src.infrastructure.workers.celery_app worker --loglevel=info --pool=solo"

echo Both services started. Close the windows to stop them.
