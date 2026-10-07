# setup_kronos.ps1 - entorno APARTE para la prueba hacia adelante de Kronos (H-KRON1).
#
# Crea .venv_kronos (NO toca el .venv del bot), instala PyTorch CPU + lo que pide
# Kronos + MetaTrader5 (solo lectura de velas), clona el codigo de Kronos en
# vendor\Kronos en el commit fijado del pre-registro y baja los pesos del modelo
# (Hugging Face) a vendor\hf_cache en las revisiones fijadas.
#
# USO (una sola vez; tarda unos minutos y baja ~1 GB):
#   .\scripts\setup_kronos.ps1
# Despues: .\start_kronos.ps1
#
# NOTA: archivo en ASCII puro a proposito (PowerShell 5.1 lee .ps1 sin BOM como ANSI).

param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$KronosCommit = "",
    [switch]$SkipModels
)

$ErrorActionPreference = "Stop"
$botPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$venv = Join-Path $RepoRoot ".venv_kronos"
$py = Join-Path $venv "Scripts\python.exe"
$vendor = Join-Path $RepoRoot "vendor"
$kronosDir = Join-Path $vendor "Kronos"
$forward = Join-Path $RepoRoot "scripts\kronos_forward.py"

if (-not (Test-Path $botPy)) { throw "No encuentro el python del bot en $botPy" }
New-Item -ItemType Directory -Force $vendor | Out-Null

if (-not (Test-Path $py)) {
    Write-Host "Creando entorno aparte en $venv ..."
    & $botPy -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "No pude crear el venv" }
}

Write-Host "Instalando PyTorch (CPU) y dependencias de Kronos ..."
& $py -m pip install --upgrade pip --quiet
& $py -m pip install torch --index-url https://download.pytorch.org/whl/cpu --quiet
if ($LASTEXITCODE -ne 0) { throw "Fallo la instalacion de torch" }
& $py -m pip install "einops==0.8.1" "huggingface_hub==0.33.1" "safetensors==0.6.2" "tqdm==4.67.1" "pandas==2.2.2" numpy MetaTrader5 --quiet
if ($LASTEXITCODE -ne 0) { throw "Fallo la instalacion de dependencias" }

if (-not (Test-Path (Join-Path $kronosDir ".git"))) {
    Write-Host "Clonando Kronos (MIT) en $kronosDir ..."
    git clone --quiet https://github.com/shiyu-coder/Kronos $kronosDir
    if ($LASTEXITCODE -ne 0) { throw "Fallo el git clone de Kronos" }
}
if ($KronosCommit -eq "") {
    # el commit fijado en el pre-registro (scripts/kronos_forward.py: KRONOS_COMMIT)
    $KronosCommit = (& $py -c "import ast,sys;src=open(sys.argv[1],encoding='utf-8').read();print([n.value.value for n in ast.parse(src).body if isinstance(n,ast.Assign) and getattr(n.targets[0],'id','')=='KRONOS_COMMIT'][0])" $forward).Trim()
}
if ($KronosCommit -and $KronosCommit -ne "PENDIENTE") {
    git -C $kronosDir fetch --quiet origin
    git -C $kronosDir checkout --quiet $KronosCommit
    if ($LASTEXITCODE -ne 0) { throw "No pude pasar Kronos al commit $KronosCommit" }
}
Write-Host ("Kronos en el commit: " + (git -C $kronosDir rev-parse HEAD))

if (-not $SkipModels) {
    Write-Host "Bajando los pesos del modelo (revisiones fijadas) ..."
    & $py $forward --download-models --root $RepoRoot
    if ($LASTEXITCODE -ne 0) { throw "Fallo la descarga de los modelos" }
}
Write-Host ""
Write-Host "Listo. Para iniciar el registro de pronosticos: .\start_kronos.ps1"
