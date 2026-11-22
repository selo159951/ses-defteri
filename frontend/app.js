const $ = (id) => document.getElementById(id);
const fmt = (s) => {
  s = Math.floor(s);
  return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60].map((n) => String(n).padStart(2, "0")).join(":");
};
// forgiving search: i, ı, İ, I all match each other (same length, so offsets stay valid)
const fold = (s) => s.replace(/[İIı]/g, "i").toLowerCase();
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const el = (tag, props = {}, ...kids) => { const e = Object.assign(document.createElement(tag), props); e.append(...kids); return e; };
const plural = (n, one, many) => (n === 1 ? t(one) : t(many, { n }));
let job = null, stopAt = null, dirty = {}, saveTimer = null, segSpk = {}, spkNames = {};
let undoStack = [], gpuState = null;

/* Backend calls go straight to Python through pywebview's bridge - there is no web server. */
const bridgeReady = new Promise((res) => (window.pywebview?.api ? res() : window.addEventListener("pywebviewready", res, { once: true })));
bridgeReady.then(() => window.splash?.step(55, "bridge"));
async function call(name, ...args) { await bridgeReady; return window.pywebview.api[name](...args); }
const MEDIA = "https://media.sesdefteri";

/* Wrap every occurrence of q (folded) in <mark>, safely (no innerHTML). */
function marked(text, q) {
  const out = [], f = fold(text), fq = fold(q);
  let i = 0;
  for (let k = fq ? f.indexOf(fq) : -1; k >= 0; k = f.indexOf(fq, k + fq.length)) {
    out.push(text.slice(i, k), el("mark", { textContent: text.slice(k, k + fq.length) }));
    i = k + fq.length;
  }
  out.push(text.slice(i));
  return out;
}

/* ================= home ================= */
let jobsTimer = null, jobsLoaded = false;

async function loadJobs() {
  const q = $("jq").value.trim();
  if (window.semActive?.(q)) return window.semLoad(q); // search by meaning (search.js) takes over the list
  if (!jobsLoaded) skeleton($("jobs"), "list"); // first load: rows in the shape of the list
  let list = await call("list_jobs", q);
  const langs = [...new Set(list.map((j) => j.language).filter(Boolean))].sort();
  const lf = $("jLang"), curLang = lf.value;
  lf.replaceChildren(new Option(t("all_languages"), ""), ...langs.map((l) => new Option(l.toUpperCase(), l)));
  lf.value = langs.includes(curLang) ? curLang : "";
  const st = $("jStatus").value, lang = lf.value;
  list = list.filter((j) => (!st || (st === "running" ? ["running", "queued"].includes(j.status) : j.status === st)) && (!lang || j.language === lang));
  const sorters = {
    new: (a, b) => b.created - a.created, old: (a, b) => a.created - b.created,
    name: (a, b) => a.filename.localeCompare(b.filename, LANG),
    long: (a, b) => (b.duration || 0) - (a.duration || 0), short: (a, b) => (a.duration || 0) - (b.duration || 0),
  };
  list.sort(sorters[$("jSort").value]);
  $("jobCount").textContent = list.length ? `(${list.length})` : "";
  const box = $("jobsEmpty"), filtered = q || st || lang;
  box.hidden = !!list.length;
  if (!list.length) {
    box.replaceChildren(emptyState("folder", t(filtered ? "no_match_title" : "no_rec_title"), t(filtered ? "no_match_rec" : "no_rec"),
      filtered ? null : { label: t("browse"), onclick: browse }));
    if (q) window.semOffer?.(box, q); // no keyword hit: offer the search by meaning
  } else box.replaceChildren();
  $("jobs").replaceChildren(...list.map((j) => jobRow(j, q)));
  if (!jobsLoaded) { jobsLoaded = true; if (list.length) fadeIn($("jobs")); }
}

function jobRow(j, q) {
  const open = (segId) => {
    if (j.status !== "done") return watch(j.id, j.filename);
    openJob(j.id).then(() => { if (q && j.matches?.length) { $("q").value = q; refreshSearch(false); jumpToSeg(segId ?? j.matches[0].seg); } });
  };
  const title = el("a", { href: "#", className: "jtitle" }, ...marked(j.filename, j.name_match ? q : ""));
  title.onclick = (e) => { e.preventDefault(); open(); };
  const status = { done: "st_done", error: "st_error", running: "st_running", queued: "st_queued", interrupted: "st_interrupted", paused: "st_paused" }[j.status];
  const meta = [new Date(j.created * 1000).toLocaleString(LANG), j.duration ? mmss(j.duration) : null,
    j.language?.toUpperCase(), j.speakers?.length ? j.speakers.map(displayName).join(", ") : null,
    j.lines ? plural(j.lines, "line_1", "lines_n") + (j.edited ? " · " + t("edited_n", { n: j.edited }) : "") : null]
    .filter(Boolean).join("  ·  ");
  const badge = el("span", { className: "badge " + j.status, textContent: status ? t(status) : j.status, title: j.error || "" });
  // small analysis badge when the backend includes an analysis field (older jobs have none)
  const anState = j.analysis?.state;
  const anBadge = anState === "queued" || anState === "running"
    ? el("span", { className: "badge queued", textContent: t("badge_analysing") })
    : anState === "done" ? el("span", { className: "badge done", textContent: t("badge_analysis_ready") }) : null;
  const info = el("div", { className: "jinfo" }, el("div", {}, title, " ", badge, ...(anBadge ? [" ", anBadge] : [])),
    el("div", { className: "jmeta", textContent: meta }));
  if (q) { // where the search term was found
    const where = [];
    if (j.name_match) where.push(t("in_name"));
    if (j.speaker_match?.length) where.push(t("in_speakers", { s: j.speaker_match.map(displayName).join(", ") }));
    if (j.count) where.push(plural(j.count, "hit_1", "hits_n"));
    if (where.length) info.append(el("div", { className: "jwhere", textContent: where.join("  ·  ") }));
    for (const m of j.matches || []) {
      const a = el("a", { href: "#", className: "jsnip", title: t("open_line") },
        el("span", { className: "jtime", textContent: fmt(m.start) }), " ",
        el("b", { textContent: displayName(m.speaker) + ": " }), ...marked(m.text, q));
      a.onclick = (e) => { e.preventDefault(); open(m.seg); };
      info.append(a);
    }
    if (j.more) info.append(el("div", { className: "jwhere", textContent: t("more_n", { n: j.more }) }));
  }
  const ren = el("button", { textContent: t("rename"), className: "small" });
  ren.onclick = async () => {
    const name = prompt(t("rename_prompt"), j.filename);
    if (name && name.trim() && name !== j.filename) { await call("rename_job", j.id, name); loadJobs(); }
  };
  const del = el("button", { textContent: t("delete"), className: "small" });
  del.onclick = async () => { if (confirm(t("delete_confirm", { name: j.filename }))) { await call("delete_job", j.id); loadJobs(); } };
  const btns = el("div", { className: "jbtns" }, ren, j.status === "queued" ? "" : del); // waiting in line: cancel (below) instead of delete
  if (j.status === "running" || j.status === "queued") {
    const pz = el("button", { className: "small" }, icText("pause", t("pause")));
    pz.onclick = async () => { try { await call("pause_job", j.id); } catch {} loadJobs(); };
    const cx = el("button", { className: "small" }, icText("x", t("cancel_job")));
    cx.onclick = () => cancelJob(j.id, j.filename);
    btns.prepend(pz, cx);
  }
  if (j.status === "interrupted" || j.status === "paused") {
    const res = el("button", { textContent: t("resume"), className: "small primary" });
    res.onclick = () => resume(j.id);
    btns.prepend(res);
  }
  return el("li", {}, info, btns);
}
$("jq").oninput = () => { clearTimeout(jobsTimer); jobsTimer = setTimeout(loadJobs, 250); };
for (const id of ["jStatus", "jLang", "jSort"]) $(id).onchange = loadJobs;

