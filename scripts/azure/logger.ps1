# all logging settins
$logLevel = "INFO" # ("DEBUG","INFO","WARN","ERROR")
$logSize = 1mb # 30kb
$logCount = 10
# end of settings

$loggingEnabled=$true
function Write-Log-Line ($line) {
 if ($loggingEnabled) {
  try { Add-Content $logFile -Value $Line }
  catch {
   Write-Host "Failed to write to log file, skipping logging."
   $loggingEnabled=$false
  }
 }
 
 Write-Host $Line
}

# http://stackoverflow.com/a/38738942
Function Write-Log {
 [CmdletBinding()]
 Param(
  [Parameter(Mandatory=$True)]
  [string]
  $Message,
 
  [Parameter(Mandatory=$False)]
  [String]
  $Level = "INFO"
 )

 $levels = ("DEBUG","INFO","WARN","ERROR")
 $logLevelPos = [array]::IndexOf($levels, $logLevel)
 $levelPos = [array]::IndexOf($levels, $Level)
 $Stamp = (Get-Date).toString("yyyy/MM/dd HH:mm:ss:fff")

 if ($logLevelPos -lt 0){
  Write-Log-Line "$Stamp ERROR Wrong logLevel configuration [$logLevel]"
 }
 
 if ($levelPos -lt 0){
  Write-Log-Line "$Stamp ERROR Wrong log level parameter [$Level]"
 }

 $Line = "$Stamp $Level $Message"

 # if level parameter is wrong or configuration is wrong I still want to see the 
 # message in log
 if ($levelPos -lt $logLevelPos -and $levelPos -ge 0 -and $logLevelPos -ge 0){
  Write-Host $Line
  return
 }

 Write-Log-Line $Line
}

