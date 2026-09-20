# AetherHome IoT Controller PowerShell Runner
Set-Location $PSScriptRoot
Write-Host "Starting AetherHome IoT Controller from $PSScriptRoot..." -ForegroundColor Cyan
& ".\.venv\Scripts\python.exe" launcher.py