/* Files are read from disk by path: dropped files are handled by Python (it gets the full path),
   "browse" opens the native Open dialog (several files allowed). Both end up in onJobsStarted; files are processed
   one at a time in the order they were given. */
let watching = null, watchState = "", batch = 0, lastQueueSig = "";
const DEAD = ["paused", "error", "interrupted", "done"];
window.onJobStarted = (r) => {
  if (!r || !r.id) return;
  batch++;
  // do not take the box away from a recording that is really running: the box follows the running one
  if (watching === null || watching === r.id || DEAD.includes(watchState)) watch(r.id, r.filename);
  else loadJobs();
};
/* several files at once: the list comes back in the order they were started; files that cannot be used are explained */
window.onJobsStarted = (list) => {
  const bad = (list || []).filter((r) => r.skipped);
  (list || []).filter((r) => r.id).forEach(window.onJobStarted);
  if (bad.length) showNote(bad.map((r) => t("skip_" + r.code, { name: r.filename }) || r.error).join("\n"));
  loadJobs();
};
function showNote(text) {
  const n = $("pnote");
  n.textContent = text;
  n.hidden = false;
  clearTimeout(showNote.t);
  showNote.t = setTimeout(() => { n.hidden = true; }, 9000);
}
window.onJobError = (msg) => {
  if (watching !== null && !DEAD.includes(watchState)) return showNote(t("upload_failed") + msg);
  watching = null; $("progress").hidden = false; $("pfill").style.width = "0%"; $("pstage").textContent = t("upload_failed") + msg;
};
async function browse() {
  try { const r = await call("pick_and_start"); window.onJobsStarted(Array.isArray(r) ? r : r && r.id ? [r] : []); } catch (e) { onJobError(e.message || e); }
}

async function resume(id) {
  try { onJobStarted(await call("resume_job", id)); } catch (e) { onJobError(e.message || e); }
}

async function cancelJob(id, name) {
  if (!confirm(t("cancel_job_confirm", { name }))) return;
  try { await call("cancel_job", id); } catch {}
  if (watching === id) { watching = null; $("progress").hidden = true; }
  loadJobs();
}
$("pPause").onclick = async () => { if (watching) { try { await call("pause_job", watching); } catch {} } };
$("pResume").onclick = () => { if (watching) resume(watching); };
$("pCancel").onclick = () => { if (watching) cancelJob(watching, $("pname").textContent.split("  ·  ")[0]); };

/* a waiting recording is cancelled from the queue line or its row (nothing was done for it yet, so no confirmation) */
async function cancelQueued(id) {
  try { await call("cancel_job", id); } catch (e) { /* already gone */ }
  [0, 700, 2000].forEach((ms) => setTimeout(() => { loadJobs(); pollQueue(); }, ms));
}

/* "Waiting (2): a.mp4 [Cancel], b.wav [Cancel]" under the progress box */
function renderQueue(q) {
  const box = $("pqueue"), items = q.queued || [];
  box.hidden = !items.length;
  if (!items.length) return box.replaceChildren();
  const parts = [el("span", { className: "qlabel", textContent: t("queue_waiting", { n: items.length }) + " " })];
  items.forEach((it, i) => {
    const b = el("button", { type: "button", className: "small qcancel", textContent: t("queue_cancel"), title: t("queue_cancel_title", { name: it.filename }) });
    b.onclick = () => cancelQueued(it.id);
    parts.push(el("span", { className: "qitem" }, it.filename + " ", b), i < items.length - 1 ? ", " : "");
  });
  box.replaceChildren(...parts);
}

/* Noise-cleanup question (A/B popup): the running recording waits for "use cleaned" / "use original".
   Both play buttons play the same short excerpt; only one plays at a time. */
let askKey = null, askTimer = null;
function abStop() {
  [$("abAudO"), $("abAudC")].forEach((a) => a.pause());
  [["abPlayO", "abAudO"], ["abPlayC", "abAudC"]].forEach(([b]) => { $(b).classList.remove("on"); $(b).dataset.icon = "play"; });
  hydrateIcons($("abDlg"));
}
function abPlay(btn, aud) {
  const other = btn === "abPlayO" ? "abAudC" : "abAudO";
  const a = $(aud);
  if (!a.paused) return abStop();
  abStop();
  a.currentTime = 0; a.play().catch(() => {});
  $(btn).classList.add("on"); $(btn).dataset.icon = "pause"; hydrateIcons($("abDlg"));
  a.onended = abStop;
}
$("abPlayO").onclick = () => abPlay("abPlayO", "abAudO");
$("abPlayC").onclick = () => abPlay("abPlayC", "abAudC");
$("abDlg").addEventListener("cancel", (e) => e.preventDefault()); // Esc does not dismiss: a choice is needed (or the timeout decides)
async function abAnswer(cleaned) {
  const id = askKey?.split("|")[0];
  abStop();
  try { await call("answer_noise", id, cleaned, $("abDont").checked); } catch (e) { /* the poll closes the popup */ }
  closeAsk();
  try { lastSettings = await call("get_settings"); renderDenoise(); } catch (e) { /* shown next time */ }
}
$("abUseC").onclick = () => abAnswer(true);
$("abUseO").onclick = () => abAnswer(false);
function closeAsk() {
  clearInterval(askTimer); askTimer = null; askKey = null;
  abStop();
  if ($("abDlg").open) $("abDlg").close();
}
function showAsk(ask) {
  if (!ask) { if (askKey) closeAsk(); return; }
  const key = ask.id + "|" + ask.deadline;
  if (key === askKey) return;
  closeAsk(); askKey = key;
  const src = (f) => `${MEDIA}/${ask.id}/${f}?v=${Math.round(ask.deadline)}`;
  $("abAudO").src = src(ask.original); $("abAudC").src = src(ask.cleaned);
  $("abDont").checked = false;
  $("abDesc").textContent = t("ab_desc", { name: ask.filename, s: 12 });
  $("abInfo").textContent = t("ab_info", { snr: ask.snr, thr: ask.threshold });
  const tick = () => {
    const s = Math.max(0, Math.round(ask.deadline - Date.now() / 1000));
    $("abTimer").textContent = t("ab_timer", { s, choice: t(ask.auto ? "ab_choice_clean" : "ab_choice_orig") });
  };
  tick(); askTimer = setInterval(tick, 1000);
  if (!$("abDlg").open) $("abDlg").showModal();
}

