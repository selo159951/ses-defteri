/* Search by meaning across all recordings (home page). The backend (semantic.py) embeds passages with a small
   local model; here: the toggle next to the search box, the result list and the one-time model download. */
(() => {
  const btn = $("jSem"), box = $("semBox");
  let on = false, seq = 0, pollT = null;
  try { on = localStorage.getItem("semSearch") === "1"; } catch {}
  const mb = (b) => Math.round(b / 1048576) + " MB";
  const paint = () => { btn.setAttribute("aria-pressed", String(on)); btn.classList.toggle("on", on); };
  const remember = () => { try { localStorage.setItem("semSearch", on ? "1" : "0"); } catch {} };
  paint();

  /* app.js asks before drawing the normal list: when this mode is on and something is typed, we draw instead */
  window.semActive = (q) => {
    const act = on && !!q;
    box.hidden = !act; $("jobs").hidden = act;
    if (act) { $("jobsEmpty").hidden = true; $("jobCount").textContent = ""; }
    else { clearTimeout(pollT); seq++; }
    return act;
  };
  btn.onclick = () => { on = !on; paint(); remember(); loadJobs(); };
  /* "No recordings match": offer the same question by meaning */
  window.semOffer = (parent) => {
    const b = el("button", { className: "small", style: "margin-left:8px" }, icText("sparkles", t("sem_offer")));
    b.onclick = () => { on = true; paint(); remember(); loadJobs(); };
    parent.append(b);
  };

  const words = (q) => fold(q).split(/[^\p{L}\p{N}]+/u).filter((w) => w.length >= 3).map((w) => w.slice(0, 5));
  /* mark the words of the question inside a passage (word starts, so suffixes still match) */
  function markWords(text, q) {
    const stems = words(q), out = [];
    if (!stems.length) return [text];
    const f = fold(text), re = /[\p{L}\p{N}]+/gu;
    let i = 0, m;
    while ((m = re.exec(f))) {
      if (stems.some((s) => m[0].startsWith(s))) {
        out.push(text.slice(i, m.index), el("mark", { textContent: text.slice(m.index, m.index + m[0].length) }));
        i = m.index + m[0].length;
      }
    }
    out.push(text.slice(i));
    return out;
  }

  function prepBox(info, q, mine) {
    const dl = info.download || {};
    const size = mb(info.size);
    const kids = [el("div", { textContent: t("sem_need_model", { size }) })];
    if (dl.running) {
      kids.push(el("div", { className: "bar" }, el("div", { style: `width:${Math.round((dl.done / Math.max(dl.total, 1)) * 100)}%` })),
        el("div", { className: "hint", textContent: t("sem_downloading") + " " + mb(dl.done) + " / " + mb(dl.total) }));
      pollT = setTimeout(() => { if (mine === seq) semLoad(q); }, 1000);
    } else {
      const b = el("button", { className: "primary" }, icText("arrow-right", t("sem_download", { size })));
      b.onclick = async () => { try { await call("download_search_model"); } catch (e) { toast(String(e?.message || e)); } semLoad(q); };
      kids.push(b);
      if (dl.error) kids.push(el("div", { className: "hint", textContent: t("sem_dl_error", { e: dl.error }) }));
    }
    return el("div", { className: "semprep" }, ...kids);
  }

  function resultRow(r, q) {
    const a = el("a", { href: "#", className: "semres", title: t("open_line") },
      el("div", { className: "semhead" },
        el("span", { className: "jtitle", textContent: r.filename }),
        el("span", { className: "jtime", textContent: fmt(r.start) }),
        ...(r.speaker ? [el("b", { textContent: displayName(r.speaker) })] : []),
        ...(r.exact ? [el("span", { className: "semexact", textContent: t("sem_exact") })] : [])),
      el("div", { className: "sempass" }, ...markWords(r.text, q)));
    a.onclick = (e) => {
      e.preventDefault();
      openJob(r.job_id).then(() => jumpToSeg(r.seg));
    };
    return el("li", {}, a);
  }

  async function semLoad(q) {
    clearTimeout(pollT);
    const mine = ++seq;
    let info;
    try { info = await call("get_search_info"); } catch { return; }
    if (mine !== seq) return;
    if (!info.downloaded) { box.replaceChildren(prepBox(info, q, mine)); return; }
    let r;
    try { r = await call("semantic_search", q); } catch (e) { toast(String(e?.message || e)); return; }
    if (mine !== seq) return;
    const kids = [];
    if (r.total && r.indexed < r.total) {
      kids.push(el("p", { className: "semnote", textContent: t("sem_indexing", { a: r.indexed, b: r.total }) }));
      pollT = setTimeout(() => { if (mine === seq && on && $("jq").value.trim() === q) semLoad(q); }, 5000);
    }
    kids.push(r.results.length
      ? el("ul", {}, ...r.results.map((x) => resultRow(x, q)))
      : el("p", { className: "hint", textContent: t("sem_none") }));
    box.replaceChildren(...kids);
  }
  window.semLoad = semLoad;
})();
