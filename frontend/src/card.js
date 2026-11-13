// The guide's answer card: place, the spoken line (the caption), source chips, option/crew buttons, Arc read-out.
// Only the latest answer, plus a one-step "Previous" toggle. No chat log.

/** Arc Tagger read-out as one quiet line. */
export function readoutLine(r) {
  const x = (r && r.readout) || {}, bits = [];
  if (x.available) {
    if (x.act && x.act.length) bits.push("act: " + x.act.join(", "));
    if (x.mentions && x.mentions.length) bits.push("heard: " + x.mentions.join(", "));
    if (x.hard_pii && x.hard_pii.length) bits.push("private: " + x.hard_pii.join(", "));
    if (x.ms != null) bits.push(x.ms + " ms");
  } else if (r && r.source !== "tap") bits.push("Arc Tagger offline: rules only");
  if (r && r.corrected) bits.push("self-correction");
  if (r && r.action) bits.push(r.action.toUpperCase());
  if (r && r.source) bits.push("via " + r.source);
  return bits.length ? "Arc · " + bits.join(" · ") : "";
}

function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

export function createCard() {
  const $ = id => document.getElementById(id);
  const card = $("card"), title = $("cardTitle"), asked = $("cardAsked"), sayEl = $("cardSay"), note = $("cardNote"),
    claims = $("cardClaims"), actions = $("cardActions"), arc = $("cardArc"), prevBtn = $("cardPrev");
  let cur = null, prev = null, showingPrev = false, gen = 0;

  function render(e) {
    title.textContent = e.title || "Guide";
    title.classList.toggle("is-place", !!e.place);
    asked.textContent = e.asked ? "“" + e.asked + "”" : ""; asked.hidden = !e.asked;
    sayEl.textContent = e.say || "";
    note.textContent = e.note || ""; note.hidden = !e.note;
    claims.textContent = "";
    (e.claims || []).filter(c => c && c.text && (c.status === "verified" || c.status === "impression")).forEach(c => {
      const imp = c.status !== "verified";
      const s = el("span", "chip-claim" + (imp ? " is-impression" : ""), imp ? "crew impression" : (c.source || "checked"));
      s.title = c.text; claims.append(s);
    });
    claims.hidden = !claims.childElementCount;
    actions.textContent = "";
    (e.actions || []).forEach(a => actions.append(button(a)));
    actions.hidden = !actions.childElementCount;
    arc.textContent = e.arc || ""; arc.hidden = !e.arc;
    prevBtn.hidden = !prev; prevBtn.textContent = showingPrev ? "Latest" : "Previous";
    prevBtn.setAttribute("aria-pressed", showingPrev);
    card.hidden = false;
  }

  function button(a) {
    const b = el("button", "pill" + (a.hot ? " hot" : ""), a.label); b.type = "button";
    b.onclick = () => { if (a.once) actions.querySelectorAll("button").forEach(x => { x.disabled = true; }); a.onClick(); };
    if (a.onPreview) { b.onmouseenter = a.onPreview; b.onfocus = a.onPreview; }
    return b;
  }

  prevBtn.onclick = () => { showingPrev = !showingPrev; render(showingPrev ? prev : cur); };
  $("cardClose").onclick = () => { card.hidden = true; };

  return {
    /** Show a new answer. Returns a token; pass it to addAction so late buttons land on the right answer. */
    show(entry) {
      if (cur && !cur.transient) prev = cur;
      cur = { ...entry, actions: [...(entry.actions || [])] }; showingPrev = false; render(cur); return ++gen;
    },
    addAction(token, action) {
      if (token !== gen || !cur) return;
      cur.actions.unshift(action); if (!showingPrev) render(cur);
    },
    hide() { card.hidden = true; },
  };
}
