// Theme before first paint (index.html <head>): a saved choice wins; first run is dark (0.4). A file, not an inline
// script: the desktop app's Content-Security-Policy allows scripts from our own origin only (desktop/main/hardening.js).
try{var t=localStorage.getItem("atm-theme"),p=null;try{p=JSON.parse(localStorage.getItem("outpost-prefs")||"null")}catch(e){}
if(t!=="light"&&t!=="dark")t=p&&(p.theme==="system"||p.theme==="light")?(p.theme==="light"?"light":""):"dark";if(t)document.documentElement.dataset.theme=t}catch(e){}
