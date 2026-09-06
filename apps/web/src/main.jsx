import React,{useEffect,useMemo,useState}from"react";
import{createRoot}from"react-dom/client";
import Papa from"papaparse";
import{ResponsiveContainer,BarChart,Bar,XAxis,YAxis,Tooltip,CartesianGrid,PieChart,Pie,Cell,Legend,ScatterChart,Scatter,ZAxis,ReferenceLine}from"recharts";
import"./styles.css";

const num=v=>{const n=Number(String(v??"").replace(/[₹,%\s,]/g,""));return Number.isFinite(n)?n:0};
const money=n=>"₹"+Number(n||0).toLocaleString("en-IN",{maximumFractionDigits:2});
const amount=n=>Number(n||0).toLocaleString("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2});
const integer=n=>Number(n||0).toLocaleString("en-IN",{maximumFractionDigits:0});

const normalize=rows=>rows.map((r,i)=>{
const c={};Object.keys(r).forEach(k=>{c[String(k).trim().toLowerCase()]=r[k]});
return{
RK:num(c.rank??c.rk)||i+1,
STOCK:String(c.stock??"").trim().toUpperCase(),
EXPIRY:String(c.expiry??"").trim(),
SPOT:num(c.spot),
SELL:num(c.sell_strike??c.sell),
BUY:num(c.buy_strike??c.buy),
SELL_IV:num(c.sell_iv),
BUY_IV:num(c.buy_iv),
SELL_PE_BID:num(c.sell_pe_bid??c.sell_bid),
SELL_PE_OFFER:num(c.sell_pe_offer??c.sell_offer),
BUY_PE_BID:num(c.buy_pe_bid??c.buy_bid),
BUY_PE_OFFER:num(c.buy_pe_offer??c.buy_offer),
"OTM%":num(c.otm_percent??c["otm%"]),
"OTM PTS":num(c.otm_points??c["otm pts"]),
WIDTH:num(c.width),
CREDIT:num(c.credit),
LOT:num(c.lot_size??c.lot)||1,
"PROFIT/LOT":num(c.profit_per_lot??c["profit/lot"]),
"LOSS/LOT":num(c.loss_per_lot??c["loss/lot"]),
BREAKEVEN:num(c.breakeven),
"P:L":num(c.profit_to_loss??c["p:l"]),
"IV SPREAD":num(c.sell_iv)-num(c.buy_iv),
"IV RATIO":num(c.buy_iv)>0?num(c.sell_iv)/num(c.buy_iv):0
}}).filter(r=>r.STOCK);
function score(r,minOtm,maxOtm,maxWidth,minPL,maxPL){
const otm=Math.max(0,Math.min(1,(r["OTM%"]-minOtm)/Math.max(.1,maxOtm-minOtm)));
const pl=1-Math.max(0,Math.min(1,(r["P:L"]-minPL)/Math.max(.1,maxPL-minPL)));
const width=Math.max(0,1-Math.min(1,r.WIDTH/Math.max(1,maxWidth)));
const credit=Math.max(0,Math.min(1,r.CREDIT/Math.max(1,r.SPOT*.01)));
const ivSpread=Math.max(0,Math.min(1,r["IV SPREAD"]/10));
return Math.round(100*(.30*otm+.28*pl+.18*width+.14*credit+.10*ivSpread));
}
const grade=s=>s>=82?"A+":s>=72?"A":s>=62?"B":s>=52?"C":"D";
const gradeClass=g=>g==="A+"?"Aplus":g;
const dateInputValue=date=>{const year=date.getFullYear(),month=String(date.getMonth()+1).padStart(2,"0"),day=String(date.getDate()).padStart(2,"0");return `${year}-${month}-${day}`};
const todayDate=new Date();
const minExpiry=dateInputValue(todayDate);
const maxExpiry=dateInputValue(new Date(todayDate.getFullYear(),todayDate.getMonth()+3,todayDate.getDate()));

function App(){
const[rows,setRows]=useState([]),[fileName,setFileName]=useState(""),[minOtm,setMinOtm]=useState(3),[maxOtm,setMaxOtm]=useState(8),[maxWidth,setMaxWidth]=useState(200),[minPL,setMinPL]=useState(3),[maxPL,setMaxPL]=useState(5),[minIvSpread,setMinIvSpread]=useState(-10),[maxIvSpread,setMaxIvSpread]=useState(10),[topN,setTopN]=useState(10),[sortBy,setSortBy]=useState("SCORE"),[view,setView]=useState("all"),[search,setSearch]=useState(""),[selected,setSelected]=useState(null),[drilldown,setDrilldown]=useState(null),[page,setPage]=useState(1),[pageSize,setPageSize]=useState(25),[loadingDemo,setLoadingDemo]=useState(false),[gradeFilter,setGradeFilter]=useState(["A+","A","B","C","D"]),[gradeOpen,setGradeOpen]=useState(false),[applied,setApplied]=useState({minOtm:3,maxOtm:8,maxWidth:200,minPL:3,maxPL:5,minIvSpread:-10,maxIvSpread:10,grades:["A+","A","B","C","D"],search:""}),[scenario,setScenario]=useState(null),[controller,setController]=useState({running:false,status:"idle",message:"Ready",lines:[],error:null}),[runCfg,setRunCfg]=useState({host:"13.223.163.39",user:"ec2-user",keyPath:"keys\\bps-scanner-key.pem",remoteDir:"/home/ec2-user/bps-scanner",sessionToken:"",expiry:"",minOI:100000,minVolume:100000}),[runPanel,setRunPanel]=useState(true),[lastRunConfig,setLastRunConfig]=useState(()=>{try{return JSON.parse(localStorage.getItem("bps-last-run-config")||"null")}catch{return null}}),[logTimes,setLogTimes]=useState([]),[completeFilters,setCompleteFilters]=useState({});

const DEFAULT_FILTERS={minOtm:3,maxOtm:8,maxWidth:200,minPL:3,maxPL:5,minIvSpread:-10,maxIvSpread:10,grades:["A+","A","B","C","D"],search:""};
const load=(data,name,scanConfig=null)=>{
  const parsed=normalize(data);
  const cfg=scanConfig||null;
  setRows(parsed);
  setFileName(name);
  setSelected(null);
  setScenario(null);
  if(cfg){
    setMinOtm(num(cfg.minOtm));
    setMaxOtm(num(cfg.maxOtm));
    setMaxWidth(num(cfg.maxWidth));
    setMinPL(num(cfg.minPL));
    setMaxPL(num(cfg.maxPL));
    setApplied(a=>({...a,minOtm:num(cfg.minOtm),maxOtm:num(cfg.maxOtm),maxWidth:num(cfg.maxWidth),minPL:num(cfg.minPL),maxPL:num(cfg.maxPL)}));
  }else{
    setMinOtm(DEFAULT_FILTERS.minOtm);
    setMaxOtm(DEFAULT_FILTERS.maxOtm);
    setMaxWidth(DEFAULT_FILTERS.maxWidth);
    setMinPL(DEFAULT_FILTERS.minPL);
    setMaxPL(DEFAULT_FILTERS.maxPL);
    setApplied({...DEFAULT_FILTERS,grades:[...DEFAULT_FILTERS.grades]});
  }
  setSearch("");
  setGradeFilter([...DEFAULT_FILTERS.grades]);
  setView("all");
  setPage(1);
};
const handleFile=e=>{const f=e.target.files?.[0];if(f)Papa.parse(f,{header:true,skipEmptyLines:true,complete:r=>load(r.data,f.name)})};
const loadDemo=async()=>{setLoadingDemo(true);try{const text=await fetch("/sample_bps_results.csv").then(r=>r.text());Papa.parse(text,{header:true,skipEmptyLines:true,complete:r=>{load(r.data,"Demo · current scanner CSV");setLoadingDemo(false)}})}catch(e){setLoadingDemo(false)}};
const scored=useMemo(()=>rows.map(r=>{const s=score(r,applied.minOtm,applied.maxOtm,applied.maxWidth,applied.minPL,applied.maxPL);return Object.assign({},r,{SCORE:s})}),[rows,applied.minOtm,applied.maxOtm,applied.maxWidth,applied.minPL,applied.maxPL]);
const matching=useMemo(()=>scored.filter(r=>r.STOCK.toLowerCase().includes(applied.search.toLowerCase())),[scored,applied.search]);

// Base screening is evaluated first. Grade filtering must NOT participate here,
// because grades are recalculated for the current screening universe below.
const screened=useMemo(()=>matching.filter(r=>r["OTM%"]>=applied.minOtm&&r["OTM%"]<=applied.maxOtm&&r.WIDTH<=applied.maxWidth&&r["P:L"]>=applied.minPL&&r["P:L"]<=applied.maxPL&&r["IV SPREAD"]>=applied.minIvSpread&&r["IV SPREAD"]<=applied.maxIvSpread),[matching,applied.minOtm,applied.maxOtm,applied.maxWidth,applied.minPL,applied.maxPL,applied.minIvSpread,applied.maxIvSpread]);

// Rank the CURRENT screening universe first. The ranking therefore changes
// when OTM / width / P:L criteria change.
const rankedBase=useMemo(()=>[...screened].sort((a,b)=>{
if(sortBy==="PROFIT/LOT")return b["PROFIT/LOT"]-a["PROFIT/LOT"];
if(sortBy==="P:L")return a["P:L"]-b["P:L"];
if(sortBy==="OTM%")return b["OTM%"]-a["OTM%"];
if(sortBy==="WIDTH")return a.WIDTH-b.WIDTH;
if(sortBy==="IV SPREAD")return b["IV SPREAD"]-a["IV SPREAD"];
return b.SCORE-a.SCORE;
}),[screened,sortBy]);

// Grades are relative to the CURRENT selected criteria, not fixed absolute
// score cut-offs. This prevents a new scan universe from making every valid
// candidate appear as D.
const ranked=useMemo(()=>{
const total=rankedBase.length;
return rankedBase.map((r,index)=>{
const p=total?((index+1)/total):1;
const g=p<=.10?"A+":p<=.30?"A":p<=.60?"B":p<=.85?"C":"D";
return Object.assign({},r,{GRADE:g});
});
},[rankedBase]);

// Grade selection is applied only after the current universe has been scored,
// ranked and graded.
const qualified=useMemo(()=>ranked.filter(r=>applied.grades.includes(r.GRADE)),[ranked,applied.grades]);

const best=qualified.slice(0,topN);
const allRows=useMemo(()=>[...matching].sort((a,b)=>a.RK-b.RK),[matching]);
const completeColumns=[
{key:"RK",label:"RK",group:"identity",value:r=>r.RK},
{key:"STOCK",label:"STOCK",group:"identity",value:r=>r.STOCK},{key:"EXPIRY",label:"EXPIRY",group:"identity",value:r=>r.EXPIRY||""},
{key:"SPOT",label:"SPOT",group:"market",value:r=>r.SPOT},{key:"SELL",label:"SELL",group:"strikes",value:r=>r.SELL},{key:"BUY",label:"BUY",group:"strikes",value:r=>r.BUY},
{key:"SELL_IV",label:"SELL IV",group:"iv",value:r=>r.SELL_IV},{key:"BUY_IV",label:"BUY IV",group:"iv",value:r=>r.BUY_IV},{key:"IV SPREAD",label:"IV SPREAD",group:"iv",value:r=>r["IV SPREAD"]},{key:"IV RATIO",label:"IV RATIO",group:"iv",value:r=>r["IV RATIO"]},
{key:"SELL_PE_BID",label:"SELL BID",group:"quotes",value:r=>r.SELL_PE_BID},{key:"SELL_PE_OFFER",label:"SELL OFFER",group:"quotes",value:r=>r.SELL_PE_OFFER},{key:"BUY_PE_BID",label:"BUY BID",group:"quotes",value:r=>r.BUY_PE_BID},{key:"BUY_PE_OFFER",label:"BUY OFFER",group:"quotes",value:r=>r.BUY_PE_OFFER},
{key:"OTM%",label:"OTM%",group:"metrics",value:r=>r["OTM%"]},{key:"OTM PTS",label:"OTM PTS",group:"metrics",value:r=>r["OTM PTS"]},{key:"WIDTH",label:"WIDTH",group:"metrics",value:r=>r.WIDTH},
{key:"CREDIT",label:"CREDIT",group:"economics",value:r=>r.CREDIT},{key:"LOT",label:"LOT",group:"economics",value:r=>r.LOT},{key:"PROFIT/LOT",label:"PROFIT/LOT",group:"economics",value:r=>r["PROFIT/LOT"]},
{key:"LOSS/LOT",label:"LOSS/LOT",group:"risk",value:r=>r["LOSS/LOT"]},{key:"BREAKEVEN",label:"BREAKEVEN",group:"risk",value:r=>r.BREAKEVEN},{key:"P:L",label:"P:L",group:"risk",value:r=>r["P:L"]},
{key:"GRADE",label:"GRADE",group:"dashboard",value:r=>r.GRADE},{key:"SCORE",label:"SCORE",group:"dashboard",value:r=>r.SCORE}
];
const filterMatch=(value,query)=>{const q=String(query??"").trim().toLowerCase();if(!q)return true;const raw=String(value??"").replace(/,/g,"").replace(/₹/g,"").replace(/%/g,"").trim();const m=q.match(/^(>=|<=|>|<|=)\s*(-?\d+(?:\.\d+)?)$/);if(m){const n=Number(raw),v=Number(m[2]);if(!Number.isFinite(n))return false;if(m[1]===">=")return n>=v;if(m[1]==="<=")return n<=v;if(m[1]===">")return n>v;if(m[1]==="<")return n<v;return n===v}return raw.toLowerCase().includes(q)};
const completeFiltered=useMemo(()=>allRows.filter(r=>completeColumns.every(c=>filterMatch(c.value(r),completeFilters[c.key]))),[allRows,completeFilters]);
const displayed=view==="best"?best:completeFiltered;
const totalPages=Math.max(1,Math.ceil(displayed.length/pageSize));
const safePage=Math.min(page,totalPages);
const paged=view==="best"?displayed:displayed.slice((safePage-1)*pageSize,safePage*pageSize);
const stats=useMemo(()=>({all:rows.length,q:qualified.length,screened:screened.length,stocks:new Set(qualified.map(r=>r.STOCK)).size,bestProfit:qualified.length?Math.max(...qualified.map(r=>r["PROFIT/LOT"])):0,avgPL:qualified.length?qualified.reduce((s,r)=>s+r["P:L"],0)/qualified.length:0,avgScore:qualified.length?qualified.reduce((s,r)=>s+r.SCORE,0)/qualified.length:0}),[rows,qualified,screened]);

const plData=useMemo(()=>{
  const lo=num(applied.minPL),hi=num(applied.maxPL);
  const span=Math.max(0.0001,hi-lo);
  const step=span/4;
  const fmt=v=>Number(v).toFixed(2).replace(/\.00$/,"").replace(/(\.\d)0$/,"$1");
  return Array.from({length:4},(_,i)=>{
    const a=lo+i*step;
    const b=i===3?hi:lo+(i+1)*step;
    const count=qualified.filter(r=>{
      const p=num(r["P:L"]);
      return i===3?p>=a&&p<=b:p>=a&&p<b;
    }).length;
    return {name:`${fmt(a)}–${fmt(b)}`,count,rows:qualified.filter(r=>{const p=num(r["P:L"]);return i===3?p>=a&&p<=b:p>=a&&p<b})};
  });
},[qualified,applied.minPL,applied.maxPL]);
// Lower P:L means less loss relative to profit, so the lower band is stronger.
const plColors=["#22c55e","#14b8a6","#f59e0b","#ef4444"];

const widthData=useMemo(()=>[
{name:"0–25",rows:qualified.filter(r=>r.WIDTH<=25)},
{name:"26–50",rows:qualified.filter(r=>r.WIDTH>25&&r.WIDTH<=50)},
{name:"51–100",rows:qualified.filter(r=>r.WIDTH>50&&r.WIDTH<=100)},
{name:"101–150",rows:qualified.filter(r=>r.WIDTH>100&&r.WIDTH<=150)},
{name:"151–200",rows:qualified.filter(r=>r.WIDTH>150)}
].map(x=>({...x,count:x.rows.length})),[qualified]);

const stockData=useMemo(()=>{const m=new Map();qualified.forEach(r=>{const x=m.get(r.STOCK);if(!x||num(r["PROFIT/LOT"])>num(x.best)){m.set(r.STOCK,{STOCK:r.STOCK,best:num(r["PROFIT/LOT"]),row:r})}});return[...m.values()].sort((a,b)=>b.best-a.best).slice(0,20)},[qualified]);

const applyFilters=()=>{setApplied({minOtm,maxOtm,maxWidth,minPL,maxPL,minIvSpread,maxIvSpread,grades:[...gradeFilter],search});setView("best");setPage(1);setGradeOpen(false)};
const resetScreen=()=>{const grades=["A+","A","B","C","D"];setMinOtm(3);setMaxOtm(8);setMaxWidth(200);setMinPL(3);setMaxPL(5);setMinIvSpread(-10);setMaxIvSpread(10);setSearch("");setGradeFilter(grades);setApplied({minOtm:3,maxOtm:8,maxWidth:200,minPL:3,maxPL:5,minIvSpread:-10,maxIvSpread:10,grades,search:""});setView("best");setPage(1);setGradeOpen(false)};
const openStrategy=r=>{setSelected(r);setScenario({lots:1,spot:r.SPOT,sellStrike:r.SELL,buyStrike:r.BUY,lotSize:r.LOT,sellBid:r.SELL_PE_BID,sellOffer:r.SELL_PE_OFFER,buyBid:r.BUY_PE_BID,buyOffer:r.BUY_PE_OFFER,sellPrice:r.SELL_PE_BID||0,buyPrice:r.BUY_PE_OFFER||0})};
const openDrilldown=(title,items)=>setDrilldown({title,rows:items});
const drillPL=(index)=>openDrilldown("P:L "+plData[index].name,plData[index].rows);
const drillWidth=(index)=>openDrilldown("Spread width "+widthData[index].name,widthData[index].rows);
const updateScenario=(key,value)=>setScenario(s=>({...s,[key]:value}));
const calc=useMemo(()=>{if(!selected||!scenario)return null;const lots=Math.max(1,num(scenario.lots)),spot=num(scenario.spot),sellStrike=num(scenario.sellStrike),buyStrike=num(scenario.buyStrike),lotSize=Math.max(1,num(scenario.lotSize)),sellPrice=num(scenario.sellPrice),buyPrice=num(scenario.buyPrice);const credit=sellPrice-buyPrice,width=sellStrike-buyStrike,quantity=lotSize*lots,maxProfit=credit*quantity,maxLoss=(width-credit)*quantity,breakeven=sellStrike-credit,otmPts=spot-sellStrike,otm=spot>0?(otmPts/spot)*100:0,pl=maxProfit>0?maxLoss/maxProfit:0;return{lots,spot,sellStrike,buyStrike,lotSize,sellPrice,buyPrice,credit,width,maxProfit,maxLoss,breakeven,otm,otmPts,pl,quantity};},[selected,scenario]);
const setRun=(k,v)=>setRunCfg(x=>({...x,[k]:v}));
useEffect(()=>{
  const expiry=document.getElementById("expiry-date-field");
  const session=document.querySelector('input[placeholder="Paste fresh Breeze session token"]');
  if(expiry&&session?.parentElement)session.parentElement.after(expiry);
},[]);

const syncController=(x)=>{
  setController(x);
  if(Array.isArray(x.lines)){
    setLogTimes(prev=>{
      const next=[...prev];
      x.lines.forEach((_,i)=>{if(!next[i])next[i]=new Date().toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit",second:"2-digit"})});
      return next.slice(0,x.lines.length);
    });
  }
};

const loadLatestResults=(scanConfig=null,resultFile="latest_bps_results.csv")=>{
  fetch(`http://127.0.0.1:8787/api/results/${encodeURIComponent(resultFile)}?ts=${Date.now()}`)
    .then(r=>{if(!r.ok)throw new Error(`Result file could not be loaded (${r.status})`);return r.text()})
    .then(t=>Papa.parse(t,{
      header:true,
      skipEmptyLines:true,
      complete:r=>load(r.data,"EC2 Scan · "+new Date().toLocaleString("en-IN"),scanConfig)
    }))
    .catch(e=>syncController({...controller,status:"error",message:`Scan complete, but results could not be loaded: ${e.message}`,error:e.message}));
};

const pollController=()=>{
  fetch("http://127.0.0.1:8787/api/status")
    .then(r=>r.json())
    .then(x=>{
      syncController(x);
      if(x.status==="complete"&&x.resultFile)loadLatestResults(lastRunConfig,x.resultFile);
    })
    .catch(()=>syncController({...controller,status:"offline",message:"Local controller not running"}));
};

useEffect(()=>{
  pollController();
},[]);

const runScan=async()=>{
  try{
    const scanConfig={
      minOtm:num(minOtm),
      maxOtm:num(maxOtm),
      maxWidth:num(maxWidth),
      minPL:num(minPL),
      maxPL:num(maxPL),
      expiry:runCfg.expiry,
      minOI:num(runCfg.minOI),
      minVolume:num(runCfg.minVolume)
    };
    const payload={...runCfg,...scanConfig};
    setLastRunConfig(scanConfig);
    try{localStorage.setItem("bps-last-run-config",JSON.stringify(scanConfig))}catch{}
    setApplied(a=>({...a,...scanConfig}));
    setLogTimes([]);
    const r=await fetch("http://127.0.0.1:8787/api/run",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify(payload)
    });
    if(!r.ok)throw new Error((await r.json()).error||"Unable to start scan");
    const startedAt=new Date().toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit",second:"2-digit"});
    setController(x=>({...x,running:true,status:"starting",message:`Starting scan · ${startedAt}`,lines:[]}));
    const timer=setInterval(async()=>{
      try{
        const q=await fetch("http://127.0.0.1:8787/api/status").then(r=>r.json());
        syncController(q);
        if(!q.running){
          clearInterval(timer);
          if(q.status==="complete"&&q.resultFile)loadLatestResults(scanConfig,q.resultFile);
        }
      }catch(e){
        clearInterval(timer);
        syncController({running:false,status:"error",message:e.message,lines:[],error:e.message});
      }
    },1200);
  }catch(e){
    syncController({running:false,status:"error",message:e.message,lines:[],error:e.message});
  }
};


return <div className="app">
<header className="topbar">
<div className="brand"><div className="eyebrow">BULL PUT SPREAD · TRADING ANALYTICS</div><h1>BPS Strategy Dashboard</h1><p>Scan the complete universe. Isolate the best risk/reward setups.</p></div>
<div className="actions"><label className="upload"><input type="file" accept=".csv" onChange={handleFile}/><span>＋ Load CSV</span></label><button onClick={loadDemo}>{loadingDemo?"Loading…":"Demo · 176"}</button>{rows.length>0&&<button onClick={()=>{setRows([]);setFileName("");setSelected(null)}}>Clear</button>}</div>
</header>

<section className="runPanel">
{runPanel&&<div id="expiry-date-field" className="runExpiry"><label className="runExpiryField">Expiry Date<input type="date" min={minExpiry} max={maxExpiry} value={runCfg.expiry} onChange={e=>setRun("expiry",e.target.value)}/><small>Today through the next 3 months.</small></label></div>}
<div className="runHead"><div><span className="pill">⚙ EC2 SCAN CONTROL</span><h2>Configure & run scanner</h2><p>Set execution/screening rules here before the EC2 scan. These values are written to scan_config.json and uploaded to EC2 before every scan.</p></div><button className="collapse" onClick={()=>setRunPanel(!runPanel)}>{runPanel?"Hide":"Show"}</button></div>
{runPanel&&<><div className="runGrid"><label>EC2 Public IP<input value={runCfg.host} onChange={e=>setRun("host",e.target.value)}/></label><label>SSH User<input value={runCfg.user} onChange={e=>setRun("user",e.target.value)}/></label><label>SSH Key<input value={runCfg.keyPath} onChange={e=>setRun("keyPath",e.target.value)}/></label><label>Remote folder<input value={runCfg.remoteDir} onChange={e=>setRun("remoteDir",e.target.value)}/></label><label>Session token<input type="password" placeholder="Paste fresh Breeze session token" value={runCfg.sessionToken} onChange={e=>setRun("sessionToken",e.target.value)}/><small>Only sent to EC2 for this scan; not stored by React.</small></label><label>OTM min<input type="number" step=".1" value={minOtm} onChange={e=>setMinOtm(num(e.target.value))}/>%</label><label>OTM max<input type="number" step=".1" value={maxOtm} onChange={e=>setMaxOtm(num(e.target.value))}/>%</label><label>Max spread width<input type="number" value={maxWidth} onChange={e=>setMaxWidth(num(e.target.value))}/>₹</label><label>Min P:L<input type="number" step=".1" value={minPL} onChange={e=>setMinPL(num(e.target.value))}/></label><label>Max P:L<input type="number" step=".1" value={maxPL} onChange={e=>setMaxPL(num(e.target.value))}/></label><label>Min OI<input type="number" value={runCfg.minOI} onChange={e=>setRun("minOI",num(e.target.value))}/></label><label>Min volume<input type="number" value={runCfg.minVolume} onChange={e=>setRun("minVolume",num(e.target.value))}/></label><div className="runRules"><b>Scan configuration</b><span>OTM {minOtm}–{maxOtm}% · Width ≤ ₹{maxWidth} · P:L 1:{minPL}–1:{maxPL} · OI ≥ {integer(runCfg.minOI)} · Volume ≥ {integer(runCfg.minVolume)}</span></div></div><div className="runActions"><button className="runBtn" disabled={controller.running} onClick={runScan}>{controller.running?"⏳ Running…":"🚀 Run EC2 Scan"}</button><button className="testBtn" onClick={pollController}>↻ Refresh status</button><span className={"controllerStatus "+(controller.status==="complete"?"ok":controller.status==="error"?"bad":"")}>● {controller.message}</span></div><div className="runLog" style={{maxHeight:260,overflowY:"auto",overflowX:"auto",fontFamily:"ui-monospace,SFMono-Regular,Menlo,monospace"}}>
{controller.lines?.map((x,i)=><div key={i} style={{display:"flex",gap:10,whiteSpace:"pre",lineHeight:1.45}}>
  <span style={{color:"#7f93ad",minWidth:70,userSelect:"none"}}>{logTimes[i]||"—"}</span>
  <span>{x}</span>
</div>)}
{!controller.lines?.length&&<div style={{color:"#7f93ad"}}>No scanner log received yet.</div>}
</div></>}
</section>

{!rows.length?<section className="empty"><div className="dropIcon">CSV</div><h2>Load your scanner results</h2><p>Use the current <code>bps_results.csv</code>. All analysis runs locally in your browser.</p><label className="upload primary"><input type="file" accept=".csv" onChange={handleFile}/><span>Choose CSV</span></label><button className="text" onClick={loadDemo}>Load 176-row demo dataset</button></section>:
<>
<div className="fileBar"><span>● <b>{fileName}</b> · <b>{stats.all}</b> strategies loaded</span><span><b>{stats.q}</b> qualified · <b>{stats.all-stats.q}</b> outside · <b>{applied.grades.length}/5</b> grades active · OTM {applied.minOtm}–{applied.maxOtm}% · P:L {applied.minPL}–{applied.maxPL} · IV spread {applied.minIvSpread}–{applied.maxIvSpread}%</span></div>

<section className="filters">
<div className="filterTitle">BEST-PICK SCREEN <span>Set criteria, then apply</span></div>
<label>OTM min <input type="number" step=".1" value={minOtm} onChange={e=>{setMinOtm(num(e.target.value));setPage(1)}}/>%</label>
<label>OTM max <input type="number" step=".1" value={maxOtm} onChange={e=>{setMaxOtm(num(e.target.value));setPage(1)}}/>%</label>
<label>Max width <input type="number" value={maxWidth} onChange={e=>{setMaxWidth(num(e.target.value));setPage(1)}}/>₹</label><label>P:L min <input type="number" step=".1" value={minPL} onChange={e=>setMinPL(num(e.target.value))}/></label><label>P:L max <input type="number" step=".1" value={maxPL} onChange={e=>setMaxPL(num(e.target.value))}/></label><label>IV spread min <input type="number" step=".1" value={minIvSpread} onChange={e=>setMinIvSpread(num(e.target.value))}/>%</label><label>IV spread max <input type="number" step=".1" value={maxIvSpread} onChange={e=>setMaxIvSpread(num(e.target.value))}/>%</label>
<div className="gradeFilterWrap"><span className="fieldLabel">Grade</span><button className="gradeSelect" onClick={()=>setGradeOpen(!gradeOpen)}>{gradeFilter.length===5?"All Grades":gradeFilter.length+" selected"} <span>⌄</span></button>{gradeOpen&&<div className="gradeMenu" onClick={e=>e.stopPropagation()}>{["A+","A","B","C","D"].map(g=><label key={g}><input type="checkbox" checked={gradeFilter.includes(g)} onChange={()=>setGradeFilter(x=>x.includes(g)?x.filter(v=>v!==g):[...x,g])}/><Grade g={g}/><span>{g==="A+"?"Exceptional":g==="A"?"Strong":g==="B"?"Good":g==="C"?"Watch":"Weak"}</span></label>)}<div className="gradeActions"><button className="selectAll" onClick={()=>setGradeFilter(["A+","A","B","C","D"])}>Select all</button><button className="deselectAll" onClick={()=>setGradeFilter([])}>Deselect all</button></div><div className="pendingNote">Selection changes apply when you click Apply Filters.</div></div>}</div>
<label>Search <input className="search" placeholder="Stock..." value={search} onChange={e=>setSearch(e.target.value)}/></label>
<label>Best picks <select value={topN} onChange={e=>setTopN(num(e.target.value))}><option value="5">Top 5</option><option value="10">Top 10</option><option value="15">Top 15</option><option value="25">Top 25</option></select></label>
<label>Rank by <select value={sortBy} onChange={e=>setSortBy(e.target.value)}><option value="SCORE">Opportunity score</option><option value="PROFIT/LOT">Profit / lot</option><option value="P:L">P:L</option><option value="OTM%">Far OTM</option><option value="WIDTH">Narrow width</option><option value="IV SPREAD">IV spread</option></select></label>
<button className="apply" onClick={applyFilters}>✓ Apply Filters</button><button className="reset" onClick={resetScreen}>Reset</button>
</section>

<section className="cards">
<Metric title="CSV UNIVERSE" value={stats.all} sub="all loaded strategies"/>
<Metric title="QUALIFIED" value={stats.q} sub={stats.stocks+" stocks · "+stats.screened+" pass base rules"} tone="green"/>
<Metric title="BEST PROFIT / LOT" value={money(stats.bestProfit)} sub="maximum filtered profit" tone="green"/>
<Metric title="AVERAGE P:L" value={"1:"+stats.avgPL.toFixed(2)} sub={"avg opportunity score "+stats.avgScore.toFixed(0)} tone="amber"/>
</section>

<section className="hero">
<div><span className="pill">⚡ LIVE SCREENING LOGIC</span><h2>Opportunity ranking</h2><p>Score = OTM 30% + P:L 28% + width 18% + credit/spot 14% + IV spread 10%. Grades are relative to the currently selected scan criteria. Use this as a shortlist, not as a trade signal.</p></div>
<div className="heroStats"><div><b>{best.length}</b><span>best picks</span></div><div><b>{stats.all}</b><span>strategies</span></div><div><b>{stats.q?Math.round(stats.q/stats.all*100):0}%</b><span>pass rate</span></div></div>
</section>

<div className="colorLegend"><span><i className="dot aplus"></i>A+ Exceptional</span><span><i className="dot a"></i>A Strong</span><span><i className="dot b"></i>B Good</span><span><i className="dot c"></i>C Watch</span><span><i className="dot d"></i>D Weak</span><span className="legendNote">Row tint = opportunity grade</span></div>

<section className="panel">
<div className="tabs"><button className={view==="best"?"active":""} onClick={()=>{setView("best");setPage(1)}}>⭐ Best Picks <span className="tabCount">{best.length}</span></button><button className={view==="all"?"active":""} onClick={()=>{setView("all");setPage(1)}}>☷ Complete CSV <span className="tabCount">{completeFiltered.length}</span></button><span className="hint">Complete CSV starts with every loaded strategy · column filters narrow this table · Apply Filters controls Best Picks</span></div>
<div className="table">
{view==="all"&&<div className="completeTableToolbar"><span><b>Complete CSV</b> · {completeFiltered.length} of {allRows.length} rows</span><button onClick={()=>setCompleteFilters({})}>Clear column filters</button><span className="filterHelp">Text = contains · numeric = exact or use &gt; / &lt; / &gt;= / &lt;=</span></div>}
<table className={view==="all"?"completeTable":""}>
<thead>
<tr>{(view==="all"?completeColumns.map(c=>c.label):["RANK","STOCK","GRADE","SPOT","SELL","BUY","SELL IV","BUY IV","IV SPREAD","IV RATIO","OTM","WIDTH","CREDIT","LOT","PROFIT/LOT","LOSS/LOT","BREAKEVEN","P:L"]).map((h,i)=><th key={h} className={view==="all"?`col-${completeColumns[i].group}`:""}>{h}</th>)}</tr>
{view==="all"&&<tr className="columnFilterRow">{completeColumns.map(c=><th key={c.key} className={`col-${c.group}`}><input aria-label={`Filter ${c.label}`} value={completeFilters[c.key]||""} onChange={e=>{setCompleteFilters(x=>({...x,[c.key]:e.target.value}));setPage(1)}} placeholder="Filter…"/></th>)}</tr>}
</thead>
<tbody>{paged.map((r,i)=><tr className={"clickable scoreRow "+gradeClass(r.GRADE)} onClick={()=>openStrategy(r)} key={r.STOCK+"-"+r.SELL+"-"+r.BUY+"-"+i}>
{view==="all"? <>
<td className="col-identity">{r.RK}</td><td className="stock col-identity">{r.STOCK}</td><td className="col-identity">{r.EXPIRY||"—"}</td><td className="col-market">{money(r.SPOT)}</td><td className="col-strikes">{integer(r.SELL)}</td><td className="col-strikes">{integer(r.BUY)}</td><td className="col-iv">{r.SELL_IV.toFixed(2)}%</td><td className="col-iv">{r.BUY_IV.toFixed(2)}%</td><td className="col-iv">{r["IV SPREAD"].toFixed(2)}%</td><td className="col-iv">{r["IV RATIO"].toFixed(3)}</td><td className="col-quotes">{money(r.SELL_PE_BID)}</td><td className="col-quotes">{money(r.SELL_PE_OFFER)}</td><td className="col-quotes">{money(r.BUY_PE_BID)}</td><td className="col-quotes">{money(r.BUY_PE_OFFER)}</td><td className="col-metrics">{r["OTM%"].toFixed(2)}%</td><td className="col-metrics">{r["OTM PTS"].toFixed(2)}</td><td className="col-metrics">{integer(r.WIDTH)}</td><td className="col-economics">{money(r.CREDIT)}</td><td className="col-economics">{integer(r.LOT)}</td><td className="profit col-economics">{money(r["PROFIT/LOT"])}</td><td className="loss col-risk">{money(r["LOSS/LOT"])}</td><td className="col-risk">{money(r.BREAKEVEN)}</td><td className="col-risk"><b>1:{r["P:L"].toFixed(2)}</b></td><td className="col-dashboard"><Grade g={r.GRADE}/></td><td className="col-dashboard"><b>{r.SCORE}</b></td>
</>:<><td><span className="rankBadge">{i+1}</span></td><td className="stock">{r.STOCK}</td><td><Grade g={r.GRADE}/></td><td>{money(r.SPOT)}</td><td>{integer(r.SELL)}</td><td>{integer(r.BUY)}</td><td>{r.SELL_IV.toFixed(2)}%</td><td>{r.BUY_IV.toFixed(2)}%</td><td>{r["IV SPREAD"].toFixed(2)}%</td><td>{r["IV RATIO"].toFixed(3)}</td><td>{r["OTM%"].toFixed(2)}%</td><td>{integer(r.WIDTH)}</td><td>{money(r.CREDIT)}</td><td>{integer(r.LOT)}</td><td className="profit">{money(r["PROFIT/LOT"])}</td><td className="loss">{money(r["LOSS/LOT"])}</td><td>{money(r.BREAKEVEN)}</td><td><b>1:{r["P:L"].toFixed(2)}</b></td></>}
</tr>)}</tbody></table></div>
{view==="all"&&<div className="pagination"><span>Showing <b>{displayed.length?((safePage-1)*pageSize+1):0}–{Math.min(safePage*pageSize,displayed.length)}</b> of <b>{displayed.length}</b></span><div><button disabled={safePage<=1} onClick={()=>setPage(safePage-1)}>← Prev</button><select value={pageSize} onChange={e=>{setPageSize(num(e.target.value));setPage(1)}}><option value="25">25 / page</option><option value="50">50 / page</option><option value="100">100 / page</option><option value="999999">All</option></select><button disabled={safePage>=totalPages} onClick={()=>setPage(safePage+1)}>Next →</button></div></div>}
</section>

<section className="charts">
<Chart title="Profit Stats (1 stock / 1 lot)" sub="Best qualified BPS setups · profit shown per single lot"><ResponsiveContainer><BarChart data={best} margin={{top:10,right:15,left:10,bottom:5}}><CartesianGrid strokeDasharray="3 3" stroke="#dbe4ef"/><XAxis dataKey="STOCK" interval={0} tick={{fontSize:9}} angle={-25} textAnchor="end" height={55}/><YAxis tickFormatter={integer}/><Tooltip contentStyle={{borderRadius:10,border:"1px solid #dbe4ef"}} formatter={(v)=>money(v)} labelFormatter={(label)=>{const r=best.find(x=>x.STOCK===label);return r?`${r.STOCK} · BPS ${integer(r.SELL)} / ${integer(r.BUY)}`:label}} content={({active,payload,label})=>{if(!active||!payload?.length)return null;const r=best.find(x=>x.STOCK===label);if(!r)return null;return <div style={{background:"#fff",border:"1px solid #dbe4ef",borderRadius:10,padding:"10px 12px",boxShadow:"0 8px 20px #17243a18"}}><div style={{fontWeight:900,color:"#17243a",marginBottom:4}}>{r.STOCK}</div><div style={{fontSize:12}}>Profit / lot: <b>{money(r["PROFIT/LOT"])}</b></div><div style={{fontSize:11,color:"#61758e",marginTop:3}}>BPS: SELL {integer(r.SELL)} PE / BUY {integer(r.BUY)} PE</div><div style={{fontSize:11,color:"#61758e",marginTop:2}}>Credit {money(r.CREDIT)} · Width {integer(r.WIDTH)} · OTM {r["OTM%"].toFixed(2)}%</div></div>}}/><Bar dataKey="PROFIT/LOT" name="Profit / lot" radius={[7,7,2,2]}>{best.map((r,i)=><Cell key={i} fill={r.GRADE==="A+"?"#16a34a":r.GRADE==="A"?"#0f766e":r.GRADE==="B"?"#2563eb":r.GRADE==="C"?"#f59e0b":"#ef4444"}/>)}</Bar></BarChart></ResponsiveContainer></Chart>
<Chart title="P:L distribution" sub="Green = stronger risk/reward · red = weaker risk/reward · click a band to drill down"><ResponsiveContainer><PieChart margin={{top:10,right:18,bottom:10,left:4}}><Pie data={plData} dataKey="count" nameKey="name" cx="62%" cy="48%" outerRadius={96} innerRadius={56} paddingAngle={3} label>{plData.map((_,i)=><Cell key={i} fill={plColors[i]} className="chartClickable" onClick={()=>drillPL(i)}/>)}</Pie><Tooltip/><Legend layout="vertical" align="left" verticalAlign="middle" wrapperStyle={{left:0,width:"28%",lineHeight:"24px"}}/></PieChart></ResponsiveContainer></Chart>
<Chart wide title="Best profit by stock" sub="Highest profit/lot among qualified stocks · each bar is the best BPS found for that stock"><ResponsiveContainer><BarChart data={stockData} layout="vertical" margin={{top:5,right:30,left:8,bottom:5}}><CartesianGrid strokeDasharray="3 3" stroke="#dbe4ef"/><XAxis type="number" tickFormatter={integer}/><YAxis type="category" dataKey="STOCK" width={135} interval={0} tick={<StockTick/>} tickLine={false} axisLine={false}/><Tooltip cursor={{fill:"#eef7f6"}} content={({active,payload,label})=>{if(!active||!payload?.length)return null;const item=stockData.find(x=>x.STOCK===label);const r=item?.row;if(!r)return null;return <div style={{background:"#fff",border:"1px solid #dbe4ef",borderRadius:10,padding:"10px 12px",boxShadow:"0 8px 20px #17243a18",minWidth:210}}><div style={{fontWeight:900,color:"#17243a",marginBottom:5}}>{r.STOCK}</div><div style={{fontSize:12}}>Profit / lot: <b style={{color:"#087f5b"}}>{money(r["PROFIT/LOT"])}</b></div><div style={{fontSize:11,color:"#61758e",marginTop:4}}>BPS: SELL {integer(r.SELL)} PE / BUY {integer(r.BUY)} PE</div><div style={{fontSize:11,color:"#61758e",marginTop:3}}>Credit {money(r.CREDIT)} · Width {integer(r.WIDTH)}</div><div style={{fontSize:11,color:"#61758e",marginTop:3}}>OTM {r["OTM%"].toFixed(2)}% · OTM pts {r["OTM PTS"].toFixed(2)}</div><div style={{fontSize:11,color:"#61758e",marginTop:3}}>P:L 1:{r["P:L"].toFixed(2)} · Grade {r.GRADE} · Score {r.SCORE}</div><div style={{fontSize:10,color:"#8a9aab",marginTop:6}}>Lot {integer(r.LOT)} · Expiry {r.EXPIRY||"—"}</div></div>}}/><Bar dataKey="best" name="Profit / lot" radius={[0,7,7,0]}>{stockData.map((x,i)=><Cell key={i} fill={x.row.GRADE==="A+"?"#16a34a":x.row.GRADE==="A"?"#0f766e":x.row.GRADE==="B"?"#2563eb":x.row.GRADE==="C"?"#f59e0b":"#ef4444"}/>)}</Bar></BarChart></ResponsiveContainer></Chart>
<Chart title="Spread width" sub="Green → amber → red as width/risk increases · click a band to drill down"><ResponsiveContainer><BarChart data={widthData}><CartesianGrid strokeDasharray="3 3" stroke="#dbe4ef"/><XAxis dataKey="name"/><YAxis allowDecimals={false}/><Tooltip/><Bar dataKey="count" name="Strategies" radius={[7,7,2,2]}>{widthData.map((_,i)=><Cell key={i} fill={["#22c55e","#f59e0b","#3b82f6","#ef4444","#991b1b"][i]} className="chartClickable" onClick={()=>drillWidth(i)}/>)}</Bar></BarChart></ResponsiveContainer></Chart>
<Chart title="OTM vs profit" sub="Each dot is a qualified strategy · click a dot to open its scenario"><ResponsiveContainer><ScatterChart margin={{top:15,right:15,bottom:5,left:10}}><CartesianGrid stroke="#dbe4ef"/><XAxis type="number" dataKey="OTM%" name="OTM" unit="%"/><YAxis type="number" dataKey="PROFIT/LOT" name="Profit / lot" tickFormatter={integer}/><ZAxis range={[50,95]}/><Tooltip/><ReferenceLine x={applied.minOtm} stroke="#f59e0b" strokeDasharray="5 5"/><ReferenceLine x={applied.maxOtm} stroke="#ef4444" strokeDasharray="5 5"/>{["A+","A","B","C","D"].map(g=><Scatter key={g} name={g} data={qualified.filter(r=>r.GRADE===g)} fill={g==="A+"?"#16a34a":g==="A"?"#0f766e":g==="B"?"#2563eb":g==="C"?"#f59e0b":"#ef4444"} onClick={r=>openStrategy(r)} className="chartClickable" />)}</ScatterChart></ResponsiveContainer></Chart>
</section>
</>}

{drilldown&&<div className="overlay" onClick={()=>setDrilldown(null)}><aside className="drawer drilldownDrawer" onClick={e=>e.stopPropagation()}><div className="drawerTop"><div><span className="pill dark">CHART DRILL-DOWN</span><h2>{drilldown.title}</h2><p>{drilldown.rows.length} qualified strategies in this selection</p></div><button className="close" onClick={()=>setDrilldown(null)}>×</button></div><div className="drillLegend"><span><i className="profitDot"></i>MAX PROFIT / LOT</span><span><i className="lossDot"></i>MAX LOSS / LOT</span></div><div className="drillRows">{drilldown.rows.length?drilldown.rows.map((r,i)=><button key={r.STOCK+"-"+r.SELL+"-"+r.BUY+"-"+i} onClick={()=>{setDrilldown(null);openStrategy(r)}}><span><b>{r.STOCK}</b><small>SELL {integer(r.SELL)} / BUY {integer(r.BUY)} · OTM {r["OTM%"].toFixed(2)}% · WIDTH {integer(r.WIDTH)}</small></span><strong><em>{amount(r["PROFIT/LOT"])}</em><em>{amount(r["LOSS/LOT"])}</em></strong></button>):<p className="drillEmpty">No qualified strategies match this chart selection.</p>}</div></aside></div>}

{selected&&scenario&&<div className="overlay" onClick={()=>setSelected(null)}><aside className="drawer" onClick={e=>e.stopPropagation()}>
<div className="drawerTop"><div><span className="pill dark">LIVE BPS SCENARIO</span><h2>{selected.STOCK}</h2><p>Scanner rank #{selected.RK} · dashboard score {selected.SCORE}{selected.EXPIRY&&" · "+selected.EXPIRY}</p></div><button className="close" onClick={()=>setSelected(null)}>×</button></div>
<div className="gradeBig"><Grade g={selected.GRADE}/><strong>{selected.SCORE}</strong><span>Opportunity score</span></div>
<div className="scenarioSection"><div className="sectionTitle">WHAT-IF WORKBENCH <span>all execution inputs editable · derived values recalculate instantly</span></div><div className="scenarioInputs fullScenario"><label>Qty / Lots<input type="number" min="1" step="1" value={scenario.lots} onChange={e=>updateScenario("lots",e.target.value)}/><small>Total quantity: {integer(calc.quantity)}</small></label><label>Lot size<input type="number" min="1" step="1" value={scenario.lotSize} onChange={e=>updateScenario("lotSize",e.target.value)}/><small>Scanner: {integer(selected.LOT)}</small></label><label>Spot<input type="number" step=".05" value={scenario.spot} onChange={e=>updateScenario("spot",e.target.value)}/><small>Scanner: {money(selected.SPOT)}</small></label><label>Sell strike<input type="number" value={scenario.sellStrike} onChange={e=>updateScenario("sellStrike",e.target.value)}/><small>Scanner: {integer(selected.SELL)}</small></label><label>Buy strike<input type="number" value={scenario.buyStrike} onChange={e=>updateScenario("buyStrike",e.target.value)}/><small>Scanner: {integer(selected.BUY)}</small></label><label>Sell PE BID<input type="number" step=".01" value={scenario.sellBid} onChange={e=>{updateScenario("sellBid",e.target.value);updateScenario("sellPrice",e.target.value)}}/><small>Scanner: {money(selected.SELL_PE_BID)}</small></label><label>Sell PE OFFER<input type="number" step=".01" value={scenario.sellOffer} onChange={e=>updateScenario("sellOffer",e.target.value)}/><small>Scanner: {money(selected.SELL_PE_OFFER)}</small></label><label>Buy PE BID<input type="number" step=".01" value={scenario.buyBid} onChange={e=>updateScenario("buyBid",e.target.value)}/><small>Scanner: {money(selected.BUY_PE_BID)}</small></label><label>Buy PE OFFER<input type="number" step=".01" value={scenario.buyOffer} onChange={e=>{updateScenario("buyOffer",e.target.value);updateScenario("buyPrice",e.target.value)}}/><small>Scanner: {money(selected.BUY_PE_OFFER)}</small></label><label>Actual sell fill<input type="number" step=".01" value={scenario.sellPrice} onChange={e=>updateScenario("sellPrice",e.target.value)}/><small>Used for P/L calculation</small></label><label>Actual buy fill<input type="number" step=".01" value={scenario.buyPrice} onChange={e=>updateScenario("buyPrice",e.target.value)}/><small>Used for P/L calculation</small></label></div><button className="scenarioReset" onClick={()=>openStrategy(selected)}>↺ Reset to scanner values</button></div><div className="legs"><D k="SELL PUT" v={integer(calc.sellStrike)}/><D k="BUY PUT" v={integer(calc.buyStrike)}/><D k="WIDTH" v={money(calc.width)}/></div><div className="riskbar"><div><span>MAX PROFIT</span><b>{money(calc.maxProfit)}</b></div><div><span>MAX LOSS</span><b>{money(calc.maxLoss)}</b></div></div><div className="detailGrid"><D k="NET CREDIT" v={money(calc.credit)}/><D k="BREAKEVEN" v={money(calc.breakeven)}/><D k="OTM" v={calc.otm.toFixed(2)+"%"}/><D k="OTM PTS" v={calc.otmPts.toFixed(2)}/><D k="P:L" v={calc.pl>=0?"1:"+calc.pl.toFixed(2):"Invalid"}/><D k="TOTAL QTY" v={integer(calc.quantity)}/></div><div className="executionNote"><b>SCANNER VS WHAT-IF</b><span>Original CSV remains unchanged. This panel is temporary scenario analysis.</span><em>Default calculation uses SELL at bid and BUY at offer; actual fills can be overridden independently.</em></div><div className="why"><b>Live strategy analysis</b><p>Edit spot, strikes, bid/offer prices, actual fills, lot size or number of lots. Width, credit, OTM, breakeven, max profit, max loss and P:L recalculate automatically.</p></div></aside></div>}
<footer>BPS Strategy Dashboard · local-only analytics · current scanner CSV schema supported</footer>
</div>
}
function Metric({title,value,sub,tone=""}){return <div className={"metric "+tone}><small>{title}</small><strong>{value}</strong><em>{sub}</em></div>}
function Grade({g}){return <span className={"grade g"+gradeClass(g)}>{g}</span>}
function D({k,v}){return <div className="d"><small>{k}</small><b>{v}</b></div>}
function StockTick({x,y,payload}){return <g transform={`translate(${x},${y})`}><text x={-8} y={0} dy="4" textAnchor="end" fontSize="9" fill="#61758e" style={{fontFamily:"inherit",whiteSpace:"nowrap"}}>{payload.value}</text></g>}
function Chart({title,sub,wide,children}){return <div className={"chart "+(wide?"wide":"")}><div className="head"><h2>{title}</h2><p>{sub}</p></div><div className="plot">{children}</div></div>}
createRoot(document.getElementById("root")).render(<App/>);
