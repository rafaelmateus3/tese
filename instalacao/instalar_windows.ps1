# Cria duas tarefas agendadas:
#   SAD ciclo noturno   todos os dias às 02:00 (ciclo.py)
#   SAD dashboard       ao arrancar o computador (uvicorn na porta 8000)
# e abre a porta 8000 na firewall para a rede interna.

param([string]$Hora = "02:00", [int]$Porta = 8000)
$ErrorActionPreference = "Stop"
$Pasta = Split-Path $PSScriptRoot -Parent   # a raiz do projeto, um nível acima
$Python = (Get-Command python).Source
Write-Host "python: $Python"
Write-Host "pasta:  $Pasta"

& $Python -m pip install -r "$Pasta\requirements.txt"
if (-not (Test-Path "$Pasta\.env")) { throw "Falta o .env (copiar de .env.exemplo e preencher)." }

$conta = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Highest
$def = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
        -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 8)

$ciclo = New-ScheduledTaskAction -Execute $Python -Argument "ciclo.py" -WorkingDirectory $Pasta
Register-ScheduledTask -TaskName "SAD ciclo noturno" -Force -Principal $conta -Settings $def `
    -Action $ciclo -Trigger (New-ScheduledTaskTrigger -Daily -At $Hora) | Out-Null

$defDash = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
        -AllowStartIfOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
$dash = New-ScheduledTaskAction -Execute $Python `
    -Argument "-m uvicorn server:app --host 0.0.0.0 --port $Porta" -WorkingDirectory "$Pasta\dashboard"
Register-ScheduledTask -TaskName "SAD dashboard" -Force -Principal $conta -Settings $defDash `
    -Action $dash -Trigger (New-ScheduledTaskTrigger -AtStartup) | Out-Null

if (-not (Get-NetFirewallRule -DisplayName "SAD dashboard" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "SAD dashboard" -Direction Inbound -Protocol TCP `
        -LocalPort $Porta -Action Allow -Profile Domain,Private | Out-Null
}
Start-ScheduledTask -TaskName "SAD dashboard"
Write-Host ""
Write-Host "Feito. Dashboard em http://$($env:COMPUTERNAME):$Porta"
Write-Host "Ciclo noturno às $Hora. Para correr já: Start-ScheduledTask 'SAD ciclo noturno'"
Write-Host "Registos do ciclo em $Pasta\logs"
