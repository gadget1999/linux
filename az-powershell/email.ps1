$cmd_path=(Get-Item $PSCommandPath).DirectoryName
. "$cmd_path/logger.ps1"

#$logLevel="DEBUG"

function Send-Email([string]$subject, [string]$body)
{
 $cmd = "/usr/local/bin/send-email ""$subject"" ""$body"" "
 Invoke-Expression $cmd
}