/* keeps the queue line and the list fresh, and gives the box back to the running recording
   (for instance after the one in the box was cancelled) */
async function pollQueue() {
  let q;
  try { q = await call("get_queue"); } catch (e) { return; }
  const sig = (q.running?.id || "") + "|" + (q.queued || []).map((x) => x.id).join(",");
  if (sig !== lastQueueSig) { lastQueueSig = sig; if (!$("home").hidden) loadJobs(); }
  renderQueue(q);
  showAsk(q.ask);
  if (!q.running && !(q.queued || []).length && watching === null) batch = 0;
  if (watching === null && q.running && !$("home").hidden) watch(q.running.id, q.running.filename);
}
setInterval(pollQueue, 1500);

/* The progress box follows the recording that is really running: a queued one hands over to the running one,
   and when the running one finishes the box moves on to the next without opening the finished page. */
function watch(id, name) {
  watching = id; watchState = "";
  $("progress").hidden = false; $("pname").textContent = name;
  const t0 = Date.now();
  const tick = async () => {
    if (watching !== id) return; // another file took over the progress box
    let j;
    try { j = await call("get_job", id); } catch (e) {
      if (/not found/i.test(String(e?.message || e))) { watching = null; $("progress").hidden = true; return loadJobs(); } // cancelled
      return setTimeout(tick, 2000);
    }
    watchState = j.status;
    if (j.status === "queued") {
      let q = null;
      try { q = await call("get_queue"); } catch (e) { /* try again next second */ }
      if (watching !== id) return;
      if (q?.running && q.running.id !== id) return watch(q.running.id, q.running.filename);
    }
    const paused = j.status === "paused";
    $("pPause").hidden = paused; $("pResume").hidden = !paused;
    $("progress").classList.toggle("paused", paused); // the moving microphone rests while paused
    const secs = Math.round((Date.now() - t0) / 1000);
    const asrP = j.progress || 0, diaP = j.dprogress || 0;
    const active = j.stage === "transcribing" || j.stage === "diarizing";
    // transcription and speaker separation can run at the same time; show both
    const overall = active ? 0.6 * asrP + 0.4 * diaP : j.stage === "done" ? 1 : 0.03;
    $("pfill").style.width = Math.round(overall * 100) + "%";
    $("pfill").classList.toggle("indeterminate", !active && j.status === "running");
    if (paused) {
      $("pfill").classList.remove("indeterminate");
      $("pstage").textContent = `${t("st_paused")}  ·  ${t("stage_" + j.stage)}`;
      return loadJobs();
    }
    if (j.status === "error") { $("pstage").textContent = t("error") + ": " + j.error; return loadJobs(); }
    if (j.status === "done") return finished(id);
    const dev = { cuda: "NVIDIA GPU", vulkan: "GPU (Vulkan)", cpu: "CPU" }[j.device];
    $("pname").textContent = dev ? `${name}  ·  ${dev}` : name;
    const parts = j.parts?.length > 1 ? " " + t("part_n", { i: j.part || 1, n: j.parts.length }) : "";
    const bits = active
      ? [`${t("stage_transcribing")} ${Math.round(asrP * 100)}%${parts}`, diaP > 0 || j.stage === "diarizing" ? `${t("stage_diarizing")} ${Math.round(diaP * 100)}%` : null]
      : [t("stage_" + j.stage)];
    const eta = window.etaText?.(j, secs, overall);
    $("pstage").textContent = `${bits.filter(Boolean).join("  ·  ")}  (${fmt(secs)} ${t("elapsed")})` + (eta ? `  ·  ${eta}` : "");
    setTimeout(tick, 1000);
  };
  tick();
}

async function finished(id) {
  loadJobs();
  let q = { queued: [] };
  try { q = await call("get_queue"); } catch (e) { /* treat as empty */ }
  const next = q.running || (q.queued || [])[0];
  if (next) return watch(next.id, next.filename); // more are waiting: go on, do not jump into the finished page
  const n = batch;
  batch = 0; watching = null; watchState = "";
  $("progress").hidden = true; $("pqueue").hidden = true;
  if (n <= 1) openJob(id); // one file in this round: show it as before
}

/* ================= transcript state ================= */
async function openJob(id) {
  // switch pages at once and show placeholder lines; the recording (can be long) loads behind them
  $("home").hidden = true; $("view").hidden = false; $("player").hidden = false; $("homeBtn").hidden = false;
  for (const p of PAGES) $(p).hidden = true; // e.g. a search result opened while a page was showing
  $("title").textContent = ""; $("speakers").replaceChildren(); skeleton($("segs"), "lines");
  let j;
  try { j = await call("get_job", id); }
  catch (e) { $("segs").replaceChildren(); throw e; }
  undoStack = []; updateUndo();
  $("title").textContent = j.filename + (j.language ? `  (${j.language})` : "");
  $("audio").src = `${MEDIA}/${id}/audio.mp3`;
  $("q").value = ""; $("fSpk").value = ""; $("fEdited").checked = false; $("fMatch").checked = false;
  applyJob(j);
  fadeIn($("segs"));
  window.analysisHooks?.opened(j); // analysis.js: stop polling, back to the Metin tab
}

function applyJob(j) {
  // edit calls return the job without the one-off "learned" report; keep it for this recording
  if (j && j.learned === undefined && job && job.id === j.id) j.learned = job.learned;
  job = j; dirty = {}; segSpk = {}; spkNames = { ...j.speakers };
  for (const s of job.segments) spkNames[s.speaker] ??= `Speaker ${s.speaker + 1}`;
  renderSpeakers(); renderSegs(); updateExportOptions();
}

const spkIds = () => Object.keys(spkNames).map(Number).sort((a, b) => a - b);
const spkClass = (i) => "spk s" + (i % 6);
/* Default labels are stored as "Speaker N" and shown in the UI language. */
const displayName = (name) => { const m = /^(?:Speaker|Konuşmacı) (\d+)$/.exec(name || ""); return m ? t("speaker_n", { n: m[1] }) : name; };
const spkLabel = (i) => displayName(spkNames[i]);

