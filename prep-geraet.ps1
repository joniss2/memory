# Liest Modell, Build, Android-Stand und CSC vom angeschlossenen Handy.
# Schreibt nur diese Felder nach geraet.txt. Seriennummer und IMEI bleiben draussen.
# Danach in Bifrost: Modell SM-A146P, Region = die CSC aus der Datei, Zielordner firmware\

$ErrorActionPreference = "Stop"

function Find-Adb {
    $scrcpy = Get-Command scrcpy -ErrorAction SilentlyContinue
    if ($scrcpy) {
        $beside = Join-Path (Split-Path -Parent $scrcpy.Source) "adb.exe"
        if (Test-Path -LiteralPath $beside) {
            return $beside
        }
    }

    $winget = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    $found = Get-ChildItem -Path $winget -Recurse -Filter adb.exe -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($found) {
        return $found.FullName
    }

    $cmd = Get-Command adb -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    throw "adb nicht gefunden. scrcpy installieren: winget install --id Genymobile.scrcpy -e"
}

function Read-Prop {
    param(
        [string]$Adb,
        [string]$Serial,
        [string]$Name
    )
    $value = (& $Adb -s $Serial shell getprop $Name 2>$null)
    if ($null -eq $value) {
        return ""
    }
    return (($value | Out-String).Trim())
}

$adb = Find-Adb
& $adb start-server | Out-Null
$lines = & $adb devices
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

if ($unauthorized.Count -gt 0 -and $ready.Count -eq 0) {
    Write-Host "Das Handy wartet auf die Freigabe."
    Write-Host "Am Display tippen: Immer von diesem Computer zulassen."
    exit 1
}

if ($ready.Count -eq 0) {
    Write-Host "Kein Handy im USB-Debugging."
    Write-Host "Entwickleroptionen, USB-Debugging an, Dateiübertragung, dann dieses Skript noch einmal."
    Write-Host "Im Download-Modus gibt es kein USB-Debugging. Dort die CSC nicht raten."
    exit 1
}

if ($ready.Count -gt 1) {
    throw "Mehr als ein Gerät hängt an adb. Nur das A14 angeschlossen lassen."
}

$serial = $ready[0]
$fields = [ordered]@{
    Modell   = Read-Prop -Adb $adb -Serial $serial -Name "ro.product.model"
    Build    = Read-Prop -Adb $adb -Serial $serial -Name "ro.build.display.id"
    Android  = Read-Prop -Adb $adb -Serial $serial -Name "ro.build.version.release"
    CSC      = Read-Prop -Adb $adb -Serial $serial -Name "ro.csc.sales_code"
    Hardware = Read-Prop -Adb $adb -Serial $serial -Name "ro.hardware"
}

if ([string]::IsNullOrWhiteSpace($fields.CSC)) {
    $fields.CSC = Read-Prop -Adb $adb -Serial $serial -Name "ril.official_cscver"
}

if ([string]::IsNullOrWhiteSpace($fields.Build)) {
    $fields.Build = Read-Prop -Adb $adb -Serial $serial -Name "ro.build.version.incremental"
}

$out = Join-Path $PSScriptRoot "geraet.txt"
$linesOut = foreach ($key in $fields.Keys) {
    "{0}={1}" -f $key, $fields[$key]
}
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllLines($out, $linesOut, $utf8)

Write-Host "Geschrieben: $out"
foreach ($row in $linesOut) {
    Write-Host $row
}

if ($fields.Modell -ne "SM-A146P") {
    Write-Host "Modell ist nicht SM-A146P. Diese Firmware nicht fuer das Video laden."
    exit 2
}

if ([string]::IsNullOrWhiteSpace($fields.CSC) -or [string]::IsNullOrWhiteSpace($fields.Build)) {
    Write-Host "CSC oder Build leer. In den Einstellungen unter Dienstanbieter-SW-Version nachsehen."
    exit 3
}

Write-Host "Bifrost: Modell SM-A146P, Region $($fields.CSC). Zielordner: $(Join-Path $PSScriptRoot 'firmware')"
Write-Host "Die Build auf dem PC muss $($fields.Build) sein oder neuer. Kein Downgrade."
exit 0
