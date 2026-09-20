@echo off
title AetherHome IoT Controller
cd /d "%~dp0"
echo Starting AetherHome IoT Controller...
.\.venv\Scripts\python.exe launcher.py
pause
