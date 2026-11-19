# Prüft die PC-Seite vor dem Dreh. Schreibt keine Firmware und startet kein Odin.

$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
$ok = $true

function Show-Check {
    param([bool]$Pass, [string]$Text)
    if ($Pass) {
        Write-Host "[ok] $Text"
    } else {
        Write-Host "[--] $Text"
        $script:ok = $false
    }
}

$odin = Join-Path $root "tools\odin-patched\extracted\Odin3 v3.14.1_3B_PatcheD.exe"
$ini = Join-Path $root "tools\odin-patched\extracted\Odin3.ini"
$magisk = Join-Path $root "tools\Magisk-v31.1.apk"
$bifrost = Join-Path $root "tools\bifrost\bin\Bifrost.exe"
$obs = Join-Path $root "obs\usb-handy-spiegel.py"
$expectedHash = "89CEFAC0A318AFA39FB3880C45C87B036C05BC1EBF02A7A715B7F8D7C26AC6E7"

Show-Check (Test-Path -LiteralPath $odin) "Odin 3.14.1 PatcheD unter tools\odin-patched\extracted\"
if (Test-Path -LiteralPath $ini) {
    $auto = Select-String -LiteralPath $ini -Pattern "^\s*AutoReboot\s*=\s*0\s*$" -Quiet
    Show-Check $auto "Odin3.ini: AutoReboot=0"
} else {
    Show-Check $false "Odin3.ini fehlt"
}

Show-Check (Test-Path -LiteralPath $bifrost) "Bifrost 2.1.4"
Show-Check (Test-Path -LiteralPath $obs) "OBS-Skript obs\usb-handy-spiegel.py"

if (Test-Path -LiteralPath $magisk) {
    $hash = (Get-FileHash -LiteralPath $magisk -Algorithm SHA256).Hash
    Show-Check ($hash -eq $expectedHash) "Magisk-v31.1.apk SHA-256 stimmt mit GitHub überein"
} else {
    Show-Check $false "Magisk-v31.1.apk fehlt"
}

$scrcpy = Get-Command scrcpy -ErrorAction SilentlyContinue
Show-Check ($null -ne $scrcpy) "scrcpy im PATH"

$samsung = Get-PnpDevice -ErrorAction SilentlyContinue |
    Where-Object { $_.FriendlyName -like "*SAMSUNG Mobile USB*" -and $_.Status -eq "OK" }
$modemUnknown = Get-PnpDevice -ErrorAction SilentlyContinue |
    Where-Object { $_.FriendlyName -like "SAMSUNG Mobile USB Modem" }
Show-Check ($null -ne $modemUnknown -or $null -ne $samsung) "Samsung-USB-Treiber (ssudadb) vorhanden"

$geraet = Join-Path $root "geraet.txt"
if (Test-Path -LiteralPath $geraet) {
    Write-Host "[ok] geraet.txt vorhanden"
    Get-Content -LiteralPath $geraet -Encoding UTF8 | ForEach-Object { Write-Host "     $_" }
} else {
    Write-Host "[--] geraet.txt fehlt — Handy anschließen und .\prep-geraet.ps1"
    $ok = $false
}

$firmware = Join-Path $root "firmware"
$parts = @{}
if (Test-Path -LiteralPath $firmware) {
    Get-ChildItem -LiteralPath $firmware -File -ErrorAction SilentlyContinue | ForEach-Object {
        $name = $_.Name
        if ($name -like "BL_*") { $parts.BL = $name }
        if ($name -like "AP_*") { $parts.AP = $name }
        if ($name -like "CP_*") { $parts.CP = $name }
        if ($name -like "CSC_*" -and $name -notlike "HOME_CSC_*") { $parts.CSC = $name }
    }
}
foreach ($part in @("BL", "AP", "CP", "CSC")) {
    if ($parts.ContainsKey($part)) {
        Write-Host "[ok] firmware\$($parts[$part])"
    } else {
        Write-Host "[--] firmware\$part fehlt — nach CSC-Ablesung mit .\open-bifrost.ps1 laden"
        $ok = $false
    }
}

if ($ok) {
    Write-Host "Prep vollständig. Unlock, Magisk und Dashboard können gedreht werden."
    exit 0
}

Write-Host "Prep unvollständig. Offene Punkte oben beheben, bevor der Bootloader aufgeht."
exit 1
