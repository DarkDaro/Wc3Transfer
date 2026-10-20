@echo off
setlocal
cd /d "%~dp0"

rem Порядок: закреплённый py -3.14 (в него установлен полный набор
rem пакетов и тесты) -> любой дефолт py/pyw -> python из PATH.
set "CMD="
set "VER="

pyw -3.14 --version >nul 2>nul
if not errorlevel 1 set "CMD=pyw" & set "VER=-3.14"
if defined CMD goto run

py -3.14 --version >nul 2>nul
if not errorlevel 1 set "CMD=py" & set "VER=-3.14"
if defined CMD goto run

pyw --version >nul 2>nul
if not errorlevel 1 set "CMD=pyw" & set "VER="
if defined CMD goto run

py --version >nul 2>nul
if not errorlevel 1 set "CMD=py" & set "VER="
if defined CMD goto run

where python >nul 2>nul
if not errorlevel 1 set "CMD=python" & set "VER="
if defined CMD goto run

echo Python ne najden. Ustanovi Python 3.12+ s galochkoj "Add to PATH",
echo zatem: pip install customtkinter==6.0.0
pause
exit /b 1

:run
start "" %CMD% %VER% transfer_gui_ctk.py
exit /b 0