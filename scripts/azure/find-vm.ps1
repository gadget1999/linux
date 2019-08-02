$cmd_path=(Get-Item $PSCommandPath).DirectoryName
. "$cmd_path/logger.ps1"

#$logLevel="DEBUG"

function Find-VM-In-Subscription([string]$subscriptionId, [string]$vmName)
{
 Set-AzContext -SubscriptionId $subscriptionId
 $VMs = Get-AzVM -Status | Where-Object {$_.Name -ieq "$VMName"}
 foreach($VM in $VMs)
 {
  Write-Log "VM: $($VM.Name) (State: $($VM.PowerState))" "DEBUG"
  if ($VM.Name -ieq $VMName)
  {
   return $VM
  }
 }
 return 0
}

function Find-VM([string]$vmName)
{
 $subs = Get-AzSubscription
 foreach($sub in $subs)
 {
  $subscriptionId = $sub.Id
  Write-Log "Look up for $vmName under subscription: $($sub.Name) (Id: $subscriptionId)" "DEBUG"
  $vm = Find-VM-In-Subscription $subscriptionId $vmName
  if ($vm.Name -ieq $vmName) {
   # seems return value is an array with first object PSContext, second object is VM
   $realName = $vm[1].Name
   Write-Log "Found VM: $realName"
   return $vm[1]
  }
 }
 Write-Log "Cannot find the VM."
 return $null
}
