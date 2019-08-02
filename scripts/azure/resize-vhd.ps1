$cmd_path=(Get-Item $PSCommandPath).DirectoryName
. "$cmd_path/logger.ps1"

function Resize-VHD
{
 Param
 (
  [Parameter(Mandatory=$true, Position=0)]
  [string] $VHDSASUri,
  [Parameter(Mandatory=$true, Position=1)]
  [int] $TargetSize
 )

 ################################################
 # Shrink Azure VHD without download/upload
 ################################################

 $AzVHDResizer="$cmd_path/AzureDiskResizer/WindowsAzureDiskResizer.exe"
 if((Test-Path $AzVHDResizer) -eq $false) {
  Write-Error "Script is terminating since the provided AzCopyPath does not exist: $AzVHDResizer"
  return $false
 }

 # seems a bit tricky to get input, run out-of-band for now
 Write-Log "RUN CMD: ""$AzVHDResizer"" $TargetSize ""$VHDSASUri"" " "DEBUG"
 return

 & "$AzVHDResizer" $TargetSize "$VHDSASUri"
}