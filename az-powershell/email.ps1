$cmd_path=(Get-Item $PSCommandPath).DirectoryName
. "$cmd_path/logger.ps1"

#$logLevel="DEBUG"

function Send-Email([string]$subject, [string]$body)
{
 $cmd = "/home/share/bin/send-email" 
 Start-Process -FilePath $cmd -ArgumentList ("$subject", "$body")
}
