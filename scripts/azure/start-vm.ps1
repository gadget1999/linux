param (
 [Parameter(Mandatory=$true)][string]$VMName
)

$cmd_path=(Get-Item $PSCommandPath).DirectoryName
. "$cmd_path/logger.ps1"
. "$cmd_path/find-vm.ps1"

$program=(Get-Item $PSCommandPath).Basename
$logFile="/tmp/$program.log"
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
