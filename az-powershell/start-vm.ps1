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

if ($vm.PowerState -eq "VM running") {
 Write-Log "VM already running: $VMName" "DEBUG"
 Return
}

Write-Log "Starting VM: $VMName"
Start-AzVM -ResourceGroupName $vm.ResourceGroupName -Name $VMName
Write-Log "Completed"
