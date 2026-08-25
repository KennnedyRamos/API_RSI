[CmdletBinding()]
param(
    [ValidateRange(15, 1440)]
    [int]$IntervalMinutes = 15,
    [string]$TaskName = "RSI Radar - Provisionar Oracle A1 6GB",
    [string]$OciProfile = "DEFAULT"
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$retryPath = Join-Path $PSScriptRoot "oracle_a1_provision_retry.py"
$userProfilePath = [Environment]::GetFolderPath("UserProfile")
$ociConfigPath = Join-Path $userProfilePath ".oci\config"
$sshPublicKeyPath = Join-Path $userProfilePath ".ssh\rsi_radar_oracle_ed25519.pub"
$legacyMonitorTask = "RSI Radar - Capacidade Oracle A1"

foreach ($requiredPath in @($pythonPath, $retryPath, $ociConfigPath, $sshPublicKeyPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Arquivo obrigatório não encontrado: $requiredPath"
    }
}

$arguments = @(
    "`"$retryPath`"",
    "--config-file", "`"$ociConfigPath`"",
    "--profile", "`"$OciProfile`"",
    "--ssh-public-key", "`"$sshPublicKeyPath`"",
    "--task-name", "`"$TaskName`""
) -join " "

$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $arguments -WorkingDirectory $projectRoot
$firstRun = (Get-Date).AddMinutes(1)
$trigger = New-ScheduledTaskTrigger -Once -At $firstRun `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Tenta criar a Oracle A1 de 1 OCPU e 6 GB até a Oracle aceitar a criação." -Force | Out-Null

if (Get-ScheduledTask -TaskName $legacyMonitorTask -ErrorAction SilentlyContinue) {
    Disable-ScheduledTask -TaskName $legacyMonitorTask | Out-Null
}

Write-Host "Tarefa agendada: $TaskName"
Write-Host "Frequência: a cada $IntervalMinutes minuto(s), somente enquanto este usuário estiver conectado."
Write-Host "A tarefa será desativada automaticamente quando a Oracle aceitar a criação da A1."
Write-Host "Estado e log: $env:LOCALAPPDATA\RsiRadar\oracle-a1-provision-retry-state.json"
