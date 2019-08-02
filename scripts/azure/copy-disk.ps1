$cmd_path=(Get-Item $PSCommandPath).DirectoryName
. "$cmd_path/logger.ps1"

#############################################
# Copy a managed disk to a VHD
#############################################

function Copy-Disk-To-VHD
{
 Param
 (
  [Parameter(Mandatory=$true, Position=0)]
  [string] $SourceDiskName,
  [Parameter(Mandatory=$true, Position=1)]
  [string] $TargetStorageAccountName,
  [Parameter(Mandatory=$true, Position=2)]
  [string] $TargetVHDName
 )

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
 $targetSAS=Get-AzStorageAccountKey -ResourceGroupName $targetRGName -Name $TargetStorageAccountName
 $targetContext=New-AzStorageContext -StorageAccountName $TargetStorageAccountName -StorageAccountKey ($targetSAS).Value[0]
 $targetContainerName="vhds"
 if (!(Get-AzStorageContainer -Context $targetContext | where {$_.Name -eq $targetContainerName})) {
  Write-Log "Generating target VHD container..."
  New-AzStorageContainer -Context "$targetContext" -Name $targetContainerName -Permission Off
 }
 $targetVHDSASUri=New-AzStorageContainerSASToken -Context $targetContext -ExpiryTime(get-date).AddSeconds(3600) `
   -FullUri -Name "$targetContainerName/$TargetVHDName" -Permission rw
 Write-Log "Target VHD SAS: $targetVHDSASUri" "DEBUG"

 AzCopyBlob -SourceSASUri $sourceDiskSASUri -TargetSASUri $targetVHDSASUri
 Read-Host -Prompt "Press Enter after azcopy is done..."

 Write-Log "Revoking source disk SAS..."
 Revoke-AzDiskAccess -ResourceGroupName $sourceRGName -DiskName $SourceDiskName
}

function AzCopyBlob
{
 Param
 (
  [Parameter(Mandatory=$true, Position=0)]
  [string] $SourceSASUri,
  [Parameter(Mandatory=$true, Position=1)]
  [string] $TargetSASUri
 )

 # It seems something wrong with local azcopy, run it in Cloud Shell out-of-band for now
 Write-Log "RUN CMD: azcopy copy ""$SourceSASUri"" ""$TargetSASUri"" "
 return $true

 $AzCopyPath="$cmd_path/azcopy.exe"
 if((Test-Path $AzCopyPath) -eq $false) {
  Write-Error "Script is terminating since the provided AzCopyPath does not exist: $AzCopyPath"
  return $false
 }
 
 $azCopyCmd=[string]::Format("""{0}"" copy ""{1}"" ""{2}"" ",$AzCopyPath, $SourceSASUri, $TargetSASUri)
 Write-Log "Starting AzCopy: $AzCopyPath"
 $output = cmd /c $azCopyCmd 2`>`&1
 foreach($s in $output) { Write-Host $s }

 if ($LASTEXITCODE -ne 0) {
  Write-Error "AzCopy failed."
  return $false
 }

 return $true
}