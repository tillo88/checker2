param([int]$Port = 8501)

$ErrorActionPreference = "Stop"
$ProjectWinPath = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "=========================================="
Write-Host "  SpyEngine Client GUI Launcher"
Write-Host "=========================================="
Write-Host ""

$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if (-not $wsl) {
    Write-Host "ERRORE: wsl.exe non trovato."
    Read-Host "Premi INVIO per uscire"
    exit 1
}

if ($ProjectWinPath -like "\\wsl.localhost\*" -or $ProjectWinPath -like "\\wsl$\*") {
    $parts = $ProjectWinPath -split "\\"
    $rest = $parts[4..($parts.Length-1)] -join "/"
    $ProjectWslPath = "/" + $rest
} else {
    $ProjectWslPath = (wsl.exe wslpath -u "$ProjectWinPath").Trim()
}

Write-Host "Percorso Windows: $ProjectWinPath"
Write-Host "Percorso WSL:     $ProjectWslPath"
Write-Host "Avvio GUI su http://localhost:$Port ..."

$existsCmd = "test -f '$ProjectWslPath/spy_gui_v3.py' || test -f '$ProjectWslPath/scripts/run_gui.py'"
wsl.exe bash -lc $existsCmd
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRORE: non trovo spy_gui_v3.py o scripts/run_gui.py in $ProjectWslPath"
    Read-Host "Premi INVIO per uscire"
    exit 1
}

Start-Job -ScriptBlock {
    param($p)
    Start-Sleep -Seconds 4
    Start-Process "http://localhost:$p"
} -ArgumentList $Port | Out-Null

$runCmd = "cd '$ProjectWslPath' && if [ -f .venv/bin/activate ]; then source .venv/bin/activate; fi && if [ -f scripts/run_gui.py ]; then python scripts/run_gui.py; else python -m streamlit run spy_gui_v3.py --server.port $Port --server.address 0.0.0.0; fi"
wsl.exe bash -lc $runCmd

Read-Host "GUI terminata. Premi INVIO per uscire"
