param (
 [Parameter(Mandatory=$true)][string]$VMName
)

$cmd_path=(Get-Item $PSCommandPath).DirectoryName
. "$cmd_path/logger.ps1"
. "$cmd_path/find-vm.ps1"

$program=(Get-Item $PSCommandPath).Basename
$logFile="/tmp/$program.log"
#$logLevel="DEBUG"

$VMStopped = $false

$vm = Find-VM -VMName $VMName
if ($vm.Name -ine $VMName) {
 Return
}

$VMOldSize = $vm.HardwareProfile.VmSize
Write-Log "Current VM size: $VMOldSize"

$VMSize = Read-Host -Prompt "Enter the new VM size"
$VMNewSize = "Standard_" + $VMSize
Write-Log "New VM size: $VMNewSize"

if ($vm.HardwareProfile.VmSize -like $VMNewSize) {
 Write-Log "Size is the same, no need to change." "DEBUG"
 Return
}

if ($vm.PowerState -eq "VM running") {
 Write-Log "Shutdown VM..." "DEBUG"
 Stop-AzVM -ResourceGroupName $vm.ResourceGroupName -Name $VMName -Force
 $VMStopped = $true
}

$vm.HardwareProfile.VmSize = $VMNewSize
Update-AzVM -VM $vm -ResourceGroupName $vm.ResourceGroupName

if ($VMStopped) {
 Write-Log "Starting VM..." "DEBUG"
 Start-AzVM -ResourceGroupName $vm.ResourceGroupName -Name $VMName
}
Write-Log "Resizing completed."
