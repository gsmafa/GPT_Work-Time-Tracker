@echo off
cd /d "%~dp0"
python launch.py
if errorlevel 1 (
 echo.
 echo Python failed. Try: python launch.py
 pause
)