/* Snapshot before any structural change, so it can be undone. */
async function checkpoint() {
  await save();
  undoStack.push(JSON.stringify({ segments: job.segments, speakers: spkNames }));
  if (undoStack.length > 50) undoStack.shift();
  updateUndo();
}
function updateUndo() { $("undoBtn").disabled = !undoStack.length; }

/* Save the whole transcript (used after add / delete / merge / undo …). */
async function commit(msg, undoable = true) {
  $("saved").textContent = t("saving");
  // text_original/words are sent so an undone delete gets its model text back;
  // the server ignores them for lines it already has.
  const segments = job.segments.map(({ id, start, end, speaker, text_edited, text_original, words }) =>
    ({ id, start, end, speaker, text_edited, text_original: text_original || "", words: words || [] }));
  const j = await call("replace_transcript", job.id, segments, spkNames);
  $("saved").textContent = t("saved");
  applyJob(j);
  if (msg) toast(msg, undoable);
}

async function undo() {
  if (!undoStack.length) return;
  await save();
  const snap = JSON.parse(undoStack.pop());
  updateUndo();
  job.segments = snap.segments; spkNames = snap.speakers;
  await commit(t("undone"), false);
}

function toast(msg, withUndo = false, action = null) {
  const b = $("toastUndo");
  b.textContent = action ? action.label : t("undo_short");
  b.onclick = () => { $("toast").hidden = true; action ? action.run() : undo(); };
  $("toastMsg").textContent = msg; b.hidden = !(withUndo || action); $("toast").hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => ($("toast").hidden = true), withUndo || action ? 7000 : 3500);
}
$("undoBtn").onclick = undo;

/* ================= speakers ================= */
function renderSpeakers() {
  const box = $("speakers"); box.replaceChildren(t("speakers") + " ");
  const total = job.segments.reduce((s, x) => s + (x.end - x.start), 0) || 1;
  for (const i of spkIds()) {
    const mine = job.segments.filter((s) => s.speaker === i);
    const talk = mine.reduce((s, x) => s + (x.end - x.start), 0);
    const inp = el("input", { value: spkLabel(i), title: t("rename_speaker") });
    inp.onchange = async () => {
      await checkpoint();
      spkNames[i] = inp.value.trim() || `Speaker ${i + 1}`;
      commit(t("renamed_to", { s: spkLabel(i) }));
    };
    // "⋯" menu: move all lines to another speaker / remove an unused speaker
    const menu = el("div", { className: "popmenu" });
    const others = spkIds().filter((j) => j !== i);
    if (mine.length && others.length) {
      menu.append(el("div", { className: "menulabel", textContent: t("move_all_to") }));
      for (const j of others) {
        const b = el("button", { className: "small " + spkClass(j), textContent: spkLabel(j) });
        b.onclick = async () => {
          if (!confirm(t("move_confirm", { n: mine.length, a: spkLabel(i), b: spkLabel(j) }))) return;
          await checkpoint();
          for (const s of mine) s.speaker = j;
          commit(t("moved_n", { n: mine.length, b: spkLabel(j) }));
        };
        menu.append(b);
      }
    }
    if (!mine.length) {
      const del = el("button", { className: "small" }, icText("x", t("remove_speaker")));
      del.onclick = async () => { await checkpoint(); delete spkNames[i]; commit(t("speaker_removed")); };
      menu.append(del);
    }
    if (mine.length) {
      const only = el("button", { className: "small" }, icText("file-text", t("only_export")));
      only.onclick = () => { more.open = false; exportOnly(i); };
      menu.append(only);
    }
    window.peopleHooks?.speakerMenu(i, menu); // people.js: "Save to People"
    const more = el("details", { className: "menu spkmore" }, el("summary", { textContent: "⋯", title: t("speaker_menu") }), menu);
    const stats = el("span", { className: "stats", textContent: mine.length ? `${mmss(talk)} · ${Math.round((talk / total) * 100)}% · ${plural(mine.length, "line_1", "lines_n")}` : t("no_lines") });
    const card = el("div", { className: "spkcard " + spkClass(i) + (mine.length ? "" : " unused") },
      el("div", { className: "spkline" }, inp, more), stats);
    window.peopleHooks?.speakerCard(i, card); // people.js: "%82" badge / "Selim olabilir?"
    box.append(card);
  }
  const add = el("button", { className: "icon", textContent: "+", title: t("add_speaker_title") });
  add.onclick = async () => {
    await checkpoint();
    const n = Math.max(-1, ...spkIds()) + 1; spkNames[n] = `Speaker ${n + 1}`;
    commit(t("added_speaker", { s: spkLabel(n) }));
  };
  const det = el("button", { className: "icon", title: t("detect_names") + " - " + t("detect_title") }, ic("user-search"));
  det.onclick = detectNames;
  box.append(el("div", { className: "spkbtns" }, add, det));
  renderExportWho();
  const learned = (job.learned || []).filter((x) => x.action === "created" || x.action === "enriched");
  if (learned.length) {
    const names = learned.map((x) => x.name);
    const shown = names.slice(0, 6).join(", ") + (names.length > 6 ? ", ..." : "");
    box.append(el("p", { className: "hint learnedline", textContent: t(names.length === 1 ? "learned_1" : "learned_n", { n: names.length, s: shown }) }));
  }
  const gseen = new Set(), gpairs = [];
  for (const g of job.glossary_changes || []) {
    const k = g.from + "\u0000" + g.to;
    if (!gseen.has(k)) { gseen.add(k); gpairs.push(g.from + " > " + g.to); }
  }
  if (gpairs.length) {
    const shown = gpairs.slice(0, 6).join(", ") + (gpairs.length > 6 ? ", ..." : "");
    box.append(el("p", { className: "hint learnedline", textContent: t("glossary_applied", { s: shown }) }));
  }
  const f = $("fSpk"), cur = f.value;
  f.replaceChildren(new Option(t("all_speakers"), ""));
  for (const i of spkIds()) f.add(new Option(spkLabel(i), i));
  f.value = [...f.options].some((o) => o.value === cur) ? cur : "";
}

async function detectNames() {
  await checkpoint();
  const r = await call("detect_names", job.id);
  const found = Object.entries(r.found).map(([k, v]) => `${spkLabel(k) || t("speaker_n", { n: +k + 1 })}: ${v}`);
  if (!found.length) { undoStack.pop(); updateUndo(); }
  applyJob(r.job);
  toast(found.length ? t("names_found", { s: found.join(", ") }) : t("no_names"), !!found.length);
}

/* ================= lines ================= */
/* ---- lines to check: the speech model's word confidence and how sure the speaker decision was ----
   Red must be rare and worth a look: the model is often unsure about ordinary words that are right, so common and
   short words are almost never marked; names and unusual words are judged more strictly. */
