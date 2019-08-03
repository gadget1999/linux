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

$newdisk=Get-AzDisk -ResourceGroupName $vm.ResourceGroupName -DiskName aks-node1-os
Set-AzVMOSDisk -VM $vm -ManagedDiskId $newdisk.Id -Name $newdisk.Name
Update-AzVM -ResourceGroupName MC_AKS-Test_aks-test_eastus -VM $vm
