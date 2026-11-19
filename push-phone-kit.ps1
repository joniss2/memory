# Kopiert Magisk und die Termux-/Dashboard-Dateien aufs Handy.
# Preferiert adb. Ohne adb: CrossDevice-Pfad Documents\A14 (Sushi.test).

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$files = @(
    @{ Src = "tools\Magisk-v31.1.apk"; Name = "Magisk-v31.1.apk" },
    @{ Src = "phone\index.html"; Name = "index.html" },
    @{ Src = "phone\start.sh"; Name = "start.sh" },
    @{ Src = "phone\debian-setup.sh"; Name = "debian-setup.sh" }
)

function Find-Adb {
    $scrcpy = Get-Command scrcpy -ErrorAction SilentlyContinue
    if ($scrcpy) {
        $beside = Join-Path (Split-Path -Parent $scrcpy.Source) "adb.exe"
        if (Test-Path -LiteralPath $beside) { return $beside }
    }
    $cmd = Get-Command adb -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$adb = Find-Adb
$serial = $null
if ($adb) {
    & $adb start-server | Out-Null
    foreach ($line in (& $adb devices)) {
        if ($line -match "^(\S+)\s+device$" -and $Matches[1] -notlike "emulator-*") {
            $serial = $Matches[1]
            break
        }
    }
}

if ($serial) {
    $remote = "/sdcard/Documents/A14"
    & $adb -s $serial shell "mkdir -p $remote" | Out-Null
    foreach ($f in $files) {
        $src = Join-Path $root $f.Src
        if (-not (Test-Path -LiteralPath $src)) { throw "Fehlt: $src" }
        & $adb -s $serial push $src "$remote/$($f.Name)"
    }
    $hint = Join-Path $env:TEMP "a14-usb-debugging.txt"
    @"
A14 Drehkit — USB-Debugging ist an. Als Nächstes am PC:
  .\warte-auf-handy.ps1
Oder wenn geraet.txt schon da ist: .\open-bifrost.ps1
"@ | Set-Content -LiteralPath $hint -Encoding UTF8
    & $adb -s $serial push $hint "$remote/USB-DEBUGGING.txt" | Out-Null
    Write-Host "Per adb nach $remote kopiert."
    exit 0
}

$cross = "C:\Users\jonas\CrossDevice\Sushi.test\storage\Documents\A14"
if (-not (Test-Path -LiteralPath $cross)) {
    Write-Host "Kein adb-Gerät und kein CrossDevice-Ordner unter:"
    Write-Host "  $cross"
    Write-Host "Handy mit USB-Debugging anschließen oder Smartphone-Link verbinden."
    exit 1
}

New-Item -ItemType Directory -Force -Path $cross | Out-Null
foreach ($f in $files) {
    $src = Join-Path $root $f.Src
    if (-not (Test-Path -LiteralPath $src)) { throw "Fehlt: $src" }
    Copy-Item -Force -LiteralPath $src -Destination (Join-Path $cross $f.Name)
}
$hintPath = Join-Path $cross "USB-DEBUGGING.txt"
try {
    @"
A14 Drehkit — als Nächstes am Handy

1. Entwickleroptionen (siebenmal auf die Build-Nummer)
2. USB-Debugging an
3. Kabel, Dateiübertragung, Immer von diesem Computer zulassen

Dann am PC:
  cd C:\Users\jonas\Projects\a14-server-video
  .\warte-auf-handy.ps1

CSC nicht raten. Firmware erst nach geraet.txt laden.
"@ | Set-Content -LiteralPath $hintPath -Encoding UTF8
} catch {
    Write-Host "Hinweisdatei nicht geschrieben (Zugriff verweigert). Kit-Dateien sind trotzdem kopiert."
}

Write-Host "Per CrossDevice nach $cross kopiert (ohne adb)."
Write-Host "Für CSC und Firmware trotzdem USB-Debugging einschalten."
exit 0
