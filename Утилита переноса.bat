@echo off
setlocal
cd /d "%~dp0"
rem запуск pythonw (GUI без консоли); если его нет - python с консолью
set "PYW="
for /f "usebackq delims=" %%i in (`where pythonw 2^>nul`) do if not defined PYW set "PYW=%%i"
if not defined PYW for /f "usebackq delims=" %%i in (`where python 2^>nul`) do set "PYW=%%i"
if not defined PYW (
  echo Python ne najden. Ustanovi Python 3.12+ s galochkoj "Add to PATH".
  pause
  exit /b 1
)
start "" "%PYW%" transfer_gui_ctk.py
exit /b 0