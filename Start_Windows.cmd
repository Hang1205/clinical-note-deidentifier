@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" clinical_note_gui.py
) else (
  py -3 clinical_note_gui.py
)
if errorlevel 1 pause
