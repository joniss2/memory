# Lokale Vorschau der Startseite auf Port 8080.
# Für die Laptop-Szene vor dem echten Handy. Glances (61208) kommt erst vom Gerät.

param(
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"
$html = Join-Path $PSScriptRoot "phone\index.html"
if (-not (Test-Path -LiteralPath $html)) {
    throw "phone\index.html fehlt."
}

$listener = [System.Net.HttpListener]::new()
$prefix = "http://127.0.0.1:$Port/"
$listener.Prefixes.Add($prefix)
try {
    $listener.Start()
} catch {
    throw "Port $Port belegt. Anderen Port wählen: .\serve-dashboard.ps1 -Port 8081"
}

Write-Host "Dashboard: $prefix"
Write-Host "Stoppen mit Strg+C."
Write-Host "Vor der Aufnahme in phone\index.html die Platzhalter-IP durch die Handy-IP ersetzen."

try {
    while ($listener.IsListening) {
        $ctx = $listener.GetContext()
        $path = $ctx.Request.Url.AbsolutePath.TrimEnd("/")
        if ($path -eq "" -or $path -eq "/" -or $path -eq "/index.html") {
            $bytes = [System.IO.File]::ReadAllBytes($html)
            $ctx.Response.StatusCode = 200
            $ctx.Response.ContentType = "text/html; charset=utf-8"
            $ctx.Response.ContentLength64 = $bytes.Length
            $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
        } else {
            $ctx.Response.StatusCode = 404
            $msg = [System.Text.Encoding]::UTF8.GetBytes("not found")
            $ctx.Response.ContentLength64 = $msg.Length
            $ctx.Response.OutputStream.Write($msg, 0, $msg.Length)
        }
        $ctx.Response.OutputStream.Close()
    }
} finally {
    $listener.Stop()
    $listener.Close()
}
