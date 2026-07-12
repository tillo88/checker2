@echo off
setlocal EnableExtensions
title SpyEngine Client

rem Non ereditare la directory UNC del doppio click.
cd /d "%USERPROFILE%"

where wsl.exe >nul 2>nul
if errorlevel 1 (
  echo ERRORE: WSL non e installato o wsl.exe non e nel PATH.
  pause
  exit /b 1
)

set "DISTRO=Ubuntu"
set "PROJECT=/home/tillo/price_check_bot"

wsl.exe -d "%DISTRO%" --cd "%PROJECT%" test -x ./.venv/bin/python
if errorlevel 1 (
  echo ERRORE: virtualenv Linux non trovata in %PROJECT%/.venv
  pause
  exit /b 1
)

wsl.exe -d "%DISTRO%" --cd "%PROJECT%" test -f ./scripts/run_gui.py
if errorlevel 1 (
  echo ERRORE: scripts/run_gui.py non trovato in %PROJECT%
  pause
  exit /b 1
)

echo Avvio SpyEngine da %PROJECT%...
wsl.exe -d "%DISTRO%" --cd "%PROJECT%" ./.venv/bin/python ./scripts/run_gui.py

if errorlevel 1 echo SpyEngine terminato con errore.
