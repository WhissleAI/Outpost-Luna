import "./styles.css";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

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

/* ---------- voice in / voice out (browser Web Speech API) ---------- */
const $ = id => document.getElementById(id);
let ttsOn=true, llm=true, listening=false;
const synth=window.speechSynthesis||null;
{const s=$("ttsState"), b=$("ttsBtn");
  if(!synth){s.textContent="Read-aloud isn't available in this browser, so answers show as text.";}
  else{s.textContent="The guide reads answers out loud."; b.hidden=false;
    b.onclick=()=>{ttsOn=!ttsOn;b.textContent="Read aloud: "+(ttsOn?"on":"off"); if(!ttsOn)synth.cancel();};}}
function pickVoice(){const v=synth?synth.getVoices():[]; return v.find(x=>/Samantha|Google US English|Karen|Moira/.test(x.name))||v.find(x=>x.lang&&x.lang.startsWith("en"));}
function say(text){ if(!synth||!ttsOn)return; synth.cancel(); const u=new SpeechSynthesisUtterance(text); const v=pickVoice(); if(v)u.voice=v; u.rate=0.98; u.pitch=1.08; synth.speak(u); }
function stopTalking(){ if(synth)synth.cancel(); }
{const SR=window.SpeechRecognition||window.webkitSpeechRecognition, m=$("mic"), n=$("voiceNote");
  if(!SR){n.textContent="Voice input works in Chrome or Edge. Here, type your question.";}
  else{const rec=new SR(); rec.lang="en-US"; rec.interimResults=true; rec.continuous=false; let finalBuf="";
    m.hidden=false;
    rec.onresult=e=>{let interim="";for(let i=e.resultIndex;i<e.results.length;i++){const r=e.results[i];if(r.isFinal)finalBuf+=r[0].transcript+" ";else interim+=r[0].transcript;} $("q").value=(finalBuf+interim).trim();};
    rec.onstart=()=>{listening=true;m.classList.add("on");m.setAttribute("aria-label","Stop listening");};
    rec.onend=()=>{listening=false;m.classList.remove("on");m.setAttribute("aria-label","Talk"); const q=finalBuf.trim(); finalBuf=""; if(q)ask(q);};
    rec.onerror=e=>{ if(e.error==="not-allowed"||e.error==="service-not-allowed"){m.hidden=true;n.textContent="Mic is blocked. Allow it in the address bar, or type instead.";} };
    m.onclick=()=>{ if(listening){rec.stop();return;} stopTalking(); finalBuf=""; $("q").value=""; try{rec.start()}catch(e){} };}}

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

/* ---------- ask / intent ---------- */
const log=$("log");
function bubble(cls){const d=document.createElement("div");d.className=cls;log.append(d);$("pane-ask").scrollTop=1e9;return d;}
function kidSays(q){bubble("kid").textContent=q;}
function guideCard(f,lead){
  const g=bubble("guide"); const h=document.createElement("h3"); h.textContent=f.name; g.append(h);
  const p=document.createElement("p"); p.textContent=(lead?lead+" ":"")+f.fact; g.append(p);
  if(f.est){const m=document.createElement("p");m.className="muted";m.textContent="Location estimated from the crew's own directions.";g.append(m);}
  const row=document.createElement("div"); row.className="row"; g.append(row);
  const c=clipFor(f.id);
  if(c){const b=document.createElement("button");b.className="pill hot";b.type="button";b.textContent="▶ Hear the crew talk about it";b.onclick=()=>playAt(c,f.id);row.append(b);}
  const ll=document.createElement("span"); ll.className="tag-src"; ll.textContent=`${Math.abs(f.lat).toFixed(1)}°${f.lat>=0?"N":"S"} ${Math.abs(f.lon).toFixed(1)}°${f.lon>=0?"E":"W"}`; row.append(ll);
  say(f.name+". "+(lead?lead+" ":"")+f.fact);
}
function guideText(t){const g=bubble("guide");const p=document.createElement("p");p.textContent=t;g.append(p);say(t);return g;}

function readout(r){
  const x=r.readout||{}; const bits=[];
  if(x.available){ if(x.act&&x.act.length)bits.push("act: "+x.act.join(", ")); if(x.mentions&&x.mentions.length)bits.push("heard: "+x.mentions.join(", ")); if(x.hard_pii&&x.hard_pii.length)bits.push("private: "+x.hard_pii.join(", ")); if(x.ms!=null)bits.push(x.ms+" ms"); }
  else bits.push("Arc Tagger offline: rules only");
  if(r.corrected)bits.push("self-correction");
  bits.push("via "+r.source);
  return bits.join(" · ");
}
function tagLine(el,r){const d=document.createElement("div");d.className="tag-src";d.textContent="Arc read-out · "+readout(r);el.append(d);}

