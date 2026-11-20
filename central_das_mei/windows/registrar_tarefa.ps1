# Cria no Agendador de Tarefas do Windows:
#  1) "Central de DAS MEI": inicia o servico em segundo plano ao entrar no Windows;
#  2) "Central de DAS MEI - garantir": todo dia 06:40 religa o servico se tiver parado
#     (e acorda o PC da suspensao, se o hardware permitir).
# O servico tem trava de instancia unica: chamar de novo nao duplica.
# Tambem restringe a pasta dos documentos ao usuario atual, Administradores e SYSTEM.
param([Parameter(Mandatory=$true)][string]$Pasta)
$ErrorActionPreference = 'Stop'
$Pasta = (Resolve-Path $Pasta).Path
$py = Join-Path $Pasta '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $py)) { throw "pythonw.exe nao encontrado em $py" }
$usuario = "$env:USERDOMAIN\$env:USERNAME"

$acao = New-ScheduledTaskAction -Execute $py -Argument '-m dasmei servico' -WorkingDirectory $Pasta
$cfg = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Limited

$logon = New-ScheduledTaskTrigger -AtLogOn -User $usuario
Register-ScheduledTask -TaskName 'Central de DAS MEI' -Action $acao -Trigger $logon -Settings $cfg `
  -Principal $principal -Description 'Robo fiscal: consulta, emite e organiza os DAS dos clientes MEI.' -Force | Out-Null

$cfg2 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -WakeToRun -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$diario = New-ScheduledTaskTrigger -Daily -At '06:40'
Register-ScheduledTask -TaskName 'Central de DAS MEI - garantir' -Action $acao -Trigger $diario -Settings $cfg2 `
  -Principal $principal -Description 'Garante que o servico da Central de DAS MEI esteja rodando.' -Force | Out-Null

# Protecao da pasta dos documentos (dados fiscais de clientes - LGPD)
$docs = & (Join-Path $Pasta '.venv\Scripts\python.exe') -c "from dasmei import config; print(config.carregar().pasta_documentos)"
if ($docs -and (Test-Path $docs)) {
  icacls "$docs" /inheritance:r /grant:r "${usuario}:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" | Out-Null
  Write-Host "Pasta protegida: $docs"
}
# Versao separada: atalho "Central de DAS MEI" na area de trabalho (abre a tela local)
$modo = & (Join-Path $Pasta '.venv\Scripts\python.exe') -c "from dasmei import config; print(config.carregar().modo_gestor)"
if ($modo -eq 'local') {
  $atalho = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Central de DAS MEI.lnk'
  $ws = New-Object -ComObject WScript.Shell
  $lnk = $ws.CreateShortcut($atalho)
  $lnk.TargetPath = $py
  $lnk.Arguments = '-m dasmei abrir'
  $lnk.WorkingDirectory = $Pasta
  $lnk.Description = 'Central de DAS MEI'
  $lnk.Save()
  Write-Host "Atalho criado: $atalho"
}
Start-ScheduledTask -TaskName 'Central de DAS MEI'
Write-Host 'Tarefas criadas e servico iniciado.'
