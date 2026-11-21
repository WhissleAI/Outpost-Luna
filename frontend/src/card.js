// The guide's answer card: place, the spoken line (the caption), source chips, option/crew buttons, Arc read-out.
// Only the latest answer, plus a one-step "Previous" toggle. No chat log.
import { maskProfanity } from "./profanity.js";

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
    claims = $("cardClaims"), actions = $("cardActions"), arc = $("cardArc"), prevBtn = $("cardPrev"),
    eyebrow = $("cardEyebrow"), meta = $("cardMeta"), img = $("cardImg"), story = $("cardStory"), more = $("cardMore"),
    moreBody = $("cardMoreBody"), crew = $("cardCrew"), sources = $("cardSources"), lessons = $("cardLessons");
  let cur = null, prev = null, showingPrev = false, gen = 0;

  function render(e) {
    title.textContent = e.title || "Guide";
    title.classList.toggle("is-place", !!e.place);
    asked.textContent = e.asked ? "“" + maskProfanity(e.asked) + "”" : ""; asked.hidden = !e.asked;   // [P0] kid text
    // The Director often answers a hardware question with the artifact's own story; don't print it twice.
    const flat = t => String(t || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    const dupStory = e.artifact && e.artifact.story && flat(e.say) && flat(e.artifact.story).startsWith(flat(e.say).slice(0, 60));
    // [qa] nor the status line the hardware row already shows ("Bottom half still sitting at Tranquility Base")
    const dupStatus = e.artifact && e.artifact.status && flat(e.say) === flat(e.artifact.status);
    sayEl.textContent = e.say || ""; sayEl.hidden = !e.say || !!dupStory || !!dupStatus;
    renderArtifact(e);
    note.textContent = e.note || ""; note.hidden = !e.note;
    lessons.textContent = "";
    if (e.lessons && e.lessons.length) {
      lessons.append(el("b", "", "Lessons from past missions"));
      const ul = el("ul");
      e.lessons.forEach(l => { const li = el("li", "", l.text + " "); if (l.source && l.source.url) { const a = el("a", "chip-src", l.source.title || "source"); a.href = l.source.url; a.target = "_blank"; a.rel = "noopener"; li.append(a); } ul.append(li); });
      lessons.append(ul);
    }
    lessons.hidden = !lessons.childElementCount;
    claims.textContent = "";
    // [qa] a verified claim whose sources the hardware list already links adds nothing; a long "A; B; C" source shows A.
    const listed = new Set(((e.artifact && e.artifact.sources) || []).map(x => flat(x && x.title)));
    (e.claims || []).filter(c => c && c.text && (c.status === "verified" || c.status === "impression"))
      .filter(c => c.status !== "verified" || !c.source || !String(c.source).split(";").every(x => listed.has(flat(x)))).forEach(c => {
      const imp = c.status !== "verified", src = String(c.source || "").split(";")[0].trim();
      const s = el("span", "chip-claim" + (imp ? " is-impression" : ""), imp ? "crew impression" : (src || "checked"));
      s.title = c.text; claims.append(s);
    });
    claims.hidden = !claims.childElementCount;
    actions.textContent = "";
    (e.actions || []).forEach(a => actions.append(button(a)));
    actions.hidden = !actions.childElementCount;
    arc.textContent = e.arc || ""; arc.hidden = !e.arc;
    prevBtn.hidden = !prev || !!e.tour;   // [flows] a tour card has its own Previous (the stop before)
    prevBtn.textContent = showingPrev ? "Latest" : "Previous";
    prevBtn.setAttribute("aria-pressed", showingPrev);
    card.hidden = false;
  }

  /** Hardware story parts: eyebrow, mission/year/agency row, image, first-person story, More, crew, sources. */
  function renderArtifact(e) {
    const a = e.artifact;
    eyebrow.textContent = e.eyebrow || ""; eyebrow.hidden = !e.eyebrow;
    title.classList.toggle("is-hw", !!a);
    title.dataset.hw = a ? a.hw || "lander" : "";
    meta.textContent = ""; story.textContent = ""; moreBody.textContent = ""; crew.textContent = ""; sources.textContent = "";
    img.hidden = true; more.open = false; img.title = "";
    if (!a) { [meta, story, more, crew, sources].forEach(x => { x.hidden = true; }); renderPhoto(e); return; }
    if (a.agency) meta.append(el("span", "agency", a.agency));
    const bits = [a.mission, a.landed ? "landed " + a.landed.slice(0, 4) : "", a.status].filter(Boolean);
    meta.append(el("span", "", bits.join(" · ")));
    meta.hidden = false;
    if (a.image) { img.src = a.image; img.alt = a.name; img.hidden = false; img.onerror = () => { img.hidden = true; }; }
    story.textContent = a.story || ""; story.hidden = !a.story;
    [["What it did", a.what_it_did], ["Science", a.science]].forEach(([h, t]) => { if (t) { moreBody.append(el("b", "", h)); moreBody.append(el("p", "", t)); } });
    more.hidden = !moreBody.childElementCount;
    const names = (a.crew || []).filter(Boolean);
    if (names.length) { crew.append(el("b", "", "Crew ")); crew.append(names.join(", ")); }
    crew.hidden = !names.length;
    (a.sources || []).filter(x => x && x.url).forEach(x => {
      const l = el("a", "chip-src", x.title || new URL(x.url).hostname); l.href = x.url; l.target = "_blank"; l.rel = "noopener"; sources.append(l);
    });
    sources.hidden = !sources.childElementCount;
  }

  /** [courses] A real photo on a place / library card (field_library.js): the picture, its credit line, its sources. */
  function renderPhoto(e) {
    const p = e.photo;
    if (p && p.src) {
      img.src = p.src; img.alt = p.alt || e.title || ""; img.title = p.caption || ""; img.hidden = false; img.onerror = () => { img.hidden = true; };
      if (p.credit) { meta.append(el("span", "photo-credit", (p.creditLabel || "Photo") + ": " + p.credit)); meta.hidden = false; }
    }
    (e.sources || []).filter(x => x && x.url).forEach(x => {
      const l = el("a", "chip-src", x.title || new URL(x.url).hostname); l.href = x.url; l.target = "_blank"; l.rel = "noopener"; sources.append(l);
    });
    sources.hidden = !sources.childElementCount;
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
    /** Patch the current answer in place (e.g. the Director's line arriving after the story card is up). */
    update(token, patch) {
      if (token !== gen || !cur) return;
      Object.assign(cur, patch); if (!showingPrev) render(cur);
    },
    get token() { return gen; },
    addAction(token, action) {
      if (token !== gen || !cur) return;
      cur.actions.unshift(action); if (!showingPrev) render(cur);
    },
    hide() { card.hidden = true; },
  };
}
