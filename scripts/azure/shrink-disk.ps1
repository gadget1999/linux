#param (
# [Parameter(Mandatory=$true)][string]$SourceDiskName,
# [Parameter(Mandatory=$true)][string]$TargetDiskName,
# [Parameter(Mandatory=$true)][string]$TargetSize
#)

$cmd_path=(Get-Item $PSCommandPath).DirectoryName
. "$cmd_path/logger.ps1"
. "$cmd_path/copy-disk.ps1"
. "$cmd_path/resize-vhd.ps1"
$program=(Get-Item $PSCommandPath).Basename
$logFile="/tmp/$program.log"
$logLevel="INFO"
#$logLevel="DEBUG"

################################################
# Shrink a managed disk to a new managed disk
################################################

$SourceDiskName="aks-agentpool-30099824-0_OsDisk_1_4c924b291da545a4b56005c1418022c7"
$TargetDiskName="aks-os-node1"
$TargetSize=31

$sourceDisk=Get-AZDisk -DiskName $SourceDiskName
if ($sourceDisk.Name -ine $SourceDiskName) {
 Write-Error "Cannot find the managed disk: $SourceDiskName"
 Return $false
}

$sourceRGName=$sourceDisk.ResourceGroupName
$sourceLocation=$sourceDisk.Location
$tmpDiskName="tmpDisk-$TargetDiskName"
Write-Log "Creating tmp disk: $tmpDiskName"
$diskConfig=New-AzDiskConfig -SourceResourceId $sourceDisk.Id -Location $sourceLocation -CreateOption Copy 
$tmpDisk=New-AzDisk -Disk $diskConfig -DiskName $tmpDiskName -ResourceGroupName $sourceRGName
Read-Host -Prompt "Please attach disk [$tmpDiskName] to a VM and shrink the partition. Press Enter when it's done"

$random=Get-Random
$tmpStorageAccountName="tmpsa$random"
Write-Log "Creating tmp target storage account: $tmpStorageAccountName"
$tmpStorageAccount=New-AzStorageAccount -ResourceGroupName $sourceRGName -Name $tmpStorageAccountName `
  -Location $sourceLocation -SkuName Standard_LRS -Kind StorageV2

$tmpVHDName="tmpVHD-$TargetDiskName.vhd"
Copy-Disk-To-VHD $tmpDiskName $tmpStorageAccountName $tmpVHDName

Write-Log "Shrinking VHD size to $TargetSize GB..."
$tmpSAS=Get-AzStorageAccountKey -ResourceGroupName $sourceRGName -Name $tmpStorageAccountName
$tmpContext=New-AzStorageContext -StorageAccountName $tmpStorageAccountName -StorageAccountKey ($tmpSAS).Value[0]
$tmpVHDSASUri=New-AzStorageBlobSASToken -Context $tmpContext -Container "vhds" -Blob "$tmpVHDName" `
  -ExpiryTime(get-date).AddSeconds(3600) -FullUri -Permission rw
Resize-VHD -TargetSize $TargetSize -VHDSASUri $tmpVHDSASUri
Read-Host -Prompt "Press Enter after VHD resizing is done..."

Write-Log "Creating disk [$TargetDiskName] from temp VHD..."
$diskConfig = New-AzDiskConfig -AccountType Standard_LRS -Location $location -CreateOption Import `
  -StorageAccountId $tmpStorageAccount.Id -SourceUri $tmpVHDSASUri
New-AzDisk -Disk $diskConfig -ResourceGroupName $sourceRGName -DiskName $TargetDiskName

# clean up
Write-Log "Removing tmp storage account: $tmpStorageAccountName"
#Remove-AzStorageAccount -ResourceGroupName $sourceRGName -Name $tmpStorageAccountName

Write-Log "Removing tmp disk: $tmpDiskName"
#Remove-AzDisk -ResourceGroupName $sourceRGName -DiskName $tmpDiskName
