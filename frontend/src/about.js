// The concept brief as an in-app drawer (<dialog>): About button opens it, close button / Esc / backdrop close it.
export function initAbout() {
  const dlg = document.getElementById("about"), btn = document.getElementById("aboutBtn");
  btn.onclick = () => { dlg.showModal(); dlg.querySelector(".about-body").scrollTop = 0; btn.setAttribute("aria-expanded", "true"); };
  document.getElementById("aboutClose").onclick = () => dlg.close();
  dlg.addEventListener("close", () => { btn.setAttribute("aria-expanded", "false"); btn.focus(); });
  dlg.addEventListener("click", e => { if (e.target === dlg) dlg.close(); });   // backdrop
}
