$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "Compose ou .env invalido." }
docker compose up -d --build --wait --wait-timeout 180
if ($LASTEXITCODE -ne 0) { throw "Falha ao iniciar. Consulte: docker compose logs --tail=100 hermes" }
docker compose ps
Write-Host "Dashboard local: http://127.0.0.1:9120/"
Write-Host "Chromium local:  http://127.0.0.1:6080/"
$lanIps = @()
try {
    $lanIps = @(Get-WmiObject Win32_NetworkAdapterConfiguration -ErrorAction Stop |
        Where-Object { $_.IPEnabled } |
        ForEach-Object { $_.IPAddress } |
        Where-Object { $_ -match '^\d{1,3}(\.\d{1,3}){3}$' -and $_ -notmatch '^127\.' -and $_ -notmatch '^169\.254\.' } |
        Select-Object -Unique)
} catch { }
foreach ($lanIp in $lanIps) {
    Write-Host ("Dashboard LAN: http://{0}:9120/" -f $lanIp) -ForegroundColor Cyan
    Write-Host ("Chromium LAN:  http://{0}:6080/" -f $lanIp) -ForegroundColor Cyan
    Write-Host ("API LAN:       http://{0}:8643/" -f $lanIp) -ForegroundColor Cyan
}
Write-Host 'Se o acesso LAN for bloqueado, libere TCP 9120, 6080 e 8643 no firewall da rede privada.' -ForegroundColor Yellow