const RV = { shortRed: 0.05, wordRed: 0.2, wordYellow: 0.45, nameRed: 0.3, nameYellow: 0.6,
             lineRed: 0.55, lineYellow: 0.78, spkRed: -0.05, spkYellow: 0.0 };
const COMMON = new Set(("the and that this with have from they will would there their what about which when your said each she how out other many then them these some her " +
  "would make like him into time has look two more write see number way could people than first water been call who its now find long down day did get come made may part " +
  "yes yeah okay well just very also really thank thanks please hello right sure good great nice fine point since because think know want going here where over after before " +
  "bir bu şu ve ama için gibi çok daha evet hayır tamam peki şimdi sonra önce zaten yani işte belki hiç kadar çünkü ancak fakat veya ile değil var yok").split(" "));
let reviewOnly = false;
const segOf = (row) => job.segments.find((x) => "seg" + x.id === row.id);
/* 0 fine | 1 yellow (check) | 2 red (probably wrong); sentStart: capitalised words at a sentence start are not names */
function wordLevel(tx, p, sentStart) {
  const w = tx.trim().replace(/^[^\p{L}]+|[^\p{L}]+$/gu, "");
  if (!w || typeof p !== "number") return 0;
  if (w.length <= 3 || COMMON.has(w.toLowerCase())) return p < RV.shortRed ? 2 : 0;
  const name = !sentStart && /^\p{Lu}/u.test(w);
  if (p < (name ? RV.nameRed : RV.wordRed)) return 2;
  return p < (name ? RV.nameYellow : RV.wordYellow) ? 1 : 0;
}
function* wordLevels(s) {  // [index, level] for every word with its own mark
  let start = true;
  for (let i = 0; i < s.words.length; i++) {
    const tx = s.words[i][2];
    const lv = wordLevel(tx, s.words[i][3], start);
    if (lv) yield [i, lv];
    start = /[.!?…]\s*$/.test(tx);
  }
}
/* -> { level: 0 none | 1 medium (yellow) | 2 low (red), reasons: [..] }; a line the user edited is no longer in doubt */
function reviewOf(s) {
  const reasons = [];
  let level = 0;
  const edited = s.text_original && s.text_edited !== s.text_original;
  if (!edited && s.words?.length && typeof s.words[0][3] === "number") {
    let red = 0, yellow = 0;
    for (const [, lv] of wordLevels(s)) lv === 2 ? red++ : yellow++;
    if ((typeof s.conf === "number" && s.conf < RV.lineRed) || red >= 2) { level = 2; reasons.push(t("rv_text")); }
    else if ((typeof s.conf === "number" && s.conf < RV.lineYellow) || red >= 1 || yellow >= 2) { level = 1; reasons.push(t("rv_text")); }
  }
  if (typeof s.spk_conf === "number") {
    if (s.spk_conf < RV.spkRed) { level = 2; reasons.push(t("rv_spk")); }
    else if (s.spk_conf < RV.spkYellow) { level = Math.max(level, 1); reasons.push(t("rv_spk")); }
  }
  return { level, reasons };
}
function paintConfidence() {  // word level: coloured ranges inside the unedited text (the CSS highlight API leaves the text itself alone)
  if (!hl) return;
  const low = [], mid = [];
  for (const row of $("segs").children) {
    const s = segOf(row);
    if (!s || !s.words?.length || s.text_edited !== s.text_original) continue;
    const node = row.querySelector(".txt")?.firstChild;
    if (!node || node.nodeType !== 3 || node.textContent !== s.text_original) continue;
    const raw = s.words.map((w) => w[2]).join(""), lead = raw.length - raw.trimStart().length;
    const starts = [];
    let pos = 0;
    for (const w of s.words) { starts.push(pos); pos += w[2].length; }
    for (const [i, lv] of wordLevels(s)) {
      const tx = s.words[i][2];
      const a = starts[i] - lead + (tx.length - tx.trimStart().length), b = starts[i] - lead + tx.length;
      if (a >= 0 && b <= node.length && b > a) {
        const r = new Range(); r.setStart(node, a); r.setEnd(node, b);
        (lv === 2 ? low : mid).push(r);
      }
    }
  }
  CSS.highlights.set("lc-low", new Highlight(...low));
  CSS.highlights.set("lc-mid", new Highlight(...mid));
}
function refreshReview() {
  let n = 0;
  for (const row of $("segs").children) {
    const s = segOf(row); if (!s) continue;
    const r = reviewOf(s);
    row.classList.toggle("rv-low", r.level === 2); row.classList.toggle("rv-mid", r.level === 1);
    row.querySelector(".chip").title = r.reasons.length ? t("play_part") + " - " + r.reasons.join(" / ") : t("play_part");
    if (r.level) n++;
  }
  $("reviewBar").hidden = n === 0 && !reviewOnly;
  $("reviewOnly").textContent = t("rv_only_n", { n });
  $("reviewOnly").classList.toggle("active", reviewOnly);
  paintConfidence();
}
$("reviewOnly").onclick = () => { reviewOnly = !reviewOnly; applyFilters(); refreshReview(); };

function renderSegs() {
  const box = $("segs"); box.replaceChildren();
  for (const s of job.segments) {
    const row = el("div", { className: "seg", id: "seg" + s.id });
    const chip = el("button", { className: "chip", textContent: `${fmt(s.start)} – ${fmt(s.end)}`, title: t("play_part") });
    chip.onclick = () => playRange(s.start, s.end);
    const sel = el("select", { className: spkClass(s.speaker) });
    for (const i of spkIds()) sel.add(new Option(spkLabel(i), i, false, i === s.speaker));
    sel.onchange = async () => { await checkpoint(); s.speaker = +sel.value; delete s.spk_conf; commit(t("line_given", { s: spkLabel(s.speaker) })); };
    const txt = el("div", { className: "txt", contentEditable: "true", spellcheck: true, textContent: s.text_edited });
    txt.dataset.placeholder = t("type_here");
    const isNew = !s.text_original;
    const rev = el("button", { className: "small", textContent: t("revert"), title: t("revert_title") });
    const mark = () => {
      const ch = !isNew && s.text_edited !== s.text_original;
      row.classList.toggle("edited", ch); row.classList.toggle("added", isNew); rev.hidden = !ch;
    };
    txt.oninput = () => { s.text_edited = txt.innerText.replace(/\n+/g, " ").trim(); (dirty.texts ??= {})[s.id] = s.text_edited; mark(); scheduleSave(); refreshSearch(false); refreshReview(); };
    txt.onkeydown = (e) => { if (e.ctrlKey && e.key === "Enter") { e.preventDefault(); playRange(s.start, s.end); } };
    rev.onclick = () => { s.text_edited = s.text_original; txt.textContent = s.text_original; (dirty.texts ??= {})[s.id] = s.text_edited; mark(); scheduleSave(); refreshReview(); };
    const act = el("div", { className: "actions" }, rev,
      btn("plus", t("add_line"), () => addLine(s)),
      btn("merge-up", t("merge_up"), () => mergeUp(s)),
      btn("trash", t("delete_line"), () => deleteLine(s)));
    mark();
    row.append(chip, sel, txt, act); box.append(row);
  }
  refreshSearch(false); // re-apply filters and search highlights on the new nodes
  refreshReview();
}
const btn = (icon, title, fn) => { const b = el("button", { className: "small icon", title }, ic(icon)); b.onclick = fn; return b; };

