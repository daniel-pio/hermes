[CmdletBinding()]
param([ValidateRange(1024,65535)][int]$WebUIPort = 3000)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'O Windows solicitara autorizacao administrativa para liberar o firewall da rede interna.'
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -WebUIPort ' + $WebUIPort
    $process = Start-Process -FilePath powershell.exe -ArgumentList $arguments -Verb RunAs -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw 'Falha ao liberar o firewall. Execute liberar-lan.ps1 como administrador.' }
    return
}
$ports = @($WebUIPort,9120,6080,8643) | Sort-Object -Unique
$ruleName = 'Hermes-OpenWebUI-LAN-' + $WebUIPort
$rule = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
if ($rule) {
    Set-NetFirewallRule -Name $ruleName -Enabled True -Direction Inbound -Action Allow -Profile Private,Domain -RemoteAddress LocalSubnet -Protocol TCP -LocalPort $ports | Out-Null
} else {
    New-NetFirewallRule -Name $ruleName -DisplayName ('Hermes e Open WebUI - rede interna (' + $WebUIPort + ')') -Enabled True -Direction Inbound -Action Allow -Profile Private,Domain -RemoteAddress LocalSubnet -Protocol TCP -LocalPort $ports | Out-Null
}
Write-Host 'Firewall liberado somente para a sub-rede local em redes Privadas ou de Dominio.'
