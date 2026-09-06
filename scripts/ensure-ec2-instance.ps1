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

$instanceId = $env:BPS_EC2_INSTANCE_ID
if (-not $instanceId) {
    Write-Warning 'BPS_EC2_INSTANCE_ID is not configured; skipping EC2 instance status check.'
    exit 0
}

$awsCommand = (Get-Command aws -ErrorAction SilentlyContinue).Source
if (-not $awsCommand -and (Test-Path 'C:\Program Files\Amazon\AWSCLIV2\aws.exe')) {
    $awsCommand = 'C:\Program Files\Amazon\AWSCLIV2\aws.exe'
}
if (-not $awsCommand) { throw 'AWS CLI is required when BPS_EC2_INSTANCE_ID is configured.' }

$awsArgs = @('ec2', 'describe-instances', '--instance-ids', $instanceId, '--output', 'json')
if ($env:BPS_AWS_REGION) { $awsArgs += @('--region', $env:BPS_AWS_REGION) }
$details = (& $awsCommand @awsArgs | ConvertFrom-Json).Reservations[0].Instances[0]
if (-not $details) { throw "EC2 instance not found: $instanceId" }

$state = $details.State.Name
if ($state -eq 'stopped') {
    Write-Host "EC2 instance $instanceId is stopped; starting it..."
    $startArgs = @('ec2', 'start-instances', '--instance-ids', $instanceId, '--output', 'json')
    if ($env:BPS_AWS_REGION) { $startArgs += @('--region', $env:BPS_AWS_REGION) }
    & $awsCommand @startArgs | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Unable to start EC2 instance $instanceId." }

    $waitArgs = @('ec2', 'wait', 'instance-running', '--instance-ids', $instanceId)
    if ($env:BPS_AWS_REGION) { $waitArgs += @('--region', $env:BPS_AWS_REGION) }
    & $awsCommand @waitArgs
    if ($LASTEXITCODE -ne 0) { throw "EC2 instance $instanceId did not reach running state." }
    Write-Host "EC2 instance $instanceId is running."
} elseif ($state -in @('pending', 'stopping')) {
    Write-Host "Waiting for EC2 instance $instanceId to reach running state..."
    $waitArgs = @('ec2', 'wait', 'instance-running', '--instance-ids', $instanceId)
    if ($env:BPS_AWS_REGION) { $waitArgs += @('--region', $env:BPS_AWS_REGION) }
    & $awsCommand @waitArgs
    if ($LASTEXITCODE -ne 0) { throw "EC2 instance $instanceId did not reach running state." }
} elseif ($state -ne 'running') {
    throw "EC2 instance $instanceId is $state and cannot accept SSH connections."
}

$details = (& $awsCommand @awsArgs | ConvertFrom-Json).Reservations[0].Instances[0]
$publicIp = $details.PublicIpAddress
if (-not $publicIp) { throw "EC2 instance $instanceId has no public IP. Use an Elastic IP or configure networking first." }
Write-Host "BPS_EC2_RUNTIME_HOST=$publicIp"
