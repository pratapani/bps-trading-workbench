$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot '.env'

if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#=\s]+)\s*=\s*(.*?)\s*$') {
            $name = $matches[1]
            $value = $matches[2].Trim('"', "'")
            if (-not [Environment]::GetEnvironmentVariable($name)) {
                [Environment]::SetEnvironmentVariable($name, $value, 'Process')
            }
        }
    }
}

$groupId = $env:BPS_EC2_SECURITY_GROUP_ID
if (-not $groupId) {
    Write-Warning 'BPS_EC2_SECURITY_GROUP_ID is not configured; skipping SSH rule check.'
    exit 0
}

$awsCommand = (Get-Command aws -ErrorAction SilentlyContinue).Source
if (-not $awsCommand -and (Test-Path 'C:\Program Files\Amazon\AWSCLIV2\aws.exe')) {
    $awsCommand = 'C:\Program Files\Amazon\AWSCLIV2\aws.exe'
}
if (-not $awsCommand) {
    throw 'AWS CLI is required when BPS_EC2_SECURITY_GROUP_ID is configured.'
}

$publicIp = (Invoke-RestMethod -Uri 'https://api.ipify.org?format=text').Trim()
if ($publicIp -notmatch '^\d{1,3}(\.\d{1,3}){3}$') {
    throw "Could not determine a valid public IP: $publicIp"
}
$cidr = "$publicIp/32"

$awsArgs = @('ec2', 'describe-security-groups', '--group-ids', $groupId, '--output', 'json')
if ($env:BPS_AWS_REGION) { $awsArgs += @('--region', $env:BPS_AWS_REGION) }
$securityGroupJson = & $awsCommand @awsArgs
if ($LASTEXITCODE -ne 0) { throw "Unable to read security group $groupId." }
$securityGroup = $securityGroupJson | ConvertFrom-Json
$sshRules = @($securityGroup.SecurityGroups[0].IpPermissions | Where-Object {
    $_.IpProtocol -eq 'tcp' -and $_.FromPort -eq 22 -and $_.ToPort -eq 22
})
$allowedCidrs = @($sshRules | ForEach-Object { $_.IpRanges } | ForEach-Object { $_.CidrIp })

if ($allowedCidrs -contains $cidr) {
    Write-Host "SSH access already allowed for $cidr in $groupId."
    exit 0
}

$permissionJson = @(
    [ordered]@{
        IpProtocol = 'tcp'
        FromPort = 22
        ToPort = 22
        IpRanges = @([ordered]@{ CidrIp = $cidr; Description = 'BPS Windows deployment' })
    }
) | ConvertTo-Json -Compress -Depth 5
$authorizeArgs = @('ec2', 'authorize-security-group-ingress', '--group-id', $groupId, '--ip-permissions', $permissionJson)
if ($env:BPS_AWS_REGION) { $authorizeArgs += @('--region', $env:BPS_AWS_REGION) }
& $awsCommand @authorizeArgs
if ($LASTEXITCODE -ne 0) { throw "Unable to add SSH access for $cidr to $groupId." }
Write-Host "Added SSH access for $cidr to $groupId."
