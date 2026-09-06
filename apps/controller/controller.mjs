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
  res.writeHead(code,{'Content-Type':'application/json','Access-Control-Allow-Origin':'http://localhost:5173','Cache-Control':'no-store'});res.end(JSON.stringify(obj));
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

async function doScan(cfg){
  const host=process.env.BPS_EC2_HOST || cfg.host || '13.223.163.39';
  const user=cfg.user || 'ec2-user';
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

  state.status='connecting';state.message='Testing SSH connection';
  await run('ssh',['-o','ConnectTimeout=12','-o','StrictHostKeyChecking=accept-new','-i',key,`${user}@${host}`,'echo BPS_SSH_OK']);
  log('✓ SSH connection');

  state.status='uploading';state.message='Uploading scan configuration';
  await run('scp',['-q','-o','ConnectTimeout=12','-i',key,configFile,`${user}@${host}:${remoteDir}/scan_config.json`]);
  log('✓ Scan configuration uploaded');

  if(cfg.sessionToken?.trim()){
    const tokenFile=path.join(__dirname,'public','.bps_session_token.tmp');
    fs.writeFileSync(tokenFile,cfg.sessionToken.trim(),'utf8');
    try{
      await run('scp',['-q','-o','ConnectTimeout=12','-i',key,tokenFile,`${user}@${host}:/tmp/bps_session_token`]);
      log('✓ Session token uploaded for this run');
    } finally { try{fs.unlinkSync(tokenFile)}catch{} }
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
  if(req.method==='OPTIONS'){res.writeHead(204,{'Access-Control-Allow-Origin':'http://localhost:5173','Access-Control-Allow-Methods':'GET,POST,OPTIONS','Access-Control-Allow-Headers':'Content-Type'});return res.end()}
  if(req.url?.startsWith('/api/results/')&&req.method==='GET'){
    const fileName=decodeURIComponent(req.url.slice('/api/results/'.length).split('?')[0]);
    if(!fileName||path.basename(fileName)!==fileName||!fileName.endsWith('.csv'))return json(res,{error:'Invalid result file'},400);
    const filePath=path.join(PUBLIC,fileName);
    if(!fs.existsSync(filePath))return json(res,{error:'Result file not found'},404);
    res.writeHead(200,{'Content-Type':'text/csv; charset=utf-8','Access-Control-Allow-Origin':'http://localhost:5173','Cache-Control':'no-store'});
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
