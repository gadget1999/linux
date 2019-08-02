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


$TargetRGName = Read-Host -Prompt "Enter the target resource group name"
$TargetStorageAccountName = Read-Host -Prompt "Enter the target storage account name"
$TargetStorageAccount = Get-AzStorageAccount -ResourceGroupName $TargetRGName -Name $TargetStorageAccountName

$TargetSAS = Get-AzStorageAccountKey -ResourceGroupName $TargetRGName -Name $TargetStorageAccountName
$TargetContext = New-AzStorageContext -StorageAccountName $TargetStorageAccountName -StorageAccountKey ($TargetSAS).Value[0]
$TargetContainerName = 'vhds'
if (!(Get-AzStorageContainer -Context $TargetContext | where {$_.Name -eq $TargetContainerName})) {
 cls
 Write-Verbose "Container $TargetContainerName not found.  Creating..."
 New-AzStorageContainer -Context $TargetContext -Name $TargetContainerName -Permission Off
}

$SourceDiskSAS = Read-Host -Prompt "Enter the source disk SAS URI"

$ContainerSASUri = New-AzStorageContainerSASToken -Context $TargetContext -ExpiryTime(get-date).AddSeconds(3600) -FullUri -Name $TargetContainerName -Permission rw
.\azcopy copy $SourceDiskSAS $ContainerSASUri
