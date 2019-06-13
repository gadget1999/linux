#Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
$tenantId="271d6ac1-5f24-4d02-8eb3-c3a6de3e60ff"
$pscredential = Get-Credential -Message "Login as App" -UserName "a1bb67cc-9d3d-4d62-af74-b19ddb6ed2d0"
Connect-AzAccount -ServicePrincipal -Credential $pscredential -TenantId $tenantId