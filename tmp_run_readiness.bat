@echo off
set "STORAGE_ROOT=%TEMP%\pz-readiness-storage"
set "SERIES_BOOTSTRAP_ENABLED=false"
set "PYTHONIOENCODING=utf-8"
cd /d "C:\PZ-wt-readiness\service"
"C:\Users\Super Fashion\AppData\Local\Programs\Python\Python39\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 47997
