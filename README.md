# BPS Trading Workbench

This repository groups the existing Windows React dashboard, Windows Node SSH controller, and EC2 Python scanner without changing their current runtime flow.

## Runtime layout

```text
Windows: React/Vite UI -> Node controller -> SSH/SCP -> EC2 scanner
EC2:    scan_universe.py -> bps_results.csv
```

## Open in VS Code

Open:

```text
C:\Users\durga\bps-trading-workbench
```

## Windows setup

```powershell
Copy-Item .env.example .env
npm run install:web
```

Set the EC2 values in `.env`. The existing controller currently receives connection values from the UI, so this file is a reference for the planned central configuration and does not alter that flow.

Start the two existing processes in separate terminals:

```powershell
npm run controller
npm run dev
```

Open `http://localhost:5173/`.

The one-command launcher checks the EC2 instance before starting the UI. If the
instance is stopped, it starts it, waits for `running`, and resolves its current
public IP. It then checks the current Windows public IP before starting the UI.
If `BPS_EC2_SECURITY_GROUP_ID` is configured, it adds the current IP as a
`TCP/22` rule only when that rule is missing. Deployment performs the same
instance check, so a stopped instance can be started before files are uploaded.
This requires the AWS CLI and an identity that can call
`ec2:DescribeInstances`, `ec2:StartInstances`,
`ec2:DescribeSecurityGroups`, and `ec2:AuthorizeSecurityGroupIngress`.

Run `aws configure` once on Windows, then use:

```powershell
npm.cmd start
```

This startup check does not remove older IP rules. Scanner deployment remains a
separate operation:

```powershell
npm.cmd run deploy:scanner
```

## EC2 deployment

Set the deployment environment variables in the PowerShell session, then run:

```powershell
$env:BPS_EC2_HOST = "your-ec2-host"
$env:BPS_EC2_KEY_PATH = "C:\keys\scanner.pem"
npm run deploy:scanner
```

The deploy script first creates a timestamped ZIP backup of any previously deployed active scanner files under `$BPS_EC2_REMOTE_DIR/backups/`, then uploads the new scanner files and prepares the EC2 virtual environment. It does not upload credentials, UI dependencies, generated results, or archived scripts.

## Deliberately excluded

`node_modules`, build output, Python caches, credentials, tokens, and generated scan results are not part of the source project.