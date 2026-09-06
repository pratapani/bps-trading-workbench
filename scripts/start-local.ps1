$projectRoot = Split-Path -Parent $PSScriptRoot
$ensureInstanceScript = Join-Path $PSScriptRoot 'ensure-ec2-instance.ps1'

$instanceOutput = & powershell.exe -ExecutionPolicy Bypass -File $ensureInstanceScript
if ($instanceOutput) { $instanceOutput | ForEach-Object { Write-Host $_ } }
if ($LASTEXITCODE -ne 0) { throw 'EC2 instance preflight failed; UI startup stopped.' }
$runtimeHost = $instanceOutput | Where-Object { $_ -match '^BPS_EC2_RUNTIME_HOST=(.+)$' } | Select-Object -Last 1
if ($runtimeHost -match '^BPS_EC2_RUNTIME_HOST=(.+)$') { $env:BPS_EC2_HOST = $matches[1] }

$ensureSshScript = Join-Path $PSScriptRoot 'ensure-ssh-access.ps1'

& powershell.exe -ExecutionPolicy Bypass -File $ensureSshScript
if ($LASTEXITCODE -ne 0) { throw 'SSH access check failed; UI startup stopped.' }

$controllerRunning = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue

if (-not $controllerRunning) {
    Start-Process powershell.exe -ArgumentList @(
        '-NoExit',
        '-ExecutionPolicy', 'Bypass',
        '-Command', "Set-Location '$projectRoot'; npm.cmd run controller"
    ) -WorkingDirectory $projectRoot

    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 250
        $controllerRunning = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
        if ($controllerRunning) { break }
    }
    if (-not $controllerRunning) { throw 'Controller did not start on port 8787.' }
}

npm.cmd run dev --prefix apps/web -- --open
