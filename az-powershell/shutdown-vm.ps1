$cmd_path=(Get-Item $PSCommandPath).DirectoryName
. "$cmd_path/logger.ps1"
. "$cmd_path/find-vm.ps1"

$program=(Get-Item $PSCommandPath).Basename
$logFile="/tmp/$program.log"
#$logLevel="DEBUG"

function Shutdown-VM([string]$rg, [string]$vm)
{
 Write-Log "Shutdown idle VM: $rg - $vm"
 Stop-AzVM -ResourceGroupName $rg -Name $vm -Force
}

function Shutdown-IdleVMs
{
 $VMs = Get-AzVM -Status
 foreach($VM in $VMs)
 {
  Write-Log "VM: $($VM.Name) (State: $($VM.PowerState))" "DEBUG"
  if ($VM.PowerState -eq "VM stopped")
  {
   Shutdown-VM $VM.ResourceGroupName $VM.Name
  }
  elseif (($VM.PowerState -eq "VM running") -and ($VM.StorageProfile.OsDisk.OsType -eq "Windows"))
  {
   $metric=Get-AzMetric -ResourceId $VM.Id -TimeGrain 01:00:00 -DetailedOutput -MetricNames "Percentage CPU" -AggregationType Maximum
   $cpu=$metric.Data.Maximum
   if ($cpu -ne $null)
   {
    if ($cpu -lt 20)
    {
     Write-Log "VM max CPU in last hour: $cpu%" "INFO"
     Shutdown-VM $VM.ResourceGroupName $VM.Name
    }
    else
    {
     Write-Log "VM max CPU in last hour: $cpu%" "DEBUG"
    }
   }
  }
 }
}

function Shutdown-IdleVMs-In-Subscription([string]$sub)
{
 Set-AzContext -SubscriptionId $sub
 Shutdown-IdleVMs
}

function Shutdown-All-IdleVMs
{
 $subs = Get-AzSubscription
 foreach($sub in $subs)
 {
  Write-Log "Listing VMs under subscription: $($sub.Name) (Id: $($sub.Id))" "DEBUG"
  Shutdown-IdleVMs-In-Subscription $sub.Id
 }
}

Shutdown-All-IdleVMs
