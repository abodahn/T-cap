# Registers the T-CAP monitoring agent as a Windows Scheduled Task that runs at
# startup and keeps running. Run this in an elevated PowerShell from the agent folder.
#   powershell -ExecutionPolicy Bypass -File .\install_agent.ps1
param(
  [string]$TaskName = "TCAP-Monitoring-Agent",
  [string]$Python   = "python"
)

$here   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$script = Join-Path $here "tcap_agent.py"

if (-not (Test-Path (Join-Path $here "agent_config.json"))) {
  Write-Host "agent_config.json not found. Copy agent_config.example.json to agent_config.json and set your token first." -ForegroundColor Yellow
  exit 1
}

$action  = New-ScheduledTaskAction -Execute $Python -Argument "`"$script`"" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed and started scheduled task '$TaskName'." -ForegroundColor Green
Write-Host "Remove with:  Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
