/* Ses Defteri Basit: first-run guided tour with a spotlight. Short plain-Turkish steps, only elements that are
   on screen are shown. Two tours: "home" (first start) and "job" (the first time a recording is opened).
   "Already shown" is kept in the backend settings (tour_home_done / tour_job_done); the header button
   "Nasıl kullanılır?" shows the tour of the current page again. Styles: #tour rules in style.css and simple.css. */
(() => {
  const SETTING = { home: "tour_home_done", job: "tour_job_done" };
  const q = (s) => document.querySelector(s);

  /* target: selector, function returning an element, or null for a centred card */
  const TOURS = {
    home: [
      { t: "Kaydı buraya ekle", b: "Videoyu ya da ses kaydını bu kutuya sürükleyip bırak. İstersen büyük \"Dosya seç\" düğmesine basıp bilgisayarından seç.",
        target: "#drop" },
      { t: "İlerlemeyi buradan izle", b: "Kayıt başlayınca burada adımlar görünür: hangisi bitti, hangisi şimdi yapılıyor. \"Duraklat\" işi bekletir, \"Devam et\" kaldığı yerden sürdürür. \"İptal\" ise işi tamamen siler.",
        target: () => (visible(q("#progress")) ? q("#progress") : null) },
      { t: "Önceki kayıtların", b: "Yazıya döktüğün her kayıt bu listede durur. Birine tıklayınca açılır. Silmek ya da adını değiştirmek için yanındaki düğmeleri kullan.",
        target: () => (q("#jobs")?.children.length ? q("#jobs") : q(".listhead")) },
      { t: "Kayıtlarda ara", b: "Bir kelime yaz, o kelimenin geçtiği kayıtlar ve cümleler görünsün.",
        target: "#jq" },
    ],
    job: [
      { t: "Konuşmacı adları", b: "Kimin konuştuğu burada yazar. Bir ada tıklayıp gerçek ismini yazabilirsin; tüm konuşmalarda o isim görünür.",
        target: "#speakers" },
      { t: "Konuşmalar", b: "Metni buradan okursun. Bir satıra tıklarsan ses tam o yerden çalar. Yanlış yazılmış bir yeri düzeltmek için üstüne yazabilirsin.",
        target: "#segs" },
      { t: "Ses oynatıcı", b: "Kaydı buradan dinlersin: oynat, durdur, 5 saniye geri ya da ileri git.",
        target: "#player" },
      { t: "Dışa aktar", b: "Metni bir dosya olarak kaydetmek için buna bas. Word, düz yazı ve altyazı gibi biçimler var.",
        target: ".toolbar details.menu" },
    ],
  };

  const PAD = 6, GAP = 14, MARGIN = 12;
  let cur = null;  // { name, steps, i, root, hole, card, prevFocus, timer, raf }

  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  function mk(tag, props = {}, ...kids) {
    const e = Object.assign(document.createElement(tag), props);
    e.append(...kids);
    return e;
  }
  function visible(e) {
    if (!e || e.hidden || !e.getClientRects().length) return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== "hidden";
  }
  function targetOf(step) {
    if (!step.target) return null;
    return typeof step.target === "function" ? step.target() : q(step.target);
  }
  /* a step with a function target that returns null is shown as a centred card; a selector must be on screen */
  const usable = (step) => typeof step.target === "function" || !step.target || visible(targetOf(step));

  function markDone(name) {
    try { call("set_settings", { [SETTING[name]]: true }).catch(() => {}); } catch (_) {}
  }

  function render() {
    const { steps, i, card } = cur;
    const s = steps[i], last = i === steps.length - 1;
    const next = document.createDocumentFragment();
    if (last) next.append(icText("check", "Bitir"));
    else next.append("İleri ", ic("arrow-right"));
    card.replaceChildren(
      mk("div", { className: "tour-count", textContent: `${i + 1} / ${steps.length}` }),
      mk("h3", { id: "tourTitle", textContent: s.t }),
      mk("p", { id: "tourBody", textContent: s.b }),
      mk("div", { className: "tour-btns" },
        mk("button", { className: "tour-skip", type: "button", onclick: () => close(true) }, icText("x", "Atla")),
        mk("span", { className: "spacer" }),
        ...(i > 0 ? [mk("button", { type: "button", onclick: () => go(i - 1, -1) }, icText("arrow-left", "Geri"))] : []),
        mk("button", { className: "primary tour-next", type: "button", onclick: () => (last ? close(true) : go(i + 1, 1)) }, next),
      ));
    card.querySelector(".tour-next").focus({ preventScroll: true });
  }

  function place() {
    if (!cur) return;
    cur.raf = 0;
    const target = targetOf(cur.steps[cur.i]);
    const { hole, card } = cur;
    const vw = innerWidth, vh = innerHeight;
    card.style.width = Math.min(420, vw - 2 * MARGIN) + "px";
    const cw = card.offsetWidth, ch = card.offsetHeight;
    const clamp = (v, lo, hi) => Math.max(lo, Math.min(v, hi));
    if (!target || !visible(target)) {
      hole.hidden = true;
      cur.root.classList.add("dim");
      card.style.left = Math.round((vw - cw) / 2) + "px";
      card.style.top = Math.round(Math.max(MARGIN, (vh - ch) / 2)) + "px";
      return;
    }
    cur.root.classList.remove("dim");
    const r = target.getBoundingClientRect();
    const x0 = Math.max(0, r.left - PAD), y0 = Math.max(0, r.top - PAD);
    const x1 = Math.min(vw, r.right + PAD), y1 = Math.min(vh, r.bottom + PAD);
    hole.hidden = false;
    Object.assign(hole.style, { left: x0 + "px", top: y0 + "px", width: Math.max(0, x1 - x0) + "px", height: Math.max(0, y1 - y0) + "px" });
    const cx = clamp(x0 + (x1 - x0) / 2 - cw / 2, MARGIN, vw - cw - MARGIN);
    const cy = clamp(y0 + (y1 - y0) / 2 - ch / 2, MARGIN, vh - ch - MARGIN);
    const spots = [
      [y1 + GAP + ch <= vh - MARGIN, cx, y1 + GAP],     // below
      [y0 - GAP - ch >= MARGIN, cx, y0 - GAP - ch],     // above
      [x1 + GAP + cw <= vw - MARGIN, x1 + GAP, cy],     // right
      [x0 - GAP - cw >= MARGIN, x0 - GAP - cw, cy],     // left
    ];
    const hit = spots.find((p) => p[0]);
    const [, px, py] = hit || [0, cx, vh - ch - MARGIN]; // a very tall target: bottom of the window, over it
    card.style.left = Math.round(px) + "px";
    card.style.top = Math.round(py) + "px";
  }
  function schedule() { if (cur && !cur.raf) cur.raf = requestAnimationFrame(place); }

  function go(n, dir) {
    // drop steps whose target went missing, then show the nearest one in the travel direction
    while (n >= 0 && n < cur.steps.length && !usable(cur.steps[n])) {
      cur.steps.splice(n, 1);
      if (dir < 0) n--;
    }
    if (n >= cur.steps.length) return close(true);
    if (n < 0) n = 0;
    cur.i = n;
    render();
    const target = targetOf(cur.steps[n]);
    if (target) {
      const tall = target.getBoundingClientRect().height > innerHeight * 0.7;
      target.scrollIntoView({ block: tall ? "start" : "center", inline: "nearest", behavior: reduced() ? "auto" : "smooth" });
    }
    place();
  }

  function onKey(e) {
    if (!cur) return;
    const onButton = e.target instanceof HTMLButtonElement;
    if (e.key === "Escape") close(true);
    else if (e.key === "ArrowRight" || (e.key === "Enter" && !onButton)) { if (cur.i < cur.steps.length - 1) go(cur.i + 1, 1); else close(true); }
    else if (e.key === "ArrowLeft") { if (cur.i > 0) go(cur.i - 1, -1); }
    else if (e.key === "Tab") {  // keep focus inside the card
      const b = [...cur.card.querySelectorAll("button")];
      const at = b.indexOf(document.activeElement);
      b[(at + (e.shiftKey ? -1 : 1) + b.length) % b.length].focus();
    } else return;
    e.preventDefault();
    e.stopImmediatePropagation();
  }

  function close(markIt) {
    if (!cur) return;
    const c = cur;
    cur = null;
    if (markIt) markDone(c.name);
    clearInterval(c.timer);
    cancelAnimationFrame(c.raf);
    removeEventListener("keydown", onKey, true);
    removeEventListener("resize", schedule);
    removeEventListener("scroll", schedule, true);
    c.root.remove();
    try { c.prevFocus?.focus({ preventScroll: true }); } catch (_) {}
  }

  function start(name) {
    if (cur) close(false);
    const steps = TOURS[name].filter(usable);
    if (!steps.length) return;
    const hole = mk("div", { className: "tour-hole" });
    const card = mk("div", { className: "tour-card", role: "dialog" });
    card.setAttribute("aria-modal", "true");
    card.setAttribute("aria-labelledby", "tourTitle");
    card.setAttribute("aria-describedby", "tourBody");
    const root = mk("div", { id: "tour", className: "dim" }, mk("div", { className: "tour-block" }), hole, card);
    document.body.append(root);
    cur = { name, steps, i: 0, root, hole, card, prevFocus: document.activeElement, timer: 0, raf: 0 };
    addEventListener("keydown", onKey, true);
    addEventListener("resize", schedule);
    addEventListener("scroll", schedule, true);
    cur.timer = setInterval(() => {  // layout can change under us (the list loads, panes switch)
      if (!cur) return;
      if (!usable(cur.steps[cur.i])) go(cur.i, 1); else place();
    }, 400);
    go(0, 1);
  }

  const home = () => document.getElementById("home");
  const view = () => document.getElementById("view");
  let jobDone = true;

  function watchView() {
    new MutationObserver(() => {
      if (view().hidden || cur || jobDone) return;
      setTimeout(() => { if (!view().hidden && !cur && !jobDone) { jobDone = true; start("job"); } }, 700);
    }).observe(view(), { attributes: true, attributeFilter: ["hidden"] });
  }

  async function init() {
    for (let n = 0; document.getElementById("splash") && n < 150; n++) await new Promise((r) => setTimeout(r, 200));
    await (window.firstRunGate || Promise.resolve());  // the first-start download screen must be gone first
    let st = {};
    try { st = await call("get_settings"); } catch (_) { return; }
    jobDone = !!st.tour_job_done;
    watchView();
    if (!st.tour_home_done) setTimeout(() => { if (!cur && !home().hidden) start("home"); }, 500);
  }

  window.startTour = (name) => start(name || (!view().hidden ? "job" : "home"));
  const btn = document.getElementById("tourBtn");
  if (btn) btn.onclick = () => window.startTour();
  init();
})();
