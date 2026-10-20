[CmdletBinding()]
param(
    [switch]$InstalarDocker,
    [switch]$PrepararSomente,
    [switch]$ReusarInstalacao,
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$UsuarioDashboard = 'admin',
    [ValidateRange(60,1800)][int]$Timeout = 180
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location -LiteralPath $PSScriptRoot
$script:HermesProject = $null

function New-HermesSecret([int]$Bytes = 32) {
    $buffer = New-Object byte[] $Bytes
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($buffer)).Replace('-', '').ToLowerInvariant()
}
function Invoke-HermesDocker([string[]]$DockerArguments) {
    if ($script:HermesProject -and $DockerArguments[0] -eq 'compose') {
        $DockerArguments = @('compose','--project-name',$script:HermesProject) + $DockerArguments[1..($DockerArguments.Count - 1)]
    }
    & docker @DockerArguments
    if ($LASTEXITCODE -ne 0) { throw "Docker falhou (codigo $LASTEXITCODE). Confira a mensagem acima." }
}

$required = @('Dockerfile','docker-compose.yml','browser-stack.sh','browser-s6-run',
    'configure-browser.py','configure-browser-init','verify-health.py','.dockerignore',
    'browser-pool.py','browser-session.sh','browser-pool-client.py','patch-browser-pool.py','browser-pool-auth.py','browser-pool.html',
    'hermes-exports.py','hermes-workspace.py','hermes-specialists.json','patch-specialists.py')
foreach ($file in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $file))) {
        throw "Arquivo ausente: $file. Extraia TODO o ZIP antes de executar."
    }
}
$envPath = Join-Path $PSScriptRoot '.env'
$envExisted = Test-Path -LiteralPath $envPath
if (-not (Test-Path -LiteralPath $envPath)) {
    $values = @(
        "HERMES_DASHBOARD_BASIC_AUTH_USERNAME=$UsuarioDashboard",
        ('HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=' + (New-HermesSecret 16)),
        ('HERMES_DASHBOARD_BASIC_AUTH_SECRET=' + (New-HermesSecret)),
        ('API_SERVER_KEY=' + (New-HermesSecret)),
        'HERMES_BIND_ADDRESS=0.0.0.0',
        'NVIDIA_API_KEY='
    )
    [IO.File]::WriteAllLines($envPath, $values, (New-Object Text.UTF8Encoding($false)))
    Write-Host 'Credenciais locais novas geradas no .env. Chave NVIDIA deixada vazia.'
} else {
    Write-Host '.env existente preservado.'
}
if ($PrepararSomente) {
    Write-Host 'Preparacao concluida. Nenhum container foi alterado.'
    return
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    if (-not $InstalarDocker) {
        throw 'Instale e abra Docker Desktop (containers Linux), ou execute com -InstalarDocker.'
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'Winget indisponivel. Instale Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/'
    }
    & winget install --id Docker.DockerDesktop --exact --source winget
    if ($LASTEXITCODE -ne 0) { throw 'Instalacao do Docker nao concluida. Execute o instalador novamente depois de corrigir a falha.' }
    Write-Host 'Docker instalado. Abra Docker Desktop, configure WSL 2 e reinicie o PC se solicitado.'
    Write-Host 'Depois execute INSTALAR.cmd novamente. As credenciais geradas serao preservadas.'
    return
}
# Windows PowerShell 5.1 turns native stderr into errors under Stop.
$ErrorActionPreference = 'Continue'
$engine = & docker info --format '{{.OSType}}' 2>$null
$engineExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($engineExit -ne 0) { throw 'Abra Docker Desktop e aguarde o engine iniciar. Depois execute este script novamente.' }
if (($engine -join '').Trim() -ne 'linux') { throw 'Selecione Linux containers no Docker Desktop.' }
Invoke-HermesDocker -DockerArguments @('compose','version')
Invoke-HermesDocker -DockerArguments @('compose','config','--quiet')