async function addLine(s) {
  await checkpoint();
  const i = job.segments.indexOf(s), next = job.segments[i + 1];
  const id = Math.max(...job.segments.map((x) => x.id)) + 1;
  const start = s.end, end = next ? Math.max(start, next.start) : start + 3;
  job.segments.splice(i + 1, 0, { id, start, end, speaker: s.speaker, text_edited: "", text_original: "" });
  await commit(t("line_added"), true);
  $("seg" + id)?.querySelector(".txt").focus();
}

async function mergeUp(s) {
  const i = job.segments.indexOf(s);
  if (i === 0) return toast(t("first_line"));
  await checkpoint();
  const prev = job.segments[i - 1];
  prev.text_edited = [prev.text_edited, s.text_edited].filter(Boolean).join(" ");
  prev.end = Math.max(prev.end, s.end);
  job.segments.splice(i, 1);
  commit(t("merged", { s: spkLabel(prev.speaker) }));
}

async function deleteLine(s) {
  await checkpoint();
  job.segments.splice(job.segments.indexOf(s), 1);
  commit(t("line_deleted"));
}

function scheduleSave() { $("saved").textContent = t("saving"); clearTimeout(saveTimer); saveTimer = setTimeout(save, 600); }
async function save() {
  clearTimeout(saveTimer);
  if (!job || (!dirty.texts && !Object.keys(segSpk).length)) return;
  try {
    await call("save_edits", job.id, dirty.texts || {}, segSpk);
    dirty = {}; segSpk = {}; $("saved").textContent = t("saved");
  } catch (e) { $("saved").textContent = t("save_failed"); }
}

/* ================= search / filter ================= */
let matches = [], matchIdx = -1;
const hl = window.Highlight && CSS.highlights;

function refreshSearch(jump = true) {
  const q = fold($("q").value.trim());
  matches = [];
  if (q) {
    for (const row of $("segs").children) {
      const node = row.querySelector(".txt").firstChild;
      if (!node || node.nodeType !== 3) continue;
      const text = fold(node.textContent);
      for (let k = text.indexOf(q); k >= 0; k = text.indexOf(q, k + q.length)) {
        const r = new Range(); r.setStart(node, k); r.setEnd(node, k + q.length);
        matches.push({ row, r });
      }
    }
  }
  applyFilters();
  matches = matches.filter((m) => !m.row.hidden);
  if (jump || matchIdx < 0 || matchIdx >= matches.length) matchIdx = matches.length ? 0 : -1;
  paintMatches(jump);
}

function paintMatches(scroll) {
  $("qCount").textContent = $("q").value.trim() ? (matches.length ? `${matchIdx + 1}/${matches.length}` : "0") : "";
  if (!hl) return;
  CSS.highlights.set("search", new Highlight(...matches.map((m) => m.r)));
  const cur = matches[matchIdx];
  CSS.highlights.set("search-cur", cur ? new Highlight(cur.r) : new Highlight());
  if (cur && scroll) cur.row.scrollIntoView({ block: "center", behavior: "smooth" });
}
function step(d) { if (!matches.length) return; matchIdx = (matchIdx + d + matches.length) % matches.length; paintMatches(true); }
/* Make the first match inside a given line the current one (used from the recordings list). */
function jumpToSeg(segId) {
  const k = matches.findIndex((m) => m.row.id === "seg" + segId);
  if (k >= 0) { matchIdx = k; paintMatches(true); } else $("seg" + segId)?.scrollIntoView({ block: "center" });
  const row = $("seg" + segId); row?.classList.add("flash"); setTimeout(() => row?.classList.remove("flash"), 1600);
}

