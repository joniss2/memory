# Liest geraet.txt und startet Bifrost. Firmware landet in firmware\.
# Ohne SM-A146P plus CSC aus prep-geraet.ps1 nichts laden.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$geraet = Join-Path $root "geraet.txt"
$firmware = Join-Path $root "firmware"
$bifrost = Join-Path $root "tools\bifrost\bin\Bifrost.exe"

if (-not (Test-Path -LiteralPath $geraet)) {
    Write-Host "geraet.txt fehlt. Handy im USB-Debugging anschließen und .\prep-geraet.ps1 ausführen."
    exit 1
}

$map = @{}
Get-Content -LiteralPath $geraet -Encoding UTF8 | ForEach-Object {
    if ($_ -match "^([^=]+)=(.*)$") {
        $map[$Matches[1]] = $Matches[2]
    }
}

foreach ($key in @("Modell", "Build", "CSC")) {
    if (-not $map.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($map[$key])) {
        Write-Host "geraet.txt unvollständig ($key). .\prep-geraet.ps1 erneut ausführen."
        exit 1
    }
}

if ($map.Modell -ne "SM-A146P") {
    Write-Host "Modell ist $($map.Modell), nicht SM-A146P. Keine Firmware für das Video laden."
    exit 2
}

New-Item -ItemType Directory -Force -Path $firmware | Out-Null

if (-not (Test-Path -LiteralPath $bifrost)) {
    Write-Host "Bifrost fehlt unter tools\bifrost\bin\Bifrost.exe"
    exit 1
}

Write-Host "Bifrost:"
Write-Host "  Modell  SM-A146P"
Write-Host "  Region  $($map.CSC)"
Write-Host "  Build   $($map.Build) oder neuer (kein Downgrade)"
Write-Host "  Ziel    $firmware"
Write-Host "Danach müssen BL, AP, CP und CSC (nicht HOME_CSC) im Ordner liegen."

Start-Process -FilePath $bifrost
exit 0