async function ask(raw){
  const text=(raw||"").trim(); if(!text)return; setTab("ask"); kidSays(text); $("q").value="";
  const g=guideText("…"); let r;
  try{ const res=await fetch("/api/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text})}); if(!res.ok)throw new Error(res.status); r=await res.json(); }
  catch(e){ g.querySelector("p").textContent="I can't reach my brain right now. Is the backend running?"; return; }
  g.remove();
  const f=r.place&&FBY[r.place];
  if(r.view)flyTo(r.view.lat,r.view.lon,3.6);
  if(f){ showFeature(f); guideCard(f,r.lead||""); }
  else if(r.say){ tagLine(guideText(r.say),r); }
  if(f) tagLine(log.lastElementChild,r);
  if(r.action==="play"&&r.clip){ const c=CL.find(c=>c.id===r.clip.id); if(c) load(c,true,r.clip.t); }
}
$("askForm").addEventListener("submit",e=>{e.preventDefault();ask($("q").value)});
const CHIPS=["Where did Apollo 11 land?","Show me the giant bullseye","What did the astronauts say about the yellow part?","Show me the far side","Where will astronauts land next?","Which crater did the crew name after their spaceship?","What's the biggest crater?","Show me Earthrise"];
CHIPS.forEach(c=>{const b=document.createElement("button");b.type="button";b.textContent=c;b.onclick=()=>ask(c);$("chips").append(b)});

/* ---------- crew logs ---------- */
const audio=$("audio"), tr=$("transcript"); let cur=null, spans=[], lastI=-1, followF=null;
const fmt=s=>`${Math.floor(s/60)}:${String(Math.round(s%60)).padStart(2,"0")}`;
CL.forEach(c=>{const b=document.createElement("button");b.className="clip";b.type="button";b.dataset.id=c.id;b.setAttribute("aria-pressed","false");
  const fs=[...new Set(c.tags.filter(t=>t.f&&FBY[t.f]).map(t=>FBY[t.f].name))];
  const l=document.createElement("div"); const t=document.createElement("b"); t.textContent=c.title; const s=document.createElement("span"); s.textContent=fs.length?fs.join(" · "):"Earth, the limb"; l.append(t,s);
  const tm=document.createElement("time"); tm.textContent=fmt(c.dur); b.append(l,tm); b.onclick=()=>load(c,true); $("clips").append(b);});
function load(c,autoplay,startAt){
  if(cur!==c){cur=c; lastI=-1; followF=null;
    document.querySelectorAll(".clip").forEach(b=>b.setAttribute("aria-pressed",b.dataset.id===c.id));
    audio.src=c.file; tr.innerHTML=""; spans=[];
    const tagAt={}; c.tags.forEach(t=>tagAt[t.i]=t);
    c.words.forEach(([t,w],i)=>{const s=document.createElement("span"); s.textContent=w; const tg=tagAt[i]; if(tg){s.className="t-"+tg.type; s.title=tg.type+(tg.f&&FBY[tg.f]?" → "+FBY[tg.f].name:"")+(tg.src?"  ["+tg.src+"]":"");}
      s.onclick=()=>{audio.currentTime=t; audio.play().catch(()=>{})}; spans.push(s); tr.append(s," ");});
    const cnt={}; c.tags.forEach(t=>cnt[t.type]=(cnt[t.type]||0)+1);
    $("tagStats").textContent=`${c.words.length} words indexed · `+Object.entries(cnt).map(([k,v])=>`${k} ${v}`).join(" · ");
    $("player").hidden=false;}
  setTab("crew");
  if(startAt!=null){const go=()=>{audio.currentTime=Math.max(0,startAt-1.5)}; if(audio.readyState>=1)go(); else audio.addEventListener("loadedmetadata",go,{once:true});}
  if(autoplay){ stopTalking(); audio.play().catch(()=>{}); }
}
function playAt(c,fid){const tg=fid&&c.tags.find(t=>t.f===fid); load(c,true,tg?c.words[tg.i][0]:0);}
audio.addEventListener("timeupdate",()=>{ if(!cur)return; const t=audio.currentTime, W=cur.words;
  let lo=0,hi=W.length-1,i=-1; while(lo<=hi){const m=(lo+hi)>>1; if(W[m][0]<=t){i=m;lo=m+1}else hi=m-1;}
  if(i===lastI)return;
  const a=Math.min(lastI,i), b=Math.max(lastI,i);
  for(let k=Math.max(0,a);k<=b&&k<spans.length;k++){spans[k].classList.toggle("past",k<i);spans[k].classList.remove("now");}
  if(i<lastI) spans.forEach((s,k)=>s.classList.toggle("past",k<i));
  lastI=i; if(i<0)return; const s=spans[i]; s.classList.add("now");
  const top=s.offsetTop-tr.clientHeight/2; tr.scrollTop=Math.max(0,top);
  // follow the crew: most recent FEATURE tag at or before i
  let ft=null; for(const tg of cur.tags){ if(tg.i>i)break; if(tg.f&&FBY[tg.f])ft=tg; }
  if(ft&&ft.f!==followF){followF=ft.f; const f=FBY[ft.f]; showFeature(f); const fl=$("follow"); fl.hidden=false; fl.textContent="Following the crew → "+f.name;}
});
audio.addEventListener("pause",()=>{$("follow").hidden=true});

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
  if(d<12){showFeature(f); setTab("ask"); guideCard(f,"You tapped near "+f.name+".");}
  else { setTab("ask"); guideText(`That spot is ${Math.abs(p.lat).toFixed(0)}° ${p.lat>=0?"north":"south"}, ${Math.abs(p.lon).toFixed(0)}° ${p.lon>=0?"east":"west"}. No named place in my list is close. Try a darker or brighter patch!`);}
}

// open on a real moment: the crew's view of Orientale
try{const t=localStorage.getItem("atm-tab"); if(t&&$("pane-"+t))setTab(t);}catch(e){}
showFeature(FBY.orientale,{dist:3.3});
})();
