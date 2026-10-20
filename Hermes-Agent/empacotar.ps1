$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
# Explicit list: never export .env, Docker volumes, chats or Chromium profiles.
$files = @('INSTALAR.cmd','instalar-hermes.ps1','iniciar.ps1','Dockerfile',
    'docker-compose.yml','browser-stack.sh','browser-s6-run','configure-browser.py',
    'configure-browser-init','verify-health.py','.dockerignore','.gitignore',
    '.env.example','LEIA-ME.txt','empacotar.ps1','instalar-hermes.sh','LEIA-ME-LINUX.txt',
    'browser-pool.py','browser-session.sh','browser-pool-client.py','patch-browser-pool.py',
    'browser-pool-auth.py','browser-pool.html','LEIA-ME-3-PESQUISAS.txt',
    'openwebui-hermes-pipe.py','install-openwebui-pipe.py','integrar-openwebui.ps1',
    'integrar-openwebui.sh','LEIA-ME-OPEN-WEBUI.txt','hermes-exports.py',
    'hermes-specialists.json','hermes-workspace.py','patch-specialists.py','LEIA-ME-ESPECIALISTAS.txt',
    'configure-openwebui-access.py','docker-compose.openwebui.yml','instalar-tudo.ps1',
    'INSTALAR-LINUX.sh','LEIA-ME-INSTALACAO-COMPLETA.txt','verify-openwebui.py','liberar-lan.ps1',
    'verify-hermes-integration.py','VERSAO.txt')
$outputDir = Join-Path $PSScriptRoot 'dist'
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$staging = Join-Path $outputDir ('pacote-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $staging | Out-Null
$manifest = foreach ($file in $files) {
    $source = Join-Path $PSScriptRoot $file
    if (-not (Test-Path -LiteralPath $source)) { throw "Arquivo ausente: $file" }
    $target = Join-Path $staging $file
    Copy-Item -LiteralPath $source -Destination $target
    [PSCustomObject]@{ File = $file; SHA256 = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash }
}
$manifest | Export-Csv -LiteralPath (Join-Path $staging 'SHA256SUMS.csv') -NoTypeInformation -Encoding UTF8
$zipPath = Join-Path $outputDir 'Hermes-Agent-Installer-v2026.9.11-LAN-3.zip'
$stream = [IO.File]::Open($zipPath, [IO.FileMode]::Create)
$zip = New-Object IO.Compression.ZipArchive($stream, [IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($file in @($files) + @('SHA256SUMS.csv')) {
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip,
            (Join-Path $staging $file), ('Hermes-Agent/' + $file)) | Out-Null
    }
} finally { $zip.Dispose(); $stream.Dispose() }
Write-Host "Pacote criado: $zipPath"
Write-Host "SHA256: $((Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash)"
foreach ($platform in @('Windows','Linux')) {
    $combined = Join-Path $outputDir "Hermes-OpenWebUI-Installer-$platform-v2026.9.11.zip"
    Copy-Item -LiteralPath $zipPath -Destination $combined
    Write-Host "Pacote integrado $platform criado: $combined"
}
