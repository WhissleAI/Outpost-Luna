import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { chime, fadeTo, speak, stopSpeaking, isSpeaking, tts, ttsAvailable } from "./sound.js";
import { getMoments, deriveMoments, normMoment, sentenceEnds } from "./moments.js";
import { createListener } from "./listen.js";
import "./listen.css";

async function getJSON(url) { const r = await fetch(url); if (!r.ok) throw new Error(url + " " + r.status); return r.json(); }

(async () => {
const R = 1, MOON_KM = 1737.4;
let F = [], CL = [];
try {
  const [pl, cl] = await Promise.all([getJSON("/api/places"), getJSON("/api/clips")]);
  F = pl.places.map(p => ({ id: p.id, name: p.name, lat: p.lat, lon: p.lon, km: p.diameter_km, fact: p.fact, est: p.estimated, al: p.aliases }));
  CL = cl.clips;
} catch (e) {
  document.getElementById("loading").textContent = "Can't reach the backend. Start everything with `make dev`.";
  return;
}
const FBY = Object.fromEntries(F.map(f=>[f.id,f]));
const clipFor = id => CL.find(c=>c.tags.some(t=>t.f===id));

/* ---------- the guide's voice + shared turn state ---------- */
const $ = id => document.getElementById(id);
let lastPlace=null, lastEmotion=null, kidTalking=false, askSeq=0, voiceScene=null;
const el=(tag,cls,attrs={})=>{const e=document.createElement(tag); if(cls)e.className=cls; Object.assign(e,attrs); return e;};
// UI that index.html doesn't own: built here, inside existing containers.
{
  const stage=$("stage"), bar=document.querySelector(".askbar");
  stage.append(el("div","atm-caption",{id:"caption",hidden:true}));
  $("caption").setAttribute("aria-live","polite");
  const ls=el("div","atm-listen",{id:"listenState"}); ls.dataset.state="off";
  ls.append(el("span","atm-listen-dot"),el("span","atm-listen-label",{id:"listenLabel",textContent:"Tap anywhere to turn on the mic · hold Space to ask"}),el("span","atm-listen-words",{id:"live"}));
  ls.setAttribute("aria-live","polite");
  bar.prepend(el("button","atm-nudge",{id:"nudge",type:"button",hidden:true}),ls);
  const crew=$("pane-crew"), la=el("div","atm-la-bar",{id:"laBar"});
  const lab=el("label"); lab.append(el("input","",{type:"checkbox",id:"explainOn",checked:true})," Explain hard words");
  la.append(lab,el("span","atm-la-state",{id:"laState"}));
  crew.insertBefore(la,$("clips"));
}
{const s=$("ttsState"), b=$("ttsBtn");
  if(!ttsAvailable){s.textContent="Read-aloud isn't available in this browser, so answers show as text.";}
  else{s.textContent="The guide reads answers out loud."; b.hidden=false;
    b.onclick=()=>{tts.on=!tts.on;b.textContent="Read aloud: "+(tts.on?"on":"off"); if(!tts.on)stopSpeaking();};}}
/** Scene changes (guide ↔ crew, new place) get one soft chime. */
function setScene(s){ if(s&&s!==voiceScene)chime(); voiceScene=s; }
function caption(who,text){const c=$("caption"); if(!text){c.hidden=true;return;} c.className="atm-caption"+(who==="Guide"?" is-guide":""); c.innerHTML=""; const b=document.createElement("b"); b.textContent=who; c.append(b,text); c.hidden=false;}
let capTimer=null;
const ttsOn=()=>ttsAvailable&&tts.on;
/** The guide speaks: captions always; never over crew audio (crew is faded and paused first). */
async function guideSay(text,opts){
  if(!text)return false;
  if(audio&&!audio.paused){await fadeTo(audio,0,180); audio.pause(); audio.volume=1;}
  setScene("guide"); caption("Guide",text); clearTimeout(capTimer);
  const ok=await speak(text,opts);
  capTimer=setTimeout(()=>{ if(voiceScene==="guide")caption(null); }, ttsOn()?1200:Math.max(3000,text.length*60));
  return ok;
}
const say=t=>{guideSay(t)};

/* ---------- three.js globe ---------- */
const stage=$("stage");
const renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
stage.prepend(renderer.domElement);
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(38,1,0.01,100);
camera.position.set(0,0,3.6);
const controls=new OrbitControls(camera,renderer.domElement);
controls.enablePan=false; controls.minDistance=1.5; controls.maxDistance=6; controls.enableDamping=true; controls.rotateSpeed=0.6;

scene.add(new THREE.AmbientLight(0xffffff,0.35*Math.PI));
const sun=new THREE.DirectionalLight(0xfff4e0,1.15*Math.PI); scene.add(sun);

const tex=new THREE.TextureLoader().load("/media/img/moon4k.jpg",()=>{$("loading").remove()} ,undefined,()=>{$("loading").textContent="Couldn't load the Moon map."});
tex.colorSpace=THREE.SRGBColorSpace; tex.anisotropy=renderer.capabilities.getMaxAnisotropy();
const moon=new THREE.Mesh(new THREE.SphereGeometry(R,128,96),new THREE.MeshStandardMaterial({map:tex,roughness:1,metalness:0}));
scene.add(moon);

// stars
{const g=new THREE.BufferGeometry(),n=1400,p=new Float32Array(n*3);
 for(let i=0;i<n;i++){const v=new THREE.Vector3().randomDirection?new THREE.Vector3().randomDirection():new THREE.Vector3(Math.random()-.5,Math.random()-.5,Math.random()-.5).normalize(); v.multiplyScalar(30+Math.random()*20); p.set([v.x,v.y,v.z],i*3);}
 g.setAttribute("position",new THREE.BufferAttribute(p,3));
 scene.add(new THREE.Points(g,new THREE.PointsMaterial({color:0xc8d0ff,size:0.08,sizeAttenuation:true,transparent:true,opacity:.7})));}

const ll2v=(lat,lon,r=R)=>{const phi=(90-lat)*Math.PI/180, th=(lon+180)*Math.PI/180;
  return new THREE.Vector3(-r*Math.sin(phi)*Math.cos(th), r*Math.cos(phi), r*Math.sin(phi)*Math.sin(th));};
const v2ll=v=>{const n=v.clone().normalize(); const lat=Math.asin(n.y)*180/Math.PI; let lon=Math.atan2(n.z,-n.x)*180/Math.PI-180; if(lon<-180)lon+=360; return {lat,lon};};

// pins
const pins=new THREE.Group(); scene.add(pins);
const pinMat=new THREE.MeshBasicMaterial({color:0xffc35a}), pinEst=new THREE.MeshBasicMaterial({color:0x7cc7ff});
F.forEach(f=>{const m=new THREE.Mesh(new THREE.SphereGeometry(0.009,10,8),f.est?pinEst:pinMat); m.position.copy(ll2v(f.lat,f.lon,R*1.002)); pins.add(m);});

// highlight ring
const ringMat=new THREE.MeshBasicMaterial({color:0xffc35a,side:THREE.DoubleSide,transparent:true,opacity:.95,depthTest:true});
let ring=null, sel=null;
function highlight(f){
  if(ring){scene.remove(ring);ring.geometry.dispose();}
  const ang=Math.max((f.km/2)/MOON_KM,0.035), r=Math.sin(ang), h=Math.cos(ang);
  ring=new THREE.Mesh(new THREE.RingGeometry(r*0.92,r,96),ringMat);
  const n=ll2v(f.lat,f.lon).normalize();
  ring.position.copy(n.clone().multiplyScalar(h*R+0.004)); ring.lookAt(n.clone().multiplyScalar(5));
  scene.add(ring); sel=f;
  const L=$("label"); L.innerHTML=""; L.append(f.name); if(f.est){const s=document.createElement("small");s.textContent="est.";L.append(s);} L.hidden=false;
}

// fly
let fly=null;
function flyTo(lat,lon,dist){
  const d=ll2v(Math.max(-75,Math.min(75,lat)),lon).normalize();
  const from=camera.position.clone(), fd=from.clone().normalize(), r0=from.length();
  const r1=dist||Math.min(Math.max(r0,2.4),3.2);
  fly={fd,td:d,r0,r1,t0:performance.now(),dur:1300};
}
function showFeature(f,{dist}={}){ highlight(f); flyTo(f.lat,f.lon,dist||(f.km>800?3.2:2.5)); sun.position.copy(ll2v(f.lat+15,f.lon-40).multiplyScalar(5)); }

function resize(){const w=stage.clientWidth,h=stage.clientHeight; renderer.setSize(w,h,false); camera.aspect=w/h; camera.updateProjectionMatrix();}
new ResizeObserver(resize).observe(stage); resize();
sun.position.copy(ll2v(10,-40).multiplyScalar(5));

const tmp=new THREE.Vector3();
function tick(now){
  if(fly){let t=Math.min(1,(now-fly.t0)/fly.dur); const e=t<.5?2*t*t:1-Math.pow(-2*t+2,2)/2;
    let a=fly.fd, b=fly.td; const dot=a.dot(b);
    let dir;
    if(dot<-0.98){const mid=new THREE.Vector3(0,1,0).cross(a).normalize(); dir=e<.5?a.clone().lerp(mid,e*2):mid.clone().lerp(b,(e-.5)*2);}
    else dir=a.clone().lerp(b,e);
    camera.position.copy(dir.normalize().multiplyScalar(fly.r0+(fly.r1-fly.r0)*e)); camera.lookAt(0,0,0);
    if(t>=1)fly=null;}
  controls.update();
  if(ring) ring.material.opacity=.65+.3*Math.sin(now/300);
  if(sel){const p=ll2v(sel.lat,sel.lon,R*1.01); const facing=p.clone().normalize().dot(camera.position.clone().normalize())>0.15;
    tmp.copy(p).project(camera); const L=$("label");
    L.style.left=((tmp.x+1)/2*stage.clientWidth)+"px"; L.style.top=((1-tmp.y)/2*stage.clientHeight)+"px"; L.style.opacity=facing?1:0;}
  renderer.render(scene,camera); requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

// tap to identify
const ray=new THREE.Raycaster(), ndc=new THREE.Vector2(); let down=null;
renderer.domElement.addEventListener("pointerdown",e=>{down=[e.clientX,e.clientY]});
renderer.domElement.addEventListener("pointerup",e=>{ if(!down)return; const moved=Math.hypot(e.clientX-down[0],e.clientY-down[1]); down=null; if(moved>6)return;
  const r=renderer.domElement.getBoundingClientRect(); ndc.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);
  ray.setFromCamera(ndc,camera); const hit=ray.intersectObject(moon)[0]; if(!hit)return; onTap(v2ll(hit.point));});
const angDist=(a,b)=>Math.acos(Math.min(1,ll2v(a.lat,a.lon).normalize().dot(ll2v(b.lat,b.lon).normalize())))*180/Math.PI;
function nearest(p){let best=null,bd=1e9; F.forEach(f=>{const d=angDist(p,f)-((f.km/2)/MOON_KM*180/Math.PI)*0.6; if(d<bd){bd=d;best=f}}); return {f:best,d:bd};}

$("nearBtn").onclick=()=>{flyTo(0,0,3.6)};
$("farBtn").onclick=()=>{flyTo(0,180,3.6)};
$("pinsBtn").onclick=e=>{pins.visible=!pins.visible; e.currentTarget.textContent=pins.visible?"Hide pins":"Show pins";};

/* ---------- tabs ---------- */
const tabs=[...document.querySelectorAll("[role=tab]")];
function setTab(name){tabs.forEach(t=>{const on=t.dataset.tab===name;t.setAttribute("aria-selected",on);$("pane-"+t.dataset.tab).hidden=!on});
  try{localStorage.setItem("atm-tab",name)}catch(e){} }
tabs.forEach(t=>t.onclick=()=>setTab(t.dataset.tab));

/* ---------- ask / Director actions ---------- */
const log=$("log");
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function bubble(cls){const d=document.createElement("div");d.className=cls;log.append(d);$("pane-ask").scrollTop=1e9;return d;}
function kidSays(q){bubble("kid").textContent=q;}
function para(g,t,cls){const p=document.createElement("p");p.textContent=t;if(cls)p.className=cls;g.append(p);return p;}
function guideText(t){const g=bubble("guide");para(g,t);say(t);return g;}
let thinkingEl=null;
function thinking(on){ if(on&&!thinkingEl){thinkingEl=bubble("guide");para(thinkingEl,"…");} if(!on&&thinkingEl){thinkingEl.remove();thinkingEl=null;} }

function readout(r){
  const x=r.readout||{}; const bits=[];
  if(x.available){ if(x.act&&x.act.length)bits.push("act: "+x.act.join(", ")); if(x.mentions&&x.mentions.length)bits.push("heard: "+x.mentions.join(", ")); if(x.hard_pii&&x.hard_pii.length)bits.push("private: "+x.hard_pii.join(", ")); if(x.ms!=null)bits.push(x.ms+" ms"); }
  else bits.push("Arc Tagger offline: rules only");
  if(r.corrected)bits.push("self-correction");
  if(r.action)bits.push(r.action.toUpperCase());
  if(r.source)bits.push("via "+r.source);
  return bits.join(" · ");
}
function tagLine(el,r){const d=document.createElement("div");d.className="tag-src";d.textContent="Arc read-out · "+readout(r);el.append(d);}
/** Source chips: verified = solid, crew impression = outlined, contradicted/removed = hidden. */
function claimChips(el,claims){
  const vis=(claims||[]).filter(c=>c&&c.text&&(c.status==="verified"||c.status==="impression"||c.status==="crew_impression"));
  if(!vis.length)return; const row=document.createElement("div"); row.className="atm-claims";
  vis.forEach(c=>{const s=document.createElement("span"); const imp=c.status!=="verified"; s.className="atm-claim"+(imp?" is-impression":"");
    s.textContent=c.text; const sm=document.createElement("small"); sm.textContent=imp?"how it looked to the crew":(c.source?"· "+c.source:"· checked");
    s.append(sm); if(c.source)s.title=c.source; row.append(s);});
  el.append(row);
}

function context(){
  const c={}; if(lastPlace)c.last_place=lastPlace; if(lastEmotion)c.emotion=lastEmotion;
  if(cur&&!audio.paused)c.playing={clip_id:cur.id,t:+audio.currentTime.toFixed(2)};
  return c;
}

/** Accept the Director contract and the v0.2 shape (`lead`, `clip:{id,t}`). */
async function normalize(r){
  const f=r.place&&FBY[r.place]?FBY[r.place]:null;
  let say=r.say||"";
  if(f&&("lead" in r||!say)) say=[f.name+".",r.lead,f.fact].filter(Boolean).join(" ");
  let moment=r.moment?normMoment(r.moment):null;
  if(!moment&&r.clip&&r.clip.id){
    const c=CL.find(x=>x.id===r.clip.id);
    if(c){const t=+r.clip.t||0; const ds=deriveMoments(c,placeName).filter(m=>m.t0<=t+0.5&&m.t1>=t);
      moment=ds.find(m=>!f||m.places.includes(f.id))||ds[0]||{id:"x-"+c.id,clip_id:c.id,t0:Math.max(0,t-1.5),t1:Math.min(c.dur,t+20),places:f?[f.id]:[],jargon:[],speaker:"crew"};}
  }
  return {action:r.action||(f?"fly":"say"),say,f,view:r.view||null,moment,ask:r.ask||null,claims:r.claims||[],raw:r};
}

async function ask(raw){
  const text=(raw||"").trim(); if(!text)return;
  const ctx=context(); const my=++askSeq; cancelNudge();
  setTab("ask"); kidSays(text); $("q").value=""; $("live").textContent=""; thinking(true);
  let r;
  try{ const res=await fetch("/api/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text,context:ctx})}); if(!res.ok)throw new Error(res.status); r=await res.json(); }
  catch(e){ if(my!==askSeq)return; thinking(false); const g=bubble("guide"); para(g,"I can't reach my brain right now. Is the backend running?"); return; }
  // WAIT: never answer while the kid is still talking.
  for(let w=0;kidTalking&&w<100;w++)await sleep(100);
  if(my!==askSeq)return;
  thinking(false);
  await act(await normalize(r),my);
}

async function act(d,my){
  const r=d.raw, f=d.f;
  if(d.action==="guard"){ const g=bubble("guide"); para(g,d.say); tagLine(g,r); await guideSay(d.say); scheduleNudge(); return; }
  if(d.action==="ask"&&d.ask){ askCard(d); return; }
  if(d.view&&!f){ flyTo(d.view.lat,d.view.lon,3.6); }
  if(f){ if(f.id!==lastPlace)chime(); showFeature(f); if(d.view)flyTo(d.view.lat,d.view.lon); lastPlace=f.id; }
  const g=bubble("guide");
  if(f){const h=document.createElement("h3"); h.textContent=f.name; g.append(h);}
  para(g,d.say);
  if(f&&f.est)para(g,"Location estimated from the crew's own directions.","muted");
  claimChips(g,d.claims);
  const row=document.createElement("div"); row.className="row"; g.append(row);
  if(f&&d.action!=="play"){ getMoments(f.id,CL,placeName).then(ms=>{ if(!ms.length)return; const b=document.createElement("button");b.className="pill hot";b.type="button";b.textContent="▶ Hear the crew talk about it";b.onclick=()=>playMoment(ms[0]);row.prepend(b);}); }
  if(f){const ll=document.createElement("span"); ll.className="tag-src"; ll.textContent=`${Math.abs(f.lat).toFixed(1)}°${f.lat>=0?"N":"S"} ${Math.abs(f.lon).toFixed(1)}°${f.lon>=0?"E":"W"}`; row.append(ll);}
  tagLine(g,r);
  const spoke=await guideSay(d.say);
  if(my!==askSeq)return;
  if(d.action==="play"&&d.moment){ if(!spoke&&kidTalking)return; await playMoment(d.moment,{fromAsk:true}); return; }
  scheduleNudge();
}

/** ASK: options preview-fly the globe; a choice goes back as a new ask. */
function askCard(d){
  const q=d.ask.question||d.say; const g=bubble("guide"); para(g,q); tagLine(g,d.raw);
  const opts=(d.ask.options||[]).map(id=>FBY[id]).filter(Boolean);
  const row=document.createElement("div"); row.className="atm-opts"; g.append(row);
  opts.forEach(f=>{const b=document.createElement("button"); b.type="button"; b.className="pill hot"; b.textContent=f.name;
    const pv=()=>showFeature(f); b.onmouseenter=pv; b.onfocus=pv;
    b.onclick=()=>{row.querySelectorAll("button").forEach(x=>x.disabled=true); lastPlace=f.id; ask(f.name);};
    row.append(b);});
  guideSay(q);
  // a short preview tour while the question is read out
  opts.forEach((f,i)=>setTimeout(()=>{ if(!kidTalking)showFeature(f); },400+i*1600));
  scheduleNudge();
}

$("askForm").addEventListener("submit",e=>{e.preventDefault();ask($("q").value)});
const CHIPS=["Where did Apollo 11 land?","Show me the giant bullseye","What did the astronauts say about the yellow part?","Show me the far side","Where will astronauts land next?","Which crater did the crew name after their spaceship?","What's the biggest crater?","Show me Earthrise"];
CHIPS.forEach(c=>{const b=document.createElement("button");b.type="button";b.textContent=c;b.onclick=()=>ask(c);$("chips").append(b)});

/* ---------- NUDGE: 8 s of quiet after an answer ---------- */
let nudgeT=null;
function cancelNudge(){clearTimeout(nudgeT); nudgeT=null; $("nudge").hidden=true;}
function scheduleNudge(){
  clearTimeout(nudgeT);
  nudgeT=setTimeout(async()=>{
    if(kidTalking||isSpeaking()||!audio.paused||micOn()){ if(!micOn()||!kidTalking)scheduleNudge(); return; }
    const n=$("nudge");
    if(!done.size){ n.textContent="Try mission 1?"; n.onclick=()=>{cancelNudge(); active=0; renderMissions(); setTab("mission"); say(M[0].clue);}; n.hidden=false; return; }
    const all=await getMoments(null,CL,placeName); const m=all.find(x=>x.places.some(p=>p!==lastPlace&&FBY[p]))||all[0];
    if(!m){ return; }
    const nm=FBY[m.places[0]]?FBY[m.places[0]].name:"the Moon";
    n.textContent=`Hear the crew at ${nm}?`; n.onclick=()=>{cancelNudge(); playMoment(m);}; n.hidden=false;
  },8000);
}

/* ---------- crew logs: Listen Along ---------- */
const audio=$("audio"), tr=$("transcript"); let cur=null, spans=[], lastI=-1, followF=null;
const fmt=s=>`${Math.floor(s/60)}:${String(Math.round(s%60)).padStart(2,"0")}`;
const placeName=id=>FBY[id]?FBY[id].name:id;
let explainOn=true; $("explainOn").onchange=e=>{explainOn=e.target.checked;};
let LA=null;   // the moment playing: {m, ends, j, pending, lastPause, explaining}

function load(c){
  if(cur===c)return;
  cur=c; lastI=-1; followF=null;
  audio.src=c.file; tr.innerHTML=""; spans=[];
  const tagAt={}; c.tags.forEach(t=>tagAt[t.i]=t);
  c.words.forEach(([t,w],i)=>{const s=document.createElement("span"); s.textContent=w; const tg=tagAt[i]; if(tg){s.className="t-"+tg.type; s.title=tg.type+(tg.f&&FBY[tg.f]?" → "+FBY[tg.f].name:"")+(tg.src?"  ["+tg.src+"]":"");}
    s.onclick=()=>{audio.currentTime=t; audio.play().catch(()=>{})}; spans.push(s); tr.append(s," ");});
  const cnt={}; c.tags.forEach(t=>cnt[t.type]=(cnt[t.type]||0)+1);
  $("tagStats").textContent=`${c.words.length} words indexed · `+Object.entries(cnt).map(([k,v])=>`${k} ${v}`).join(" · ");
  $("player").hidden=false;
}
function seek(t){return new Promise(res=>{const go=()=>{audio.currentTime=t;res();}; if(audio.readyState>=1)return go(); audio.addEventListener("loadedmetadata",go,{once:true}); audio.preload="auto"; audio.load(); setTimeout(res,4000);});}

async function renderMoments(){
  const box=$("clips"); const ms=await getMoments(null,CL,placeName); box.innerHTML="";
  if(!ms.length){box.textContent="No crew moments yet.";return;}
  ms.slice(0,24).forEach(m=>{const c=CL.find(x=>x.id===m.clip_id); if(!c)return;
    const b=document.createElement("button"); b.className="clip"; b.type="button"; b.dataset.id=m.id; b.setAttribute("aria-pressed","false");
    const l=document.createElement("div"); const t=document.createElement("b"); t.textContent=(m.places||[]).map(placeName).join(" · ")||c.title;
    const who=document.createElement("span"); who.className="atm-moment-who"; who.textContent=(m.speaker&&m.speaker!=="crew"?m.speaker+" · ":"")+c.title;
    const q=document.createElement("q"); q.className="atm-moment-text"; q.textContent=(m.text||"").split(/\s+/).slice(0,14).join(" ")+"…";
    l.append(t,who,q); const tm=document.createElement("time"); tm.textContent=fmt(Math.max(1,(m.t1??c.dur)-m.t0));
    b.append(l,tm); b.onclick=()=>playMoment(m); box.append(b);});
}

/** PLAY a moment from t0 and stop at t1; fly as places are spoken; PAUSE_EXPLAIN at sentence ends. */
async function playMoment(m,{fromAsk}={}){
  m=normMoment(m); const c=CL.find(x=>x.id===m.clip_id); if(!c)return;
  cancelNudge(); if(!fromAsk)stopSpeaking();
  document.querySelectorAll(".clip").forEach(b=>b.setAttribute("aria-pressed",b.dataset.id===m.id));
  load(c); setTab("crew");
  const p=m.places.find(id=>FBY[id]);
  if(p){ showFeature(FBY[p]); followF=p; lastPlace=p; }
  LA={m,c,ends:sentenceEnds(c),j:0,pending:null,lastPause:-1e9,explaining:false};
  await seek(m.t0); audio.volume=1;
  setScene("crew"); caption(null);
  try{ await audio.play(); }catch(e){ $("laState").textContent="Press play to listen."; }
}

function crewLoop(){
  if(!LA||audio.paused||LA.explaining)return;
  const {m,c}=LA, t=audio.currentTime;
  if(m.t1!=null&&t>=m.t1){ endMoment(); return; }
  if(explainOn&&!LA.pending){
    while(LA.j<m.jargon.length&&m.jargon[LA.j].t<=t){
      const jg=m.jargon[LA.j++]; const at=LA.ends.find(e=>e>=jg.t+0.05);
      if(at!=null&&(m.t1==null||at<m.t1-0.3)){ LA.pending={jg,at}; break; }
    }
  }
  if(LA.pending&&t>=LA.pending.at-0.08){
    const {jg}=LA.pending; LA.pending=null;
    const ok=t-m.t0>=5&&performance.now()-LA.lastPause>=30000&&!kidTalking;
    if(ok)explain(jg);
  }
}
setInterval(crewLoop,60);

async function explain(jg){
  const my=LA; my.explaining=true; my.lastPause=performance.now();
  await fadeTo(audio,0,200); audio.pause();
  const w=jg.word.charAt(0).toUpperCase()+jg.word.slice(1);
  const line=`${w} means ${jg.explain.split(/\s+/).slice(0,10).join(" ")}.`;
  $("laState").textContent="Explaining “"+jg.word+"”";
  setScene("guide"); caption("Guide",line);
  await speak(line,{rate:0.9,pitch:1.0});
  if(!ttsOn())await sleep(2200);
  if(LA!==my)return;
  my.explaining=false; $("laState").textContent="";
  if(kidTalking)return;           // kid barged in: stay paused, they get the floor
  caption(null); setScene("crew");
  audio.volume=0; try{ await audio.play(); }catch(e){} fadeTo(audio,1,250);
}

function endMoment(){
  const my=LA; if(!my)return; LA=null;
  fadeTo(audio,0,200).then(()=>{audio.pause(); audio.volume=1;});
  setScene("guide"); caption(null); $("follow").hidden=true; $("laState").textContent="";
  scheduleNudge();
}

audio.addEventListener("timeupdate",()=>{ if(!cur)return; const t=audio.currentTime, W=cur.words;
  let lo=0,hi=W.length-1,i=-1; while(lo<=hi){const m=(lo+hi)>>1; if(W[m][0]<=t){i=m;lo=m+1}else hi=m-1;}
  if(i===lastI)return;
  const a=Math.min(lastI,i), b=Math.max(lastI,i);
  for(let k=Math.max(0,a);k<=b&&k<spans.length;k++){spans[k].classList.toggle("past",k<i);spans[k].classList.remove("now");}
  if(i<lastI) spans.forEach((s,k)=>s.classList.toggle("past",k<i));
  lastI=i; if(i<0)return; const s=spans[i]; s.classList.add("now");
  const top=s.offsetTop-tr.clientHeight/2; tr.scrollTop=Math.max(0,top);
  // captions for crew audio: the last few words
  if(!audio.paused&&voiceScene==="crew") caption(LA&&LA.m.speaker&&LA.m.speaker!=="crew"?LA.m.speaker:"Crew",W.slice(Math.max(0,i-9),i+1).map(w=>w[1]).join(" "));
  // follow the crew: most recent FEATURE tag at or before i
  let ft=null; for(const tg of cur.tags){ if(tg.i>i)break; if(tg.f&&FBY[tg.f])ft=tg; }
  if(ft&&ft.f!==followF){followF=ft.f; const f=FBY[ft.f]; chime(); showFeature(f); lastPlace=f.id; const fl=$("follow"); fl.hidden=false; fl.textContent="Following the crew → "+f.name;}
});
audio.addEventListener("pause",()=>{$("follow").hidden=true; if(voiceScene==="crew"&&!(LA&&LA.explaining))caption(null);});
audio.addEventListener("play",()=>{ if(voiceScene!=="crew"&&!(LA&&LA.explaining)){stopSpeaking(); setScene("crew");} cancelNudge(); });
audio.addEventListener("ended",()=>{ if(LA)endMoment(); });
renderMoments();

/* ---------- live mic: always-on WS /ws/listen + Space push-to-talk (Head Start model) ---------- */
// The mic opens after the first gesture and stays open. Holding Space marks the turn "for the guide";
// on release (after a 500 ms tail so the last word lands) or on the server's turn end, the app asks.
// Without /ws/listen, Space (or the mic button) is push-to-talk on the browser's Web Speech recognizer.
const micBtn=$("mic"), note=$("voiceNote");
let mode="off", wsBroken=false, starting=false, finalBuf="", interim="", turnAsked=false;
const ptt={held:false,tail:null};
const micOn=()=>mode==="ws"||srOn;
const turnText=()=>(finalBuf+" "+interim).trim();
function indicator(state,label){
  const ls=$("listenState"); ls.dataset.state=state;
  $("listenLabel").textContent=label||({off:"Mic off · tap the mic or hold Space to ask",listening:"Listening · hold Space to ask the guide",hearing:"Hearing you…",ptt:"Talk to the guide · let go of Space when done",thinking:"Thinking…",error:"Mic unavailable · type your question"})[state];
  micBtn.classList.toggle("on",state!=="off"&&state!=="error"); micBtn.setAttribute("aria-label",mode==="ws"?"Turn the mic off":"Talk");
}
const idle=()=>indicator(mode==="ws"?"listening":"off");
function showWords(){ $("live").textContent=turnText(); }
function bargeIn(){
  kidTalking=true; cancelNudge();
  if(isSpeaking())stopSpeaking();
  if(!audio.paused)fadeTo(audio,0.2,150);
}
function kidDone(){ kidTalking=false; if(!audio.paused)fadeTo(audio,1,250); idle(); }
function askTurn(text){
  turnAsked=true; finalBuf=""; interim=""; kidTalking=false; thinking(false); $("live").textContent="";
  if(!text){ kidDone(); return; }
  indicator("thinking"); ask(text).finally(()=>{ if($("listenState").dataset.state==="thinking")idle(); });
}

const listener=createListener({
  message(m){
    if(m.t==="ready"){ idle(); }
    else if(m.t==="words"){ if(m.final){finalBuf+=(m.text||"")+" "; interim="";} else interim=m.text||""; showWords(); }
    else if(m.t==="turn"){
      if(m.state==="start"){ turnAsked=false; bargeIn(); if(!ptt.held)indicator("hearing"); }
      else if(m.state==="eager"){ if(!turnAsked)thinking(true); }
      else if(m.state==="resumed"){ kidTalking=true; askSeq++; thinking(false); turnAsked=false; if(!ptt.held)indicator("hearing"); }
      else if(m.state==="end"){ if(ptt.held)return;   // Space still down: the kid isn't done
        if(!turnAsked)askTurn((m.text||turnText()).trim()); }
    }
    else if(m.t==="emotion"){ if(m.label)lastEmotion=m.label; }
    else if(m.t==="error"){ note.textContent="Voice hiccup: "+(m.message||"try again"); }
  },
  close(){ if(mode==="ws"){ mode="off"; kidTalking=false; indicator("off"); } },
  micError(){ note.textContent="Mic is blocked. Allow it in the address bar, or type instead."; indicator("error"); },
});

const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
let rec=null, srOn=false;
if(SR){ rec=new SR(); rec.lang="en-US"; rec.interimResults=true; rec.continuous=true;
  rec.onresult=e=>{interim="";for(let i=e.resultIndex;i<e.results.length;i++){const r=e.results[i];if(r.isFinal)finalBuf+=r[0].transcript+" ";else interim+=r[0].transcript;} showWords(); if(!kidTalking)bargeIn();};
  rec.onstart=()=>{srOn=true;indicator(ptt.held?"ptt":"hearing");};
  rec.onend=()=>{srOn=false; askTurn(turnText());};
  rec.onerror=e=>{ if(e.error==="not-allowed"||e.error==="service-not-allowed"){note.textContent="Mic is blocked. Allow it in the address bar, or type instead.";indicator("error");} };
}
const canWS=!!(navigator.mediaDevices&&window.AudioWorkletNode);
if(!canWS&&!SR){ note.textContent="Voice input works in Chrome or Edge. Here, type your question."; indicator("error"); }
else { micBtn.hidden=false; indicator("off"); }

async function startAlwaysOn(){
  if(mode==="ws"||starting||wsBroken||!canWS)return mode==="ws";
  starting=true; indicator("thinking","Turning the mic on…");
  const ok=await listener.start(); starting=false;
  if(ok===true){ mode="ws"; idle(); return true; }
  if(ok!=="mic"){ wsBroken=true; note.textContent=SR?"Hold Space (or tap the mic) to talk.":"Live voice isn't available here. Type your question."; }
  indicator(ok==="mic"?"error":"off"); return false;
}
function stopAlwaysOn(){ listener.stop(); mode="off"; kidTalking=false; indicator("off"); }
function srStart(){ if(!rec||srOn)return; stopSpeaking(); finalBuf=""; interim=""; turnAsked=false; try{rec.start()}catch(e){} }

// First gesture anywhere opens the mic (browsers need a gesture for audio + mic).
const firstGesture=()=>{ removeEventListener("pointerdown",firstGesture,true); removeEventListener("keydown",firstGesture,true); startAlwaysOn(); };
addEventListener("pointerdown",firstGesture,true); addEventListener("keydown",firstGesture,true);

micBtn.onclick=async()=>{
  if(mode==="ws"){ stopAlwaysOn(); return; }
  if(srOn){ rec.stop(); return; }
  if(await startAlwaysOn())return;
  if(starting)return;
  srStart();
};

const typing=e=>e.target&&e.target.closest&&e.target.closest("input, textarea, select, [contenteditable]");
addEventListener("keydown",async e=>{
  if(e.code!=="Space"||typing(e)||e.metaKey||e.ctrlKey||e.altKey)return;
  e.preventDefault(); if(e.repeat||ptt.held)return;
  ptt.held=true; if(ptt.tail){clearTimeout(ptt.tail);ptt.tail=null;}
  bargeIn(); turnAsked=false;
  if(mode!=="ws"&&!wsBroken){ await startAlwaysOn(); }
  if(mode==="ws"){ indicator("ptt"); return; }
  if(!ptt.held)return;
  srStart(); indicator("ptt");
});
function release(){
  if(!ptt.held)return; ptt.held=false;
  ptt.tail=setTimeout(()=>{ ptt.tail=null;
    if(mode==="ws"){ if(!turnAsked)askTurn(turnText()); }
    else if(srOn) rec.stop();
    else kidDone();
  },500);
}
addEventListener("keyup",e=>{ if(e.code!=="Space"||!ptt.held)return; e.preventDefault(); release(); });
addEventListener("blur",release);


/* ---------- missions ---------- */
const M=[
 {f:"aristarchus",t:"The yellow cheek",clue:"The crew said one plateau looked like a yellow, snow-capped mountain. Can you find it on the near side?"},
 {f:"tranquillitatis",t:"First footprints",clue:"Find the dark sea where people first walked on the Moon in 1969."},
 {f:"orientale",t:"The giant bullseye",clue:"Find the huge target with rings, right on the edge between the near and far side."},
 {f:"integrity",t:"A crater named after a spaceship",clue:"Start at Orientale. Go straight up to Ohm. Tap halfway between them."},
 {f:"shackleton",t:"Where astronauts go next",clue:"Find the place at the very bottom of the Moon where ice might hide."},
];
let active=0; const done=new Set();
function renderMissions(){const box=$("missions"); box.innerHTML="";
  $("score").textContent=`★ ${done.size} of ${M.length} found`;
  M.forEach((m,i)=>{const d=document.createElement("div"); d.className="mission"+(i===active&&!done.has(i)?" active":"")+(done.has(i)?" done":"");
    const st=document.createElement("div"); st.className="star"; st.textContent=done.has(i)?"★":String(i+1);
    const body=document.createElement("div"); const b=document.createElement("b"); b.textContent=m.t; const p=document.createElement("p"); p.textContent=m.clue;
    const row=document.createElement("div"); row.className="row"; row.style.display="flex"; row.style.gap="8px";
    if(!done.has(i)){const go=document.createElement("button");go.type="button";go.className="pill"+(i===active?" hot":"");go.textContent=i===active?"Tap the Moon to answer":"Try this one";go.onclick=()=>{active=i;renderMissions();say(m.clue)};row.append(go);
      const h=document.createElement("button");h.type="button";h.className="pill";h.textContent="Show me";h.onclick=()=>{showFeature(FBY[m.f]);};row.append(h);}
    body.append(b,p,row); d.append(st,body); box.append(d);});
}
renderMissions();
function onTap(p){
  const missionTab=!$("pane-mission").hidden;
  if(missionTab && !done.has(active)){const m=M[active], f=FBY[m.f];
    const tol=Math.max((f.km/2)/MOON_KM*180/Math.PI*1.4,f.est?9:7);
    if(angDist(p,f)<=tol){done.add(active); showFeature(f); say("You found it! "+f.name+". "+f.fact);
      const nx=M.findIndex((_,i)=>!done.has(i)); if(nx>=0)active=nx; renderMissions(); return;}
    const n=nearest(p).f; say("That's "+n.name+". Keep looking!"); highlight(n); return;}
  const {f,d}=nearest(p);
  if(d<12){showFeature(f); setTab("ask"); lastPlace=f.id; act({action:"fly",say:`You tapped near ${f.name}. ${f.fact}`,f,view:null,moment:null,ask:null,claims:[],raw:{action:"fly",source:"tap",readout:{available:true}}},askSeq);}
  else { setTab("ask"); guideText(`That spot is ${Math.abs(p.lat).toFixed(0)}° ${p.lat>=0?"north":"south"}, ${Math.abs(p.lon).toFixed(0)}° ${p.lon>=0?"east":"west"}. No named place in my list is close. Try a darker or brighter patch!`);}
}

// open on a real moment: the crew's view of Orientale
try{const t=localStorage.getItem("atm-tab"); if(t&&$("pane-"+t))setTab(t);}catch(e){}
showFeature(FBY.orientale,{dist:3.3});
})();