function applyFilters() {
  const q = fold($("q").value.trim());
  const spk = $("fSpk").value, edOnly = $("fEdited").checked, mOnly = $("fMatch").checked && q;
  let shown = 0;
  for (const row of $("segs").children) {
    const s = job.segments.find((x) => "seg" + x.id === row.id);
    const hide = (spk !== "" && s.speaker !== +spk) ||
      (edOnly && !(row.classList.contains("edited") || row.classList.contains("added"))) ||
      (mOnly && !fold(s.text_edited).includes(q)) ||
      (reviewOnly && !(row.classList.contains("rv-low") || row.classList.contains("rv-mid")));
    row.hidden = hide; if (!hide) shown++;
  }
  $("empty").hidden = shown > 0;
  const n = [$("fEdited").checked, $("fMatch").checked].filter(Boolean).length;
  $("fSum").textContent = n ? t("filters_n", { n }) : t("filters");
  $("fSum").classList.toggle("active", n > 0);
}
$("repToggle").onclick = () => { $("repBox").hidden = !$("repBox").hidden; if (!$("repBox").hidden) $("rep").focus(); };
// close any open dropdown when clicking elsewhere
document.addEventListener("click", (e) => {
  document.querySelectorAll("details.menu[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
});

$("q").oninput = () => refreshSearch(true);
$("q").onkeydown = (e) => {
  if (e.key === "Enter") { e.preventDefault(); step(e.shiftKey ? -1 : 1); }
  if (e.key === "Escape") { $("q").value = ""; refreshSearch(); }
};
$("qNext").onclick = () => step(1); $("qPrev").onclick = () => step(-1);
for (const id of ["fSpk", "fEdited", "fMatch"]) $(id).onchange = () => refreshSearch(false);
$("repAll").onclick = async () => {
  const q = $("q").value.trim();
  if (!q) return toast(t("type_find"));
  const rx = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
  const hits = job.segments.filter((s) => rx.test(s.text_edited) && (rx.lastIndex = 0, true));
  if (!hits.length) return toast(t("nothing_replace"));
  await checkpoint();
  for (const s of hits) s.text_edited = s.text_edited.replace(rx, $("rep").value);
  await commit(plural(hits.length, "replaced_1", "replaced_n"));
  refreshSearch(false);
};

/* ================= give a selected part of a line to another speaker ================= */
let pending = null;
function selectionInLine() {
  const sel = getSelection();
  if (!sel.rangeCount || sel.isCollapsed) return null;
  const r = sel.getRangeAt(0);
  const c = r.commonAncestorContainer;
  const txt = (c.nodeType === 1 ? c : c.parentElement)?.closest(".txt");
  if (!txt) return null;
  const pre = document.createRange(); pre.selectNodeContents(txt); pre.setEnd(r.startContainer, r.startOffset);
  const a = pre.toString().length, b = a + r.toString().length;
  return { txt, a, b, rect: r.getBoundingClientRect() };
}
document.addEventListener("mouseup", (ev) => !ev.target.closest?.("#selPop") && setTimeout(() => {
  const pop = $("selPop"); const s = job && !$("view").hidden && selectionInLine();
  if (!s || !s.txt.textContent.slice(s.a, s.b).trim()) { pop.hidden = true; return; }
  pending = { seg: job.segments.find((x) => "seg" + x.id === s.txt.parentElement.id), a: s.a, b: s.b };
  pop.replaceChildren(el("span", { textContent: t("who_said") }));
  for (const i of spkIds()) {
    const b = el("button", { textContent: spkLabel(i), className: spkClass(i) });
    b.onmousedown = (e) => e.preventDefault(); // keep the selection
    b.onclick = () => splitTo(i);
    pop.append(b);
  }
  pop.hidden = false;
  pop.style.left = Math.max(8, Math.min(s.rect.left, innerWidth - pop.offsetWidth - 8)) + "px";
  pop.style.top = Math.min(s.rect.bottom + 8, innerHeight - pop.offsetHeight - 70) + "px";
}, 0));
document.addEventListener("scroll", () => ($("selPop").hidden = true), true);

async function splitTo(speaker) {
  $("selPop").hidden = true;
  if (!pending) return;
  await checkpoint();
  const { seg, a, b } = pending; pending = null;
  const j = await call("split", job.id, seg.id, a, b, speaker);
  getSelection().removeAllRanges();
  applyJob(j);
  toast(t("given_to", { s: spkLabel(speaker) }), true);
}

/* ================= player ================= */
const audio = $("audio");
function playRange(a, b) { stopAt = b; audio.currentTime = a; audio.play(); }
let lastPlaying = null;
audio.ontimeupdate = () => {
  $("clock").textContent = fmt(audio.currentTime);
  if (stopAt !== null && audio.currentTime >= stopAt) { audio.pause(); stopAt = null; }
  if (!job) return;
  const cur = job.segments.find((s) => audio.currentTime >= s.start && audio.currentTime < s.end);
  const rowEl = cur && !audio.paused ? $("seg" + cur.id) : null;
  if (rowEl === lastPlaying) return;
  lastPlaying?.classList.remove("playing"); rowEl?.classList.add("playing"); lastPlaying = rowEl;
  const editing = document.activeElement?.classList.contains("txt");
  if (rowEl && $("follow").checked && !editing) rowEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
};
const setPP = (playing) => $("pp").replaceChildren(ic(playing ? "pause" : "play"));
audio.onplay = () => setPP(true); audio.onpause = () => setPP(false);
const togglePlay = () => { stopAt = null; audio.paused ? audio.play() : audio.pause(); };
$("pp").onclick = togglePlay;
$("back").onclick = () => (audio.currentTime = Math.max(0, audio.currentTime - 5));
$("fwd").onclick = () => (audio.currentTime += 5);
$("speed").onchange = (e) => (audio.playbackRate = +e.target.value);

/* ================= export ================= */
/* "Analysis" is only offered when the job has a finished analysis; SRT makes no sense for it. */
function updateExportOptions() {
  const anOpt = $("expVersion").querySelector('option[value="analysis"]');
  const ready = job?.analysis?.state === "done";
  anOpt.disabled = !ready;
  anOpt.title = ready ? "" : t("export_analysis_hint");
  $("expAnalysisHint").hidden = ready;
  if (!ready && $("expVersion").value === "analysis") $("expVersion").value = "edited";
  const isAnalysis = $("expVersion").value === "analysis";
  $("expWho").hidden = isAnalysis;
  const srt = $("expFmt").querySelector('option[value="srt"]');
  srt.disabled = isAnalysis;
  if (isAnalysis && $("expFmt").value === "srt") $("expFmt").value = "docx";
}
$("expVersion").onchange = updateExportOptions;

/* "Only one person's words": tick speakers in the export menu (nobody ticked = everyone). */
function renderExportWho() {
  const box = $("expWhoList"), keep = new Set(selectedWho());
  box.replaceChildren();
  for (const i of spkIds()) {
    if (!job.segments.some((s) => s.speaker === i)) continue;
    const cb = el("input", { type: "checkbox", value: i, checked: keep.has(i) });
    box.append(el("label", { className: "chk " + spkClass(i) }, cb, el("span", { textContent: spkLabel(i) })));
  }
}
const selectedWho = () => [...$("expWhoList").querySelectorAll("input:checked")].map((c) => +c.value);
function exportOnly(i) {
  renderExportWho();
  for (const c of $("expWhoList").querySelectorAll("input")) c.checked = +c.value === i;
  $("expVersion").value = "edited"; updateExportOptions();
  setTimeout(() => ($("expMenu").open = true), 0); // after the page-wide "click outside closes menus" handler
  toast(t("only_export_set", { s: spkLabel(i) }));
}
function reportSaved(r) {
  if (r.cancelled) return;
  if (r.error) return toast(t("export_failed") + r.error);
  const msg = r.paths.length === 1 ? t("saved_file", { p: r.paths[0] }) : t("saved_files", { n: r.paths.length, p: r.paths[0].replace(/[\\/][^\\/]+$/, "") });
  toast(msg, false, { label: t("show_folder"), run: () => call("reveal", r.paths[0]) });
}
$("expGo").onclick = async () => {
  await save();
  const v = $("expVersion").value, f = $("expFmt").value;
  const who = v === "analysis" ? [] : selectedWho();
  $("expGo").closest("details").open = false;
  reportSaved(await call("save_export", job.id, v, f, LANG, who)); // native "Save as" dialog
};
$("wordBtn").onclick = async () => { // one click: edited transcript as .docx, only the Save dialog in between
  await save();
  try { reportSaved(await call("save_word", job.id, LANG)); } catch (e) { toast(t("export_failed") + (e?.message || e)); }
};

/* ================= GPU status (chip + System page live in system.js) ================= */
function showGpu(st) {
  gpuState = st;
  window.onSysStatus?.(st);
}

/* ================= language & credits ================= */
function renderCredits() {
  const link = el("a", { href: "https://selimoguz.com.tr", className: "ext", textContent: "Selim Oğuz" });
  $("creditsLine").replaceChildren(`${t("idea")}: Umut Akbaş  ·  ${t("developer")}: `, link, ` ${t("and")} Claude`);
}
/* ================= folder watch (off by default) ================= */
let watchSt = null, watchAdded = 0;
function renderWatch() {
  const st = watchSt; if (!st) return;
  $("watchOn").checked = st.enabled;
  $("watchDir").textContent = st.dir || t("watch_none");
  const ind = $("watchInd");
  ind.hidden = !st.enabled;
  if (!st.enabled) return;
  ind.classList.toggle("warn", st.note === "missing");
  const parts = [t("watch_active", { d: st.dir })];
  if (st.note === "missing") parts.push(t("watch_missing"));
  if (st.waiting) parts.push(t("watch_waiting", { n: st.waiting }));
  if (st.queued) parts.push(t("watch_added", { n: st.queued, f: st.last_file }));
  $("watchIndText").textContent = parts.join(" · ");
}
async function refreshWatch() {
  try { const st = await call("get_watch"); if (watchSt && st.queued !== watchSt.queued && !$("home").hidden) loadJobs(); watchSt = st; renderWatch(); } catch {}
}
$("watchPick").onclick = async () => {
  try { watchSt = await call("pick_watch_folder"); renderWatch(); } catch (e) { toast(t("watch_failed") + (e?.message || e)); }
};
$("watchOn").onchange = async (e) => {
  try { watchSt = await call("set_watch", e.target.checked); }
  catch (err) { e.target.checked = false; toast(t("watch_pick_first")); return; }
  renderWatch();
};
setInterval(refreshWatch, 3000);

function setLang(l, persist = true) {
  LANG = I18N[l] ? l : "en";
  $("langSel").value = LANG;
  applyI18n(); renderCredits(); renderWatch(); renderDenoise();
  if (gpuState) showGpu(gpuState);
  if (job && !$("view").hidden) { renderSpeakers(); renderSegs(); updateExportOptions(); } else loadJobs();
  if (persist) call("set_settings", { ui_lang: LANG }).catch(() => {});
  window.dispatchEvent(new Event("langchange"));
}
$("langSel").onchange = (e) => setLang(e.target.value);
$("aboutBtn").onclick = () => $("aboutDlg").showModal();
// external links open in the normal browser, never inside the app window
document.addEventListener("click", (e) => {
  const a = e.target.closest?.("a.ext");
  if (!a) return;
  e.preventDefault();
  call("open_url", a.href);
});

/* ================= keyboard ================= */
document.addEventListener("keydown", (e) => {
  const inView = job && !$("view").hidden;
  const typing = e.target.closest?.(".txt, input, select, textarea");
  if (e.ctrlKey && e.code === "Space" && inView) { e.preventDefault(); togglePlay(); }
  else if (e.ctrlKey && e.key.toLowerCase() === "f" && inView) { e.preventDefault(); $("q").focus(); $("q").select(); }
  else if (e.ctrlKey && e.key.toLowerCase() === "z" && inView && !typing) { e.preventDefault(); undo(); }
  else if (e.altKey && e.key === "ArrowLeft" && inView) { e.preventDefault(); $("back").click(); }
  else if (e.altKey && e.key === "ArrowRight" && inView) { e.preventDefault(); $("fwd").click(); }
  else if (e.key === "Escape") $("selPop").hidden = true;
});
$("helpBtn").onclick = () => $("help").showModal();

/* ================= pages ================= */
/* System, People and Settings are full pages: opening one hides every other view (they used to stay open under
   each other). Pages listen for "pageopen" to tidy up (e.g. stop a voice recording) when another page opens. */
const PAGES = ["system", "people", "settings", "assistant"];
function showPage(id) {
  for (const p of ["home", "view", "player", ...PAGES]) { const e = $(p); if (e) e.hidden = p !== id; }
  $("homeBtn").hidden = false;
  window.dispatchEvent(new CustomEvent("pageopen", { detail: id }));
}

/* ================= wiring ================= */
$("homeBtn").onclick = async () => { await save(); audio.pause(); $("view").hidden = true; $("player").hidden = true; $("home").hidden = false; $("homeBtn").hidden = true; job = null; loadJobs(); };
$("browseBtn").onclick = (e) => { e.preventDefault(); browse(); };
const drop = $("drop");
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());
window.addEventListener("beforeunload", () => save());

