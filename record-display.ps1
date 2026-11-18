# Spiegelt das Handy über USB und nimmt das Display ohne Ton auf.
# Stoppen mit Strg+C, damit die mp4 sauber abgeschlossen wird.
# Vor Odin dieses Fenster schließen. Download-Modus hat kein USB-Debugging.

param(
    [string]$Kapitel,
    [switch]$NurAnzeigen
)

$ErrorActionPreference = "Stop"

function Find-Scrcpy {
    $cmd = Get-Command scrcpy -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $winget = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    $found = Get-ChildItem -Path $winget -Recurse -Filter scrcpy.exe -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($found) {
        return $found.FullName
    }

    throw "scrcpy nicht gefunden. Installation: winget install --id Genymobile.scrcpy -e"
}

function Get-AdbDevices {
    param([string]$Adb)
    $lines = & $Adb devices
    $ready = @()
    $unauthorized = @()
    foreach ($line in $lines) {
        if ($line -match "^(\S+)\s+device$") {
            if ($Matches[1] -notlike "emulator-*") {
                $ready += $Matches[1]
            }
        } elseif ($line -match "^(\S+)\s+unauthorized$") {
            $unauthorized += $Matches[1]
        }
    }
    return [pscustomobject]@{
        Ready        = $ready
        Unauthorized = $unauthorized
    }
}

$scrcpy = Find-Scrcpy
$scrcpyDir = Split-Path -Parent $scrcpy
$env:ADB = Join-Path $scrcpyDir "adb.exe"
if (-not (Test-Path -LiteralPath $env:ADB)) {
    throw "adb liegt nicht neben scrcpy: $env:ADB"
}

& $env:ADB start-server | Out-Null
$attached = Get-AdbDevices -Adb $env:ADB

if ($attached.Unauthorized.Count -gt 0 -and $attached.Ready.Count -eq 0) {
    Write-Host "Das Handy ist am USB, wartet aber auf die Freigabe."
    Write-Host "Am Handy tippen: Immer von diesem Computer zulassen."
    exit 1
}

if ($attached.Ready.Count -eq 0) {
    Write-Host "Kein Handy im USB-Debugging."
    Write-Host "Am Handy: Entwickleroptionen, USB-Debugging an, Kabel einstecken, Dateiübertragung wählen."
    Write-Host "Den Fingerabdruck-Dialog mit Immer von diesem Computer zulassen bestätigen."
    Write-Host "Nach einem Bootloader-Wipe denselben Dialog erneut bestätigen."
    exit 1
}

if ($attached.Ready.Count -gt 1) {
    throw "Mehr als ein Gerät hängt an adb. Nur das A14 angeschlossen lassen."
}

$serial = $attached.Ready[0]
$common = @(
    "--serial=$serial",
    "--no-audio",
    "--video-codec=h264",
    "--video-bit-rate=16M",
    "--max-fps=60",
    "--stay-awake"
)

if ($NurAnzeigen) {
    Write-Host "Kurztest ohne Datei. Fenster schließen, wenn das Bild steht."
    & $scrcpy @common
    exit $LASTEXITCODE
}

if ([string]::IsNullOrWhiteSpace($Kapitel)) {
    throw "Kapitel angeben, zum Beispiel: .\record-display.ps1 -Kapitel modell"
}

$safe = ($Kapitel.Trim() -replace "[^A-Za-z0-9_-]", "-").Trim("-")
if ([string]::IsNullOrWhiteSpace($safe)) {
    throw "Kapitelname enthält keine verwendbaren Zeichen."
}

$outDir = Join-Path $PSScriptRoot "aufnahmen"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd-HHmm"
$file = Join-Path $outDir "$safe-$stamp.mp4"

Write-Host "Aufnahme ohne Ton: $file"
Write-Host "Stoppen mit Strg+C in diesem Fenster."
& $scrcpy @common --record=$file
exit $LASTEXITCODE
