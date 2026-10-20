[CmdletBinding()]
param(
    [switch]$PrepararSomente,
    [switch]$ReusarInstalacao,
    [ValidateRange(1024,65535)][int]$WebUIPort = 3000,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]*$')][string]$WebUIContainer = '',
    [ValidateRange(180,1800)][int]$Timeout = 1200
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location -LiteralPath $PSScriptRoot
function New-StackSecret([int]$Bytes = 32) {
    $buffer = New-Object byte[] $Bytes
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($buffer)).Replace('-', '').ToLowerInvariant()
}
function Invoke-StackDocker([string[]]$Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker falhou (codigo $LASTEXITCODE). Confira a mensagem acima." }
}
function Read-StackEnv([string]$Name) {
    $line = Get-Content -LiteralPath '.env.openwebui' | Where-Object { $_.StartsWith($Name + '=') } | Select-Object -First 1
    if (-not $line) { throw "Campo ausente em .env.openwebui: $Name" }
    return $line.Substring($Name.Length + 1).Trim()
}
# Both env files contain fresh local credentials; no NVIDIA credential is bundled.
& (Join-Path $PSScriptRoot 'instalar-hermes.ps1') -PrepararSomente
if (-not (Test-Path -LiteralPath '.env.openwebui')) {
    $container = if ($WebUIContainer) { $WebUIContainer } else { 'hermes-open-webui' }
    [IO.File]::WriteAllLines((Join-Path $PSScriptRoot '.env.openwebui'), @(
        "OPEN_WEBUI_CONTAINER=$container", "OPEN_WEBUI_PORT=$WebUIPort", 'OPEN_WEBUI_BIND_ADDRESS=0.0.0.0',
        'WEBUI_ADMIN_EMAIL=admin@hermes.local',
        ('WEBUI_ADMIN_PASSWORD=' + (New-StackSecret 16)),
        ('WEBUI_SECRET_KEY=' + (New-StackSecret))
    ), (New-Object Text.UTF8Encoding($false)))
    Write-Host 'Credenciais novas do Open WebUI geradas em .env.openwebui.'
} else { Write-Host '.env.openwebui existente preservado.' }
if ($PrepararSomente) { Write-Host 'Preparacao concluida; nenhum container alterado.'; return }
& (Join-Path $PSScriptRoot 'instalar-hermes.ps1') -InstalarDocker -ReusarInstalacao:$ReusarInstalacao -Timeout $Timeout
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host 'Conclua a instalacao do Docker Desktop e execute INSTALAR.cmd novamente.'
    return
}
$ErrorActionPreference = 'Continue'
& docker info *> $null
$engineExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($engineExit -ne 0) { throw 'Conclua a configuracao do Docker Desktop e execute INSTALAR.cmd novamente.' }
$hermesRunning = & docker ps --filter 'name=^/hermes-agent-v2026-9-11$' --filter 'status=running' --format '{{.ID}}'
if ($LASTEXITCODE -ne 0 -or -not $hermesRunning) { throw 'Docker foi preparado, mas Hermes ainda nao iniciou. Conclua Docker Desktop e execute INSTALAR.cmd novamente.' }
$target = if ($WebUIContainer) { $WebUIContainer } else { Read-StackEnv 'OPEN_WEBUI_CONTAINER' }
if ($target -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]*$') { throw 'Nome de container invalido em .env.openwebui.' }
$existing = & docker ps -a --filter "name=^/$target$" --format '{{.ID}}'
if ($LASTEXITCODE -ne 0) { throw 'Falha ao verificar Open WebUI.' }
if (-not $existing -and -not $WebUIContainer) {
    $old = & docker ps -a --filter 'name=^/open-webui$' --format '{{.ID}}'
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao verificar Open WebUI existente.' }
    if ($old) { $target = 'open-webui'; $existing = $old }
}
if ($existing) {
    Write-Host "Integrando Open WebUI existente: $target. Dados e credenciais existentes serao preservados."
    Invoke-StackDocker -Arguments @('start', $target)
    # Poll from inside the container; no user password is required.
    Invoke-StackDocker -Arguments @('cp', (Join-Path $PSScriptRoot 'verify-openwebui.py'), "${target}:/tmp/verify-openwebui.py")
    Invoke-StackDocker -Arguments @('exec', $target, 'python', '/tmp/verify-openwebui.py')
} else {
    if ($target -ne (Read-StackEnv 'OPEN_WEBUI_CONTAINER')) { throw 'Defina o mesmo nome de container em .env.openwebui.' }
    Invoke-StackDocker -Arguments @('compose','--project-name','hermes-openwebui','--env-file','.env.openwebui','-f','docker-compose.openwebui.yml','up','-d','--wait','--wait-timeout',"$Timeout")
}
& (Join-Path $PSScriptRoot 'integrar-openwebui.ps1') -Container $target
# Use the actual published port when reusing an existing Open WebUI.
$published = & docker port $target '8080/tcp'
if ($LASTEXITCODE -ne 0) { throw 'Falha ao verificar a porta publicada do Open WebUI.' }
$publishedPorts = @($published | ForEach-Object { if ($_ -match ':(\d+)$') { [int]$Matches[1] } } | Sort-Object -Unique)
if ($publishedPorts.Count -ne 1) { throw 'Open WebUI precisa publicar uma porta TCP para acesso LAN. Confira a configuracao do container.' }
& (Join-Path $PSScriptRoot 'liberar-lan.ps1') -WebUIPort $publishedPorts[0]
Write-Host 'Instalacao completa: Hermes + Open WebUI integrados.' -ForegroundColor Green
Write-Host ('Open WebUI novo: http://localhost:' + (Read-StackEnv 'OPEN_WEBUI_PORT') + '/ (tambem pelo IP LAN).')
Write-Host 'Em instalacao nova, login/senha: WEBUI_ADMIN_EMAIL e WEBUI_ADMIN_PASSWORD em .env.openwebui.'
Write-Host 'Open WebUI reutilizado: mantenha seu endereco e login atuais.'
Write-Host 'Vincule somente a chave NVIDIA em http://localhost:9120/env.'
Write-Host 'Cadastre funcionarios e associe-os aos grupos em Administracao > Grupos.'
$lanAddresses = @(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway } | ForEach-Object { $_.IPv4Address.IPAddress })
foreach ($lanAddress in $lanAddresses) {
    Write-Host "Open WebUI na LAN: http://${lanAddress}:$($publishedPorts[0])/"
    Write-Host "Hermes na LAN: http://${lanAddress}:9120/"
}
