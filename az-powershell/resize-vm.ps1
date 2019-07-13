param (
 [Parameter(Mandatory=$true)][string]$VMName
)

$VMStopped = $false

$vm = Get-AzVM -Name $VMName -Status
$VMOldSize = $vm.HardwareProfile.VmSize
Write-Host "Current VM size: $VMOldSize"

$VMSize = Read-Host -Prompt "Enter the new VM size"
$VMNewSize = "Standard_" + $VMSize

if ($vm.HardwareProfile.VmSize -like $VMNewSize) {
 Write-Host "Size is the same, no need to change."
 Return
}

if ($vm.PowerState -eq "VM running") {
 Write-Host "Shutdown VM..."
 Stop-AzVM -ResourceGroupName $vm.ResourceGroupName -Name $VMName -Force
 $VMStopped = $true
}

$vm.HardwareProfile.VmSize = $VMNewSize
Update-AzVM -VM $vm -ResourceGroupName $vm.ResourceGroupName
Write-Host "Resizing completed."

if ($VMStopped) {
 Write-Host "Starting VM..."
 Start-AzVM -ResourceGroupName $vm.ResourceGroupName -Name $VMName
}
