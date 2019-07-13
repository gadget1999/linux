param (
 [Parameter(Mandatory=$true)][string]$VMName
)

. "./logger.ps1"
$logFile="/tmp/restart-vm.log"
$logLevel="INFO"
#$logLevel="DEBUG"

$vm = Get-AzVM -Name $VMName -Status
if ($vm.PowerState -ne "VM running") {
 Write-Log "VM not running: $VMName" "DEBUG"
 Return
}

Write-Log "Shutting down VM: $VMName"
Stop-AzVM -ResourceGroupName $vm.ResourceGroupName -Name $VMName -Force

Write-Log "Starting VM: $VMName"
Start-AzVM -ResourceGroupName $vm.ResourceGroupName -Name $VMName
Write-Log "Completed"
