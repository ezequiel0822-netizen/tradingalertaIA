# console_quickedit.ps1 - apaga la "Edicion rapida" (QuickEdit) de ESTA ventana.
#
# Por que: si alguien hace clic en la ventana y queda texto seleccionado, Windows PAUSA
# la salida de la consola y el proceso se CONGELA en el proximo print/log hasta que se
# suelte la seleccion (Enter/Esc). Paso el 2026-10-10: el bot quedo ~30 h colgado en
# logging.emit justo despues de reiniciarlo (py-spy). Con esto, seleccionar texto ya no
# congela nada. Solo afecta a esta ventana; no toca la configuracion de Windows.
#
# Uso: . (Join-Path $PSScriptRoot "scripts\console_quickedit.ps1"); Disable-QuickEdit
# NOTA: archivo en ASCII puro a proposito (PowerShell 5.1 lee .ps1 sin BOM como ANSI).

function Disable-QuickEdit {
    try {
        $sig = @"
using System;
using System.Runtime.InteropServices;
public static class TaiConsoleQuickEdit {
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr GetStdHandle(int nStdHandle);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool GetConsoleMode(IntPtr h, out uint mode);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool SetConsoleMode(IntPtr h, uint mode);
    public static bool Disable() {
        IntPtr h = GetStdHandle(-10);
        uint mode;
        if (!GetConsoleMode(h, out mode)) return false;
        mode &= ~0x0040u;
        mode |= 0x0080u;
        return SetConsoleMode(h, mode);
    }
}
"@
        if (-not ("TaiConsoleQuickEdit" -as [type])) { Add-Type -TypeDefinition $sig -Language CSharp }
        if ([TaiConsoleQuickEdit]::Disable()) {
            Write-Host "(Edicion rapida desactivada en esta ventana: seleccionar texto ya no congela el proceso)"
        } else {
            Write-Host "(No pude desactivar la Edicion rapida: NO selecciones texto en esta ventana)"
        }
    } catch {
        Write-Host "(No pude desactivar la Edicion rapida: NO selecciones texto en esta ventana)"
    }
}
