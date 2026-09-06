param(
    [string]$HostName = $env:BPS_EC2_HOST,
    [string]$UserName = $(if ($env:BPS_EC2_USER) { $env:BPS_EC2_USER } else { "ec2-user" }),
    [string]$KeyPath = $env:BPS_EC2_KEY_PATH,
    [string]$RemoteDir = $(if ($env:BPS_EC2_REMOTE_DIR) { $env:BPS_EC2_REMOTE_DIR } else { "/home/ec2-user/bps-scanner" })
)

$scannerPath = Join-Path $PSScriptRoot "..\services\scanner"
$envFile = Join-Path $PSScriptRoot "..\.env"

if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#=\s]+)\s*=\s*(.*?)\s*$') {
            $name = $matches[1]
            $value = $matches[2].Trim('"', "'")
            if (-not [Environment]::GetEnvironmentVariable($name)) {
                [Environment]::SetEnvironmentVariable($name, $value, "Process")
            }
        }
    }
}

if (-not $HostName) { $HostName = $env:BPS_EC2_HOST }
if (-not $KeyPath) { $KeyPath = $env:BPS_EC2_KEY_PATH }
if ($UserName -eq "ec2-user" -and $env:BPS_EC2_USER) { $UserName = $env:BPS_EC2_USER }
if ($RemoteDir -eq "/home/ec2-user/bps-scanner" -and $env:BPS_EC2_REMOTE_DIR) { $RemoteDir = $env:BPS_EC2_REMOTE_DIR }

$ensureInstanceScript = Join-Path $PSScriptRoot 'ensure-ec2-instance.ps1'
$instanceOutput = & powershell.exe -ExecutionPolicy Bypass -File $ensureInstanceScript
if ($instanceOutput) { $instanceOutput | ForEach-Object { Write-Host $_ } }
if ($LASTEXITCODE -ne 0) { throw "Unable to prepare EC2 instance." }
$runtimeHost = $instanceOutput | Where-Object { $_ -match '^BPS_EC2_RUNTIME_HOST=(.+)$' } | Select-Object -Last 1
if ($runtimeHost -match '^BPS_EC2_RUNTIME_HOST=(.+)$') { $HostName = $matches[1] }

if (-not $HostName) { throw "BPS_EC2_HOST is required." }
if (-not $KeyPath) { throw "BPS_EC2_KEY_PATH is required." }
if (-not (Test-Path $KeyPath)) { throw "SSH key not found: $KeyPath" }

& ssh -i $KeyPath "$UserName@$HostName" "mkdir -p $RemoteDir"
if ($LASTEXITCODE -ne 0) { throw "Unable to connect to EC2." }

$backupCode = @'
import os
import zipfile
from datetime import datetime, timezone

directory = os.getcwd()
names = ["bps_engine.py", "scan_universe.py", "scan_config.json", "requirements.txt"]
existing = [name for name in names if os.path.isfile(os.path.join(directory, name))]
if existing:
    backup = os.path.join(directory, "backups", "scanner-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + ".zip")
    os.makedirs(os.path.dirname(backup), exist_ok=True)
    with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in existing:
            archive.write(os.path.join(directory, name), name)
    print("Created " + backup)
else:
    print("No previous scanner files to back up")
'@
$backupEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($backupCode))
& ssh -i $KeyPath "$UserName@$HostName" "cd $RemoteDir && echo $backupEncoded | base64 --decode | python3"
if ($LASTEXITCODE -ne 0) { throw "Unable to back up the existing scanner files." }

& scp -i $KeyPath `
    (Join-Path $scannerPath "bps_engine.py"), `
    (Join-Path $scannerPath "scan_universe.py"), `
    (Join-Path $scannerPath "scan_config.json"), `
    (Join-Path $scannerPath "requirements.txt") `
    "$UserName@$HostName`:$RemoteDir/"
if ($LASTEXITCODE -ne 0) { throw "Unable to upload scanner files." }

& ssh -i $KeyPath "$UserName@$HostName" "cd $RemoteDir && python3 -m venv .venv 2>/dev/null || true && .venv/bin/pip install -r requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "Unable to prepare the EC2 Python environment." }

Write-Host "Scanner deployed to $UserName@$HostName`:$RemoteDir"
