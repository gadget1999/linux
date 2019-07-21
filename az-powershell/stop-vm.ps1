param (
 [Parameter(Mandatory=$true)][string]$VMName
)

. "./logger.ps1"
. "./find-vm.ps1"
$program=(Get-Item $PSCommandPath).Basename
$logFile="/tmp/$program.log"
$logLevel="INFO"
#$logLevel="DEBUG"

$vm = Find-VM -VMName $VMName
if ($vm.Name -ine $VMName) {
 Return
}

if ($vm.PowerState -ne "VM running") {
 Write-Log "VM not running: $VMName" "DEBUG"
 Return
}

Write-Log "Shutting down VM: $VMName"
Stop-AzVM -ResourceGroupName $vm.ResourceGroupName -Name $VMName -Force
Write-Log "Completed"
