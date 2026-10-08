@echo off
setlocal
cd /d "%~dp0"
if not exist "wheelhouse\en_core_web_lg-3.8.0-py3-none-any.whl" (
  echo Use the complete Windows offline kit, including wheelhouse.
  pause
  exit /b 1
)
py -3.12 -c "import struct; assert struct.calcsize('P') == 8"
if errorlevel 1 (
  echo Install Python 3.12 64-bit with Tkinter and the Python launcher first.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install --no-index --disable-pip-version-check --find-links wheelhouse -r requirements_windows_py312.lock.txt
if errorlevel 1 (
  echo Installation failed. No network fallback is used.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import spacy; assert 'ner' in spacy.load('en_core_web_lg').pipe_names; print('Local model ready. Run Start_Windows.cmd.')"
if errorlevel 1 exit /b 1
pause
