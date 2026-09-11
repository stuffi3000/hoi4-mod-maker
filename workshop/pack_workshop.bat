@echo off
REM === HOI4 Map Maker Workshop deploy wrapper ===
REM The deployment logic lives in deploy.ps1; this wrapper enables double-click execution.
REM
REM See the header of deploy.ps1 for the safety rules.
REM Run ..\build_exe.bat first to create dist/HOI4MapMaker/.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1"
pause
