$cmd_path=(Get-Item $PSCommandPath).DirectoryName
. "$cmd_path/logger.ps1"
$program=(Get-Item $PSCommandPath).Basename
$logFile="/tmp/$program.log"
$logLevel="INFO"
#$logLevel="DEBUG"

#############################################
# Copy a managed disk to a VHD
#############################################

function Copy-Disk-To-VHD([string]$SourceDiskName, [string]$TargetStorageAccountName, [string]$TargetVHDName)
{
 $sourceDisk=Get-AZDisk -DiskName $SourceDiskName
 if ($sourceDisk.Name -ine $SourceDiskName) {
  Write-Error "Cannot find the managed disk: $SourceDiskName"
  Return $false
 }

 $targetSA=Get-AzStorageAccount | Where-Object {$_.StorageAccountName -ieq "$TargetStorageAccountName"}
 if ($targetSA.StorageAccountName -ine $TargetStorageAccountName) {
  Write-Error "Cannot find the target storage account: $TargetStorageAccountName"
  Return $false
 }

 $sourceSize=$sourceDisk.DiskSizeGB
 Write-Log "Source disk size: $sourceSize GB" "DEBUG"

 $sourceLocation=$sourceDisk.Location
 $targetLocation=$targetSA.Location
 if ($sourceLocation -ine $targetLocation) {
  Write-Error "Source location ($sourceLocation) is different from target location ($targetLocation)"
  $confirmation = Read-Host "Do you want to proceed? [y/n]"
  if ($confirmation -ine "y") {
   Return $false
  }
 }

 Write-Log "Generating source disk SAS..."
 $sourceRGName = $sourceDisk.ResourceGroupName
 $sourceDiskSAS = Grant-AzDiskAccess -ResourceGroupName $sourceRGName -DiskName $SourceDiskName `
  -Access Read -DurationInSecond 3600
 $sourceDiskSASUri = $sourceDiskSAS.AccessSAS
 if ($sourceDiskSASUri -eq $null) {
  Write-Error "Failed to get SAS Uri for source disk."
  Return $false
 }
 Write-Log "Source disk SAS: $sourceDiskSASUri" "DEBUG"

 Write-Log "Generating target VHD SAS..."
 $targetRGName=$targetSA.ResourceGroupName
 $targetSAS = Get-AzStorageAccountKey -ResourceGroupName $targetRGName -Name $TargetStorageAccountName
 $targetContext = New-AzStorageContext -StorageAccountName $TargetStorageAccountName -StorageAccountKey ($targetSAS).Value[0]
 $targetContainerName = 'vhds'
 if (!(Get-AzStorageContainer -Context $targetContext | where {$_.Name -eq $targetContainerName})) {
  cls
  Write-Log "Generating target VHD container..."
  New-AzStorageContainer -Context $targetContext -Name $targetContainerName -Permission Off
 }

 $targetSASUri = New-AzStorageContainerSASToken -Context $targetContext -ExpiryTime(get-date).AddSeconds(3600) `
  -FullUri -Name "$targetContainerName/$TargetVHDName" -Permission rw
 Write-Log "Target VHD SAS: $targetSASUri" "DEBUG"

 Write-Log "Starting AZCopy..."
 .\azcopy copy $sourceDiskSASUri $targetSASUri

 Write-Log "Revoking source disk SAS..."
 Revoke-AzDiskAccess -ResourceGroupName $sourceRGName -DiskName $SourceDiskName

 # Final Job Status: Completed
 return $targetSASUri
}
