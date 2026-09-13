import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(__dirname, 'public');
const REMOTE_DIR_DEFAULT = '/home/ec2-user/bps-scanner';
const PORT = Number(process.env.BPS_CONTROLLER_PORT || 8787);

let state = {running:false, status:'idle', message:'Ready', lines:[], startedAt:null, finishedAt:null, resultFile:null, error:null};

function log(line){
  const clean = String(line).replace(/\r/g,'');
  if(!clean) return;
  state.lines.push(clean);
  if(state.lines.length>500) state.lines.shift();
  console.log(clean);
}
function run(cmd,args,opts={}){
  return new Promise((resolve,reject)=>{
    const p=spawn(cmd,args,{windowsHide:true,...opts});
    let out='',err='';
    p.stdout?.on('data',d=>{out+=d; d.toString().split(/\r?\n/).forEach(log)});
    p.stderr?.on('data',d=>{err+=d; d.toString().split(/\r?\n/).forEach(x=>log('[stderr] '+x))});
    p.on('error',reject);
    p.on('close',code=>code===0?resolve({out,err}):reject(new Error(`${cmd} exited with code ${code}`)));
  });
}
function json(res,obj,code=200){
  res.writeHead(code,{'Content-Type':'application/json','Access-Control-Allow-Origin':'*','Cache-Control':'no-store'});res.end(JSON.stringify(obj));
}
function body(req){return new Promise((resolve,reject)=>{let s='';req.on('data',d=>s+=d);req.on('end',()=>{try{resolve(s?JSON.parse(s):{})}catch(e){reject(e)}})})}
function formatExpiry(value){
  if(typeof value!=='string'||!value.trim()) return '';
  const match=value.trim().match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if(!match) return value.trim();
  const months=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const [,year,month,day]=match;
  return `${day}-${months[Number(month)-1]||month}-${year}`;
}
function archiveStamp(date=new Date()){
  const pad=value=>String(value).padStart(2,'0');
  return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}_${pad(date.getHours())}-${pad(date.getMinutes())}-${pad(date.getSeconds())}`;
}
function archiveExpiry(expiry){
  return String(expiry||'NoExpiry').replace(/[^A-Za-z0-9-]/g,'-');
}


function awsCliPath(){
  const candidates=[];
  if(process.env.AWS_CLI_PATH) candidates.push(process.env.AWS_CLI_PATH);
  if(process.env.LOCALAPPDATA) candidates.push(path.join(process.env.LOCALAPPDATA,'Programs','Amazon','AWSCLIV2','aws.exe'));
  if(process.env.ProgramFiles) candidates.push(path.join(process.env.ProgramFiles,'Amazon','AWSCLIV2','aws.exe'));
  if(process.env['ProgramFiles(x86)']) candidates.push(path.join(process.env['ProgramFiles(x86)'],'Amazon','AWSCLIV2','aws.exe'));
  for(const candidate of candidates){
    if(candidate && fs.existsSync(candidate)) return candidate;
  }
  return 'aws';
}

function awsBaseArgs(){
  const args=[];
  const region=process.env.BPS_AWS_REGION;
  if(region?.trim()) args.push('--region',region.trim());
  return args;
}

async function ensureSshAccess(cfg){
  const aws=awsCliPath();
  const securityGroupId=process.env.BPS_EC2_SECURITY_GROUP_ID || cfg.securityGroupId || 'sg-00c15ab4be4a6979a';
  if(!securityGroupId){
    throw new Error('BPS_EC2_SECURITY_GROUP_ID is required to refresh SSH access from the UI.');
  }

  state.status='ssh-access';state.message='Refreshing SSH access';
  log('Checking current Windows public IP for SSH access...');

  let publicIp='';
  try{
    const response=await fetch('https://api.ipify.org');
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    publicIp=(await response.text()).trim();
  }catch(error){
    throw new Error(`Unable to determine current Windows public IP. ${error.message}`);
  }

  if(!/^\d{1,3}(?:\.\d{1,3}){3}$/.test(publicIp)){
    throw new Error(`Invalid public IP returned by api.ipify.org: ${publicIp}`);
  }

  const cidr=`${publicIp}/32`;
  log(`Current Windows public IP: ${publicIp}`);

  let sgResult;
  try{
    sgResult=await run(aws,[
      ...awsBaseArgs(),
      'ec2','describe-security-groups',
      '--group-ids',securityGroupId,
      '--query','SecurityGroups[0].IpPermissions[?FromPort==`22` && ToPort==`22` && IpProtocol==`tcp`].IpRanges[].CidrIp',
      '--output','text'
    ]);
  }catch(error){
    throw new Error(`Unable to inspect SSH security-group rules. ${error.message}`);
  }

  const ranges=String(sgResult.out||'').split(/\s+/).map(x=>x.trim()).filter(Boolean);

  if(ranges.includes(cidr)){
    log(`✓ SSH access already allowed for ${cidr}`);
    return;
  }

  log(`SSH access missing for ${cidr} — adding rule to ${securityGroupId}...`);

  try{
    // Avoid --ip-permissions JSON because Windows native argument parsing can
    // strip JSON quotes. The simple AWS CLI form is robust.
    await run(aws,[
      ...awsBaseArgs(),
      'ec2','authorize-security-group-ingress',
      '--group-id',securityGroupId,
      '--protocol','tcp',
      '--port','22',
      '--cidr',cidr
    ]);
  }catch(error){
    // Another preflight may have added the rule between describe and authorize.
    try{
      const verify=await run(aws,[
        ...awsBaseArgs(),
        'ec2','describe-security-groups',
        '--group-ids',securityGroupId,
        '--query','SecurityGroups[0].IpPermissions[?FromPort==`22` && ToPort==`22` && IpProtocol==`tcp`].IpRanges[].CidrIp',
        '--output','text'
      ]);
      const verifiedRanges=String(verify.out||'').split(/\s+/).map(x=>x.trim()).filter(Boolean);
      if(verifiedRanges.includes(cidr)){
        log(`✓ SSH access already added for ${cidr}`);
        return;
      }
    }catch{}
    throw new Error(`Unable to add SSH access for ${cidr}. ${error.message}`);
  }

  log(`✓ SSH access added for ${cidr}`);
}

async function ensureEc2Ready(cfg){
  const instanceId=process.env.BPS_EC2_INSTANCE_ID || cfg.instanceId || 'i-05a5ee6857acfb59f';
  const aws=awsCliPath();

  state.status='ec2';state.message='Checking EC2 instance';
  log(`EC2 instance: ${instanceId}`);
  log(`AWS CLI: ${aws}`);

  let result;
  try{
    result=await run(aws,[
      ...awsBaseArgs(),
      'ec2','describe-instances',
      '--instance-ids',instanceId,
      '--query','Reservations[0].Instances[0].State.Name',
      '--output','text'
    ]);
  }catch(error){
    throw new Error(`Unable to query EC2 via AWS CLI. Make sure AWS credentials are configured. ${error.message}`);
  }

  let status=String(result.out||'').trim().split(/\r?\n/).filter(Boolean).pop()||'unknown';
  log(`EC2 status: ${status}`);

  if(status==='stopped'){
    state.status='ec2';state.message='Starting EC2 instance';
    log('EC2 is stopped — starting instance...');
    await run(aws,[
      ...awsBaseArgs(),
      'ec2','start-instances',
      '--instance-ids',instanceId,
      '--query','StartingInstances[0].CurrentState.Name',
      '--output','text'
    ]);
    log('✓ EC2 start requested');
  }else if(status==='pending'){
    log('EC2 is already starting — waiting...');
  }else if(status==='running'){
    log('✓ EC2 is already running');
  }else if(status==='stopping'){
    throw new Error('EC2 is stopping. Please wait for it to stop and run the scan again.');
  }else if(status==='shutting-down'){
    throw new Error('EC2 is shutting down. Please wait and run the scan again.');
  }else if(status==='terminated'){
    throw new Error('EC2 instance is terminated and cannot be started.');
  }else{
    throw new Error(`EC2 is not ready. Current state: ${status}`);
  }

  if(status!=='running'){
    state.status='ec2';state.message='Waiting for EC2 to become running';
    log('Waiting for EC2 to reach running state...');
    await run(aws,[...awsBaseArgs(),'ec2','wait','instance-running','--instance-ids',instanceId]);
    log('✓ EC2 instance is running');
  }

  // The instance uses an Elastic IP, but retrieving it from AWS keeps the
  // controller independent of a hard-coded host value.
  const ipResult=await run(aws,[
    ...awsBaseArgs(),
    'ec2','describe-instances',
    '--instance-ids',instanceId,
    '--query','Reservations[0].Instances[0].PublicIpAddress',
    '--output','text'
  ]);
  const currentHost=String(ipResult.out||'').trim().split(/\r?\n/).filter(Boolean).pop()||'';
  if(!currentHost || currentHost==='None' || currentHost==='null'){
    throw new Error('EC2 is running but has no public IP address.');
  }
  log(`EC2 public IP: ${currentHost}`);
  return currentHost;
}

async function waitForSsh(host,user,key){
  state.status='connecting';state.message='Waiting for SSH';
  log(`Waiting for SSH on ${host}:22...`);

  const attempts=18; // up to ~90 seconds
  let lastError=null;

  for(let i=1;i<=attempts;i++){
    try{
      await run('ssh',[
        '-o','ConnectTimeout=5',
        '-o','ConnectionAttempts=1',
        '-o','StrictHostKeyChecking=accept-new',
        '-i',key,
        `${user}@${host}`,
        'echo BPS_SSH_OK'
      ]);
      log('✓ SSH connection');
      return;
    }catch(error){
      lastError=error;
      if(i<attempts){
        log(`SSH not ready (${i}/${attempts}) — retrying in 5s...`);
        await new Promise(resolve=>setTimeout(resolve,5000));
      }
    }
  }

  throw new Error(`EC2 is running but SSH is not reachable after ${attempts*5} seconds. ${lastError?.message||''}`);
}

async function doScan(cfg){
  const user=cfg.user || 'ec2-user';
  if(typeof cfg.expiry!=='string' || !cfg.expiry.trim()){
    throw new Error('Expiry date is required. Select an expiry before running the scan.');
  }
  const key=cfg.keyPath;
  const remoteDir=cfg.remoteDir || REMOTE_DIR_DEFAULT;
  if(!key) throw new Error('SSH key path is required.');
  if(!fs.existsSync(key)) throw new Error(`SSH key not found: ${key}`);
  fs.mkdirSync(PUBLIC,{recursive:true});

  const runtimeConfig={
    min_otm_percent:Number(cfg.minOtm), max_otm_percent:Number(cfg.maxOtm),
    max_spread_width:Number(cfg.maxWidth), min_profit_to_loss:Number(cfg.minPL),
    max_profit_to_loss:Number(cfg.maxPL), min_oi:Number(cfg.minOI), min_volume:Number(cfg.minVolume),
    expiry:formatExpiry(cfg.expiry)
  };
  const configFile=path.join(__dirname,'public','runtime_scan_config.json');
  fs.writeFileSync(configFile,JSON.stringify(runtimeConfig,null,2));

  // Ensure the EC2 instance is running even when the scan is launched
  // directly from the dashboard while the instance is stopped.
  const host=await ensureEc2Ready(cfg);
  await ensureSshAccess(cfg);
  await waitForSsh(host,user,key);

  state.status='uploading';state.message='Uploading scan configuration';
  await run('scp',['-q','-o','ConnectTimeout=12','-i',key,configFile,`${user}@${host}:${remoteDir}/scan_config.json`]);
  log('✓ Scan configuration uploaded');

  if(cfg.sessionToken?.trim()){
    const tokenFile=path.join(__dirname,'public','.bps_session_token.tmp');
    fs.writeFileSync(tokenFile,cfg.sessionToken.trim(),'utf8');

    try{
      const remoteToken='/tmp/bps_session_token';

      // Upload fresh token to EC2 temporarily
      await run('scp',[
        '-q',
        '-o','ConnectTimeout=12',
        '-i',key,
        tokenFile,
        `${user}@${host}:${remoteToken}`
      ]);

      // Replace ONLY BREEZE_SESSION_TOKEN in EC2 .env
      const updateEnvCmd =
        `cd ${remoteDir} && ` +
        `source .venv/bin/activate && ` +
        `python -c "from pathlib import Path; ` +
        `p=Path('.env'); ` +
        `t=Path('${remoteToken}').read_text(encoding='utf-8').strip(); ` +
        `lines=p.read_text(encoding='utf-8').splitlines() if p.exists() else []; ` +
        `lines=[x for x in lines if not x.startswith('BREEZE_SESSION_TOKEN=')]; ` +
        `lines.append('BREEZE_SESSION_TOKEN='+t); ` +
        `p.write_text('\\\\n'.join(lines)+'\\\\n',encoding='utf-8')" && ` +
        `rm -f ${remoteToken} && ` +
        `grep -q '^BREEZE_SESSION_TOKEN=' .env`;

      await run('ssh',[
        '-o','ConnectTimeout=12',
        '-i',key,
        `${user}@${host}`,
        updateEnvCmd
      ]);

      log('✓ Session token updated in EC2 .env');

    } finally {
      try{fs.unlinkSync(tokenFile)}catch{}
    }
  }

  state.status='scanning';state.message='Running scanner';
  await run('ssh',['-o','ConnectTimeout=12','-i',key,`${user}@${host}`,`cd ${remoteDir} && source .venv/bin/activate && python scan_universe.py`]);
  log('✓ Scanner finished');

  state.status='downloading';state.message='Copying results to Windows';
  const archiveName=`ExpiryData_${archiveExpiry(runtimeConfig.expiry)}_${archiveStamp()}.csv`;
  const archiveTarget=path.join(PUBLIC,archiveName);
  await run('scp',['-q','-o','ConnectTimeout=12','-i',key,`${user}@${host}:${remoteDir}/bps_results.csv`,archiveTarget]);
  state.resultFile=archiveName;
  log(`✓ Archived results copied to ${archiveTarget}`);

  const target=path.join(PUBLIC,'latest_bps_results.csv');
  try{
    fs.copyFileSync(archiveTarget,target);
    log(`✓ Latest results copied to ${target}`);
  }catch(error){
    log(`⚠ Latest results not updated; close the open CSV and refresh: ${error.message}`);
  }
  state.status='complete';state.message='Scan complete';
}

