@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run scripts\setup.ps1 first.
  pause
  exit /b 1
)
set ESTATE_ADMIN_LOCAL=1
".venv\Scripts\python.exe" -m streamlit run admin.py --server.address 127.0.0.1 --server.port 8502
pause