# Refuse to replace a container belonging to another installation folder.
$configJson = & docker compose config --format json
if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel ler o Compose.' }
$config = ($configJson -join "`n") | ConvertFrom-Json
$containerName = $config.services.hermes.container_name
$existing = & docker ps -a --filter "name=^/$containerName$" --format '{{.ID}}'
if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel verificar containers existentes.' }
if ($existing) {
    # Windows PowerShell 5.1 strips embedded quotes in native arguments.
    # Read labels as JSON instead of using a Go template with a quoted key.
    $labelsJson = & docker inspect $containerName --format '{{json .Config.Labels}}'
    if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel identificar a instalacao existente.' }
    $labels = ($labelsJson -join "`n") | ConvertFrom-Json
    $ownerProperty = $labels.PSObject.Properties['com.docker.compose.project.working_dir']
    if ($null -eq $ownerProperty -or -not $ownerProperty.Value) {
        throw "O container $containerName nao tem identificacao de pasta do Compose. Verifique sua origem antes de continuar."
    }
    $owner = [string]$ownerProperty.Value
    $ownerNormalized = $owner.Trim().Replace('/','\').TrimEnd('\')
    $currentNormalized = $PSScriptRoot.Replace('/','\').TrimEnd('\')
    if ($ownerNormalized -ine $currentNormalized) {
        Write-Host "Pasta registrada no container: $owner"
        Write-Host "Pasta atual do instalador: $PSScriptRoot"
        if (-not $ReusarInstalacao) {
            throw 'Pasta diferente. Para reutilizar este Hermes com os volumes existentes, execute instalar-hermes.ps1 -ReusarInstalacao na pasta atual, mantendo o .env original.'
        }
        if (-not $envExisted) { throw 'Para reutilizar a instalacao, copie primeiro o .env original para esta pasta.' }
        $projectProperty = $labels.PSObject.Properties['com.docker.compose.project']
        $serviceProperty = $labels.PSObject.Properties['com.docker.compose.service']
        if ($null -eq $projectProperty -or $null -eq $serviceProperty -or $serviceProperty.Value -ne 'hermes') {
            throw 'O container existente nao foi identificado como servico Hermes do Compose.'
        }
        $oldProject = [string]$projectProperty.Value
        if ($oldProject -notmatch '^[a-z0-9][a-z0-9_-]*$') { throw 'Nome de projeto Docker invalido.' }
        $mountsJson = & docker inspect $containerName --format '{{json .Mounts}}'
        if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel verificar os volumes existentes.' }
        $mounts = ($mountsJson -join "`n") | ConvertFrom-Json
        foreach ($volume in @(@{Destination='/opt/data';Name="${oldProject}_hermes_data"},@{Destination='/browser-data';Name="${oldProject}_hermes_browser_data"})) {
            $found = @($mounts | Where-Object { $_.Destination -eq $volume.Destination -and $_.Type -eq 'volume' -and $_.Name -eq $volume.Name })
            if ($found.Count -ne 1) { throw "Volume existente fora do padrao esperado: $($volume.Destination). Reutilizacao interrompida para preservar seus dados." }
        }
        $script:HermesProject = $oldProject
        Write-Host "Reutilizando projeto $oldProject e seus volumes existentes."
    }
    # Keep the recorded project on every later run, including after a folder move.
    if (-not $script:HermesProject) {
        $projectProperty = $labels.PSObject.Properties['com.docker.compose.project']
        $serviceProperty = $labels.PSObject.Properties['com.docker.compose.service']
        if ($null -eq $projectProperty -or $null -eq $serviceProperty -or $serviceProperty.Value -ne 'hermes') {
            throw 'O container existente nao foi identificado como servico Hermes do Compose.'
        }
        $recordedProject = [string]$projectProperty.Value
        if ($recordedProject -notmatch '^[a-z0-9][a-z0-9_-]*$') { throw 'Nome de projeto Docker invalido.' }
        $script:HermesProject = $recordedProject
    }
}

Write-Host 'Construindo e iniciando Hermes + dashboard + Chromium. O primeiro download pode demorar.'
Invoke-HermesDocker -DockerArguments @('compose','up','-d','--build','--wait','--wait-timeout',"$Timeout")
Invoke-HermesDocker -DockerArguments @('compose','exec','-T','hermes','python','/usr/local/lib/verify-health.py')
Invoke-HermesDocker -DockerArguments @('compose','ps')
Write-Host ''
Write-Host 'Instalacao concluida.' -ForegroundColor Green
Write-Host 'Dashboard: http://127.0.0.1:9120/'
Write-Host 'Chromium:  http://127.0.0.1:6080/'
Write-Host 'Usuario/senha do dashboard: consulte o .env nesta pasta.'
Write-Host 'Vincule sua NVIDIA_API_KEY em http://127.0.0.1:9120/env'
Write-Host 'Modelo: nvidia/nemotron-3-super-120b-a12b'
Write-Host 'Pesquisas e navegacao: Chromium visivel, configurado automaticamente.'
