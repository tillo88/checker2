@echo off
title SpyEngine GUI
REM Copia questo file in una cartella Windows locale, per esempio Desktop.
REM Modifica il path Linux se il progetto non è in ~/price_check_bot.
wsl.exe -e bash -lc "cd $HOME/price_check_bot && if [ -f .venv/bin/activate ]; then source .venv/bin/activate; fi && python scripts/run_gui.py"
pause
