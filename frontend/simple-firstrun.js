/* Ses Defteri Basit: first-start screen. When the speech model is not on the computer yet, the backend downloads it
   by itself (no question, no choice) and this full-window screen tells the user what is happening: title, why,
   a big bar, "1,1 GB / 2,2 GB", speed and the remaining time. No internet or any error: a plain message and a
   "Tekrar dene" button. window.firstRunGate resolves when the screen is gone (the tour waits for it).
   Backend: first_run_status() / start_first_run_download(). Styles: #firstrun in simple.css. */
(() => {
  const $ = (id) => document.getElementById(id);
  const root = $("firstrun");
  let resolveGate;
  window.firstRunGate = new Promise((r) => (resolveGate = r));
  if (!root) { resolveGate(); return; }

  const num = (n, d) => n.toFixed(d).replace(".", ",");
  function size(b) {
    if (b >= 1e9) return num(b / 1e9, 1) + " GB";
    if (b >= 1e6) return num(b / 1e6, b >= 100e6 ? 0 : 1) + " MB";
    return Math.max(0, Math.round(b / 1e3)) + " KB";
  }
  function left(s) {
    if (s == null) return "";
    if (s < 45) return "bir dakikadan az kaldı";
    const m = Math.round(s / 60);
    if (m < 60) return `yaklaşık ${m} dakika kaldı`;
    const h = Math.floor(m / 60), r = m % 60;
    return r ? `yaklaşık ${h} saat ${r} dakika kaldı` : `yaklaşık ${h} saat kaldı`;
  }
  function setIcon(name) { const b = $("frIcon"); b.replaceChildren(ic(name)); }

  let timer = 0, finishing = false, shown = false;

  function show() {
    if (shown) return;
    shown = true;
    root.hidden = false;
    document.body.classList.add("frActive");
    document.querySelectorAll("body > header, body > main, body > footer").forEach((e) => e.setAttribute("inert", ""));
    root.setAttribute("tabindex", "-1");
    root.focus({ preventScroll: true });
  }
  function hide() {
    root.hidden = true;
    document.body.classList.remove("frActive");
    document.querySelectorAll("body > [inert]").forEach((e) => e.removeAttribute("inert"));
    clearInterval(timer);
    try { if (typeof loadJobs === "function") loadJobs(); } catch (_) {}
    resolveGate();
  }

  function render(st) {
    const pct = st.total ? Math.min(100, (st.done / st.total) * 100) : 0;
    $("frFill").style.width = pct.toFixed(1) + "%";
    $("frBytes").textContent = `${size(st.done)} / ${size(st.total)}`;
    $("frPct").textContent = `%${Math.floor(pct)}`;
    root.querySelector(".frbar").setAttribute("aria-valuenow", String(Math.floor(pct)));
    const failed = st.state === "error" || st.state === "no_internet";
    const done = st.state === "done" || !st.needed;
    root.classList.toggle("failed", failed);
    root.classList.toggle("ok", done);
    $("frErr").hidden = !failed;
    $("frKeep").hidden = failed || done;
    $("frWhy").hidden = done || failed;
    if (failed) {
      setIcon(st.kind === "no_internet" ? "wifi-off" : "alert");
      $("frTitle").textContent = st.kind === "no_internet" ? "İnternete bağlanılamadı" : "İndirme tamamlanamadı";
      $("frErrText").textContent = st.error || "";
      $("frInfo").textContent = "";
    } else if (done) {
      setIcon("check");
      $("frTitle").textContent = "Hazır";
      $("frInfo").textContent = "";
    } else {
      setIcon("download");
      $("frTitle").textContent = "İlk açılış: ses tanıma modeli indiriliyor";
      if (st.retrying) $("frInfo").textContent = "Bağlantı koptu, yeniden deneniyor…";
      else if (st.speed > 0) $("frInfo").textContent = `${size(st.speed)}/sn · ${left(st.eta)}`;
      else $("frInfo").textContent = "Hız hesaplanıyor…";
    }
    $("frInfo").hidden = !$("frInfo").textContent;
    $("frItems").replaceChildren(...(st.items || []).map((it) => {
      const li = document.createElement("li");
      li.className = it.complete ? "done" : "";
      if (it.complete) li.append(ic("check"), " ");
      li.append(`${it.label} (${size(it.total)})`);
      return li;
    }));
  }

  async function poll() {
    let st;
    try { st = await call("first_run_status"); } catch (_) { return; }
    render(st);
    if ((st.state === "done" || !st.needed) && !finishing) {
      finishing = true;
      setTimeout(hide, 1400);
    }
  }

  async function begin() {
    let st;
    try { st = await call("first_run_status"); } catch (_) { return resolveGate(); }
    if (!st.needed) return resolveGate();
    show();
    render(st);
    try { st = await call("start_first_run_download"); render(st); } catch (_) {}
    timer = setInterval(poll, 500);
  }

  $("frRetry").onclick = async () => {
    $("frRetry").disabled = true;
    try { render(await call("start_first_run_download")); } catch (_) {}
    setTimeout(() => { $("frRetry").disabled = false; }, 1500);
  };
  begin();
})();
