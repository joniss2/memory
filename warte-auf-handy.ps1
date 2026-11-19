# Wartet auf USB-Debugging, schreibt dann geraet.txt und startet Bifrost.
# CSC wird nicht geraten. Ohne SM-A146P plus CSC keine Firmware laden.

param(
    [int]$Sekunden = 300,
    [switch]$OhneBifrost
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$prep = Join-Path $root "prep-geraet.ps1"
$open = Join-Path $root "open-bifrost.ps1"
$verify = Join-Path $root "verify-prep.ps1"

if (-not (Test-Path -LiteralPath $prep)) {
    throw "prep-geraet.ps1 fehlt."
}

Write-Host "Warte bis zu $Sekunden Sekunden auf das A14 im USB-Debugging."
Write-Host "Am Handy: Dateiübertragung, Dialog Immer von diesem Computer zulassen."

$deadline = (Get-Date).AddSeconds($Sekunden)
$exitCode = 1

while ((Get-Date) -lt $deadline) {
    & $prep
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        break
    }
    if ($exitCode -eq 2 -or $exitCode -eq 3) {
        exit $exitCode
    }
    Start-Sleep -Seconds 5
}

if ($exitCode -ne 0) {
    Write-Host "Kein freigegebenes Handy in der Wartezeit."
    exit 1
}

if (-not $OhneBifrost) {
    & $open
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    Write-Host "In Bifrost SM-A146P und die CSC aus geraet.txt wählen. Zielordner: firmware\"
    Write-Host "Danach erneut: .\verify-prep.ps1"
}

& $verify
exit $LASTEXITCODE
