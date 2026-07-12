@echo off
setlocal EnableExtensions EnableDelayedExpansion
title SpyEngine Client GUI

echo.
echo ==========================================
echo   SpyEngine Client GUI Launcher
echo ==========================================
echo.

where wsl.exe >nul 2>nul
if errorlevel 1 (
    echo ERRORE: wsl.exe non trovato.
    echo Apri manualmente WSL e usa:
    echo   cd ~/price_check_bot
    echo   python -m streamlit run spy_gui_v3.py
    pause
    exit /b 1
)

set "WIN_DIR=%~dp0"
if "%WIN_DIR:~-1%"=="\" set "WIN_DIR=%WIN_DIR:~0,-1%"

REM Se il file viene lanciato da \\wsl.localhost, CMD mostra un warning UNC.
REM E' innocuo, ma pushd mappa temporaneamente il path UNC a una lettera disco.
pushd "%WIN_DIR%" >nul 2>nul

echo Percorso launcher:
echo   %WIN_DIR%
echo.

set "WSL_DIR="

echo %WIN_DIR% | findstr /I /B "\\\\wsl.localhost\\" >nul
if not errorlevel 1 (
    set "UNC_PATH=%WIN_DIR%"
    set "UNC_PATH=!UNC_PATH:\\wsl.localhost\=!"
    for /f "tokens=1,* delims=\" %%a in ("!UNC_PATH!") do (
        set "DISTRO=%%a"
        set "REST=%%b"
    )
    set "WSL_DIR=/!REST:\=/!"
    goto :got_path
)

echo %WIN_DIR% | findstr /I /B "\\\\wsl$\\" >nul
if not errorlevel 1 (
    set "UNC_PATH=%WIN_DIR%"
    set "UNC_PATH=!UNC_PATH:\\wsl$\=!"
    for /f "tokens=1,* delims=\" %%a in ("!UNC_PATH!") do (
        set "DISTRO=%%a"
        set "REST=%%b"
    )
    set "WSL_DIR=/!REST:\=/!"
    goto :got_path
)

for /f "usebackq delims=" %%i in (`wsl.exe wslpath -u "%WIN_DIR%"`) do set "WSL_DIR=%%i"

:got_path
if "%WSL_DIR%"=="" (
    echo ERRORE: impossibile determinare il percorso WSL.
    popd >nul 2>nul
    pause
    exit /b 1
)

echo Percorso WSL:
echo   %WSL_DIR%
echo.

wsl.exe bash -lc "test -f '%WSL_DIR%/spy_gui_v3.py' || test -f '%WSL_DIR%/scripts/run_gui.py'"
if errorlevel 1 (
    echo ERRORE: non trovo spy_gui_v3.py o scripts/run_gui.py in:
    echo   %WSL_DIR%
    popd >nul 2>nul
    pause
    exit /b 1
)

echo Avvio GUI su http://localhost:8501 ...
echo Chiudi questa finestra per fermare Streamlit.
echo.

start "" cmd /c "timeout /t 4 >nul && start http://localhost:8501"

wsl.exe bash -lc "cd '%WSL_DIR%' && if [ -f .venv/bin/activate ]; then source .venv/bin/activate; fi && if [ -f scripts/run_gui.py ]; then python scripts/run_gui.py; else python -m streamlit run spy_gui_v3.py --server.port 8501 --server.address 0.0.0.0; fi"

echo.
echo GUI terminata.
popd >nul 2>nul
pause
