# start_kronos.ps1 - registro hacia adelante de pronosticos de Kronos (H-KRON1).
#
# Proceso APARTE del bot (su propio entorno .venv_kronos con PyTorch CPU). No opera
# nada: dos veces por dia habil (00:00 y 12:00 UTC) lee velas H1 de MT5 en solo
# lectura, pronostica 12 h con Kronos-small y lo anota en
# trading_data\kronos_forward\rounds.csv. Cada ronda tarda ~6 min de CPU.
#
# USO (en su propia terminal, dejandola abierta):
#   .\start_kronos.ps1            # arranca el registro (Ctrl+C para cortar)
#   .\start_kronos.ps1 -Status    # solo cuenta rondas (no muestra resultados)
#   .\start_kronos.ps1 -Test      # una ronda de prueba ahora (NO cuenta)
#
# La primera vez: .\scripts\setup_kronos.ps1
# NOTA: archivo en ASCII puro a proposito (PowerShell 5.1 lee .ps1 sin BOM como ANSI).

param(
    [switch]$Status,
    [switch]$Test
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv_kronos\Scripts\python.exe"
$script = Join-Path $root "scripts\kronos_forward.py"

if (-not (Test-Path $py) -or -not (Test-Path (Join-Path $root "vendor\Kronos\model"))) {
    Write-Host "Falta el entorno de Kronos. Corre primero: .\scripts\setup_kronos.ps1"
    exit 1
}

if ($Status) { & $py $script --status --root $root; exit $LASTEXITCODE }
if ($Test) { & $py $script --once --root $root; exit $LASTEXITCODE }

$running = Get-CimInstance Win32_Process -Filter "name='python.exe'" |
    Where-Object { $_.CommandLine -like "*kronos_forward.py*--loop*" }
if ($running) {
    Write-Host ("Ya hay un registro de Kronos corriendo (PID " + ($running.ProcessId -join ", ") + "). No arranco otro.")
    exit 1
}

$Host.UI.RawUI.WindowTitle = "Kronos H-KRON1 (registro hacia adelante, no opera)"
Write-Host "Kronos H-KRON1: registro hacia adelante. Rondas 00:00 y 12:00 UTC en dias habiles."
Write-Host "No opera nada. Deja esta ventana abierta; Ctrl+C para cortar."
& $py $script --loop --root $root
