[CmdletBinding()]
param([string]$Container = 'open-webui', [string]$BaseUrl = 'http://host.docker.internal:8643/v1')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$envFile = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path -LiteralPath $envFile)) { throw 'Instale o Hermes primeiro para gerar .env.' }
$keyLine = Get-Content -LiteralPath $envFile | Where-Object { $_ -match '^API_SERVER_KEY=' } | Select-Object -First 1
if (-not $keyLine) { throw 'API_SERVER_KEY ausente no .env.' }
$apiKey = $keyLine.Substring('API_SERVER_KEY='.Length).Trim().Trim('"',"'")
& docker cp (Join-Path $PSScriptRoot 'openwebui-hermes-pipe.py') "${Container}:/tmp/hermes-openwebui-pipe.py"
if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel copiar a Pipe para Open WebUI.' }
& docker cp (Join-Path $PSScriptRoot 'install-openwebui-pipe.py') "${Container}:/tmp/install-hermes-pipe.py"
if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel copiar o instalador da Pipe.' }
& docker cp (Join-Path $PSScriptRoot 'hermes-specialists.json') "${Container}:/tmp/hermes-specialists.json"
if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel copiar o catalogo de especialistas.' }
$payload = @{api_key=$apiKey; base_url=$BaseUrl} | ConvertTo-Json -Compress
& docker cp (Join-Path $PSScriptRoot 'verify-hermes-integration.py') "${Container}:/tmp/verify_hermes_integration.py"
if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel copiar o diagnostico de integracao.' }
& docker cp (Join-Path $PSScriptRoot 'configure-openwebui-access.py') "${Container}:/tmp/configure_openwebui_access.py"
if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel copiar a configuracao de permissoes.' }
$payload | & docker exec -i $Container python /tmp/install-hermes-pipe.py
if ($LASTEXITCODE -ne 0) { throw 'Integracao Open WebUI falhou. Confira a mensagem acima.' }
& docker exec $Container python -c "from pathlib import Path; p=Path('/tmp/hermes-webui-locale-restart'); needed=p.exists(); p.unlink(missing_ok=True); raise SystemExit(10 if needed else 0)"
$restartCode = $LASTEXITCODE
if ($restartCode -eq 10) {
    Write-Host 'Reiniciando Open WebUI para aplicar o idioma padrao. Dados e usuarios preservados.'
    & docker restart $Container
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao reiniciar Open WebUI.' }
    & docker cp (Join-Path $PSScriptRoot 'verify-openwebui.py') "${Container}:/tmp/verify-openwebui.py"
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao copiar verificacao de saude.' }
    & docker exec $Container python /tmp/verify-openwebui.py
    if ($LASTEXITCODE -ne 0) { throw 'Open WebUI ainda nao ficou pronto.' }
} elseif ($restartCode -ne 0) { throw 'Falha ao verificar idioma do Open WebUI.' }
Write-Host 'Atualize o Open WebUI. Configure os membros em Administracao > Grupos e selecione o especialista Hermes.'
