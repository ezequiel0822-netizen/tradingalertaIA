# start_bot.ps1 - Arranque del bot con contrasena (opt-in).
#
# USO:
#   1. Configurar la contrasena (una sola vez):
#        .\start_bot.ps1 -SetPassword
#      Te pide la contrasena 2 veces y te muestra la linea STARTUP_PASSWORD_SHA256=...
#      para pegar en tu .env (no toca el .env automaticamente, la pegas vos).
#   2. Arrancar el bot:
#        .\start_bot.ps1
#      Pide la contrasena (3 intentos) y si es correcta lanza main.py.
#
# HONESTIDAD SOBRE LO QUE PROTEGE: esto frena que alguien con acceso casual a tu
# sesion arranque el bot. NO protege los archivos: quien pueda leer tu disco puede
# leer el .env (tokens/credenciales) o lanzar python main.py directo. La proteccion
# real de los secretos es la contrasena de tu cuenta de Windows + BitLocker.
#
# Si STARTUP_PASSWORD_SHA256 no esta en el .env, arranca directo (comportamiento
# identico a antes; la contrasena es opt-in).
#
# NOTA: archivo en ASCII puro a proposito (PowerShell 5.1 lee .ps1 sin BOM como
# ANSI y los acentos/UTF-8 rompen el parseo).

param(
    [switch]$SetPassword
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$envFile = Join-Path $root ".env"

function Get-Sha256Hex([string]$text) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($text)
    $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    return ([System.BitConverter]::ToString($hash)).Replace("-", "").ToLower()
}

function Read-PlainPassword([string]$prompt) {
    $sec = Read-Host $prompt -AsSecureString
    $ptr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try {
        return [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($ptr)
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

if ($SetPassword) {
    $p1 = Read-PlainPassword "Nueva contrasena de arranque"
    $p2 = Read-PlainPassword "Repetila"
    if ($p1 -ne $p2) { Write-Host "No coinciden. Nada cambiado."; exit 1 }
    if ($p1.Length -lt 6) { Write-Host "Muy corta (minimo 6). Nada cambiado."; exit 1 }
    $hash = Get-Sha256Hex $p1
    Write-Host ""
    Write-Host "Pega esta linea en tu .env (reemplaza la anterior si ya existe):"
    Write-Host ""
    Write-Host "STARTUP_PASSWORD_SHA256=$hash"
    Write-Host ""
    Write-Host "Despues arranca siempre con: .\start_bot.ps1"
    exit 0
}

# Leer el hash esperado del .env (solo esa clave; no se imprime nada del .env).
$expected = $null
if (Test-Path $envFile) {
    $line = Select-String -Path $envFile -Pattern "^STARTUP_PASSWORD_SHA256=([0-9a-fA-F]{64})\s*$" | Select-Object -First 1
    if ($line) { $expected = $line.Matches[0].Groups[1].Value.ToLower() }
}

if ($expected) {
    $ok = $false
    for ($i = 1; $i -le 3; $i++) {
        $given = Read-PlainPassword "Contrasena para iniciar Trading Alert AI"
        if ((Get-Sha256Hex $given) -eq $expected) { $ok = $true; break }
        Write-Host "Incorrecta ($i/3)."
    }
    if (-not $ok) { Write-Host "Demasiados intentos. No se inicia."; exit 1 }
    Write-Host "OK. Iniciando..."
} else {
    Write-Host "(Sin STARTUP_PASSWORD_SHA256 en .env - arranque directo. Para activar: .\start_bot.ps1 -SetPassword)"
}

& (Join-Path $root ".venv\Scripts\python.exe") (Join-Path $root "main.py")