const server=http.createServer(async(req,res)=>{
  if(req.method==='OPTIONS'){res.writeHead(204,{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET,POST,OPTIONS','Access-Control-Allow-Headers':'Content-Type'});return res.end()}
  if(req.url?.startsWith('/api/results/')&&req.method==='GET'){
    const fileName=decodeURIComponent(req.url.slice('/api/results/'.length).split('?')[0]);
    if(!fileName||path.basename(fileName)!==fileName||!fileName.endsWith('.csv'))return json(res,{error:'Invalid result file'},400);
    const filePath=path.join(PUBLIC,fileName);
    if(!fs.existsSync(filePath))return json(res,{error:'Result file not found'},404);
    res.writeHead(200,{'Content-Type':'text/csv; charset=utf-8','Access-Control-Allow-Origin':'*','Cache-Control':'no-store'});
    return fs.createReadStream(filePath).pipe(res);
  }
  if(req.url==='/api/status'&&req.method==='GET') return json(res,state);
  if(req.url==='/api/run'&&req.method==='POST'){
    if(state.running) return json(res,{error:'A scan is already running.'},409);
    let cfg;try{cfg=await body(req)}catch{return json(res,{error:'Invalid JSON'},400)}
    state={running:true,status:'starting',message:'Starting scan',lines:[],startedAt:new Date().toISOString(),finishedAt:null,resultFile:null,error:null};
    json(res,{ok:true});
    doScan(cfg).then(()=>{state.running=false;state.finishedAt=new Date().toISOString()}).catch(e=>{state.running=false;state.status='error';state.message='Scan failed';state.error=e.message;log('✗ '+e.message);state.finishedAt=new Date().toISOString()});
    return;
  }
  if(req.url==='/api/reset'&&req.method==='POST'){state={running:false,status:'idle',message:'Ready',lines:[],startedAt:null,finishedAt:null,resultFile:null,error:null};return json(res,{ok:true})}
  json(res,{error:'Not found'},404);
});
server.listen(PORT,'127.0.0.1',()=>console.log(`BPS local controller listening on http://127.0.0.1:${PORT}`));