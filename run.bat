@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run scripts\setup.ps1 first. Python 3.12 or newer is recommended.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1
pause
