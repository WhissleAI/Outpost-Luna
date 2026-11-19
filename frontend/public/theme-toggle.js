// The theme toggle (index.html): kept out of main.js so it works even when the backend is down. A file, not an inline
// script: the desktop app's Content-Security-Policy allows scripts from our own origin only (desktop/main/hardening.js).
(function(){
  var root=document.documentElement, btn=document.getElementById("themeBtn");
  var mq=window.matchMedia&&matchMedia("(prefers-color-scheme: dark)");
  function current(){return root.dataset.theme||(mq&&mq.matches?"dark":"light")}
  function sync(){var d=current()==="dark";btn.setAttribute("aria-label",d?"Switch to light mode":"Switch to dark mode");btn.dataset.mode=d?"dark":"light"}
  btn.addEventListener("click",function(){var n=current()==="dark"?"light":"dark";root.dataset.theme=n;try{localStorage.setItem("atm-theme",n)}catch(e){}sync()});
  if(mq&&mq.addEventListener)mq.addEventListener("change",sync);
  sync();
})();