/* Meeting mode: transcription also starts the analysis in the background. */
$("meetingMode").onchange = (e) => call("set_settings", { meeting_mode: e.target.checked }).catch(() => {});
$("learnPeople").onchange = (e) => call("set_settings", { learn_people: e.target.checked }).catch(() => {});
$("denoiseMode").onchange = (e) => call("set_settings", { denoise: e.target.value }).catch(() => {});
$("denoiseAsk").onchange = (e) => call("set_settings", { denoise_ask: e.target.checked }).catch(() => {});
let lastSettings = null;
function renderDenoise() {
  const st = lastSettings;
  if (!st) return;
  $("denoiseAsk").checked = st.denoise_ask !== false;
  $("dnThr").textContent = st.denoise_answers
    ? t("dn_thr", { v: st.denoise_threshold, n: st.denoise_answers }) : t("dn_thr_default", { v: st.denoise_threshold ?? 8 });
  $("dnReset").disabled = !st.denoise_answers;
}
$("dnReset").onclick = async () => { try { lastSettings = await call("reset_denoise_threshold"); renderDenoise(); } catch (e) { /* ignore */ } };
$("langMode").onchange = (e) => call("set_settings", { language: e.target.value }).catch(() => {});

window.splash?.step(70, "settings");
call("get_settings")
  .then((st) => {
    showGpu(st);
    $("meetingMode").checked = !!st.meeting_mode;
    $("learnPeople").checked = st.learn_people !== false;
    $("langMode").value = st.language || "auto";
    refreshWatch();
    $("denoiseMode").value = st.denoise || "auto";
    lastSettings = st; renderDenoise();
    setLang(st.ui_lang || (navigator.language.startsWith("tr") ? "tr" : "en"), false);
  })
  .catch(() => setLang("tr", false))
  .finally(() => window.splash?.done());

/* "Seçenekler": the drop-area settings sit behind one button; next to it a short line says which ones are on */
(() => {
  const box = $("optsBox");
  if (!box) return;
  const names = [["meetingMode", "meeting_mode"], ["learnPeople", "learn_people"], ["watchOn", "watch_on"]];
  const sum = () => {
    const on = names.filter(([id]) => $(id) && $(id).checked).map(([, k]) => t(k));
    $("optsSum").textContent = on.length ? t("opts_on", { list: on.join(", ") }) : "";
  };
  box.addEventListener("change", sum);
  setInterval(sum, 1500);  // settings are filled in after start-up and by the folder watch
  // a popup: the dark backdrop (the details element itself), the close button or Esc closes it
  box.addEventListener("click", (e) => { if (e.target === box) box.open = false; });
  $("optsClose").onclick = () => { box.open = false; };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && box.open) box.open = false; });
})();
