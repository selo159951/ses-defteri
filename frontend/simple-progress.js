/* Ses Defteri Basit: the progress box as a step list that explains what is going on.
   app.js watch() polls get_job and calls renderProgress(job, name) once a second.
   Texts are plain Turkish on purpose (this edition has no English interface). */
(() => {
  const STEPS = [
    { title: "Dosya hazırlanıyor" },
    { title: "Ses tanıma modeli yükleniyor" },
    { title: "Konuşmalar yazıya dökülüyor" },
    { title: "Konuşmacılar ayrılıyor" },
    { title: "Bitti" },
  ];
  let rows = null, t0 = 0, busy = null; // busy: "pause" | "cancel" while a request is being carried out
  const pct = (p) => Math.round(Math.min(1, Math.max(0, p || 0)) * 100);
  const secsText = (s) => (s < 3600
    ? `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`
    : fmt(s));
  const $p = (id) => document.getElementById(id);

  function build() {
    $p("psteps").replaceChildren();
    rows = STEPS.map((st) => {
      const ico = el("span", { className: "sico" });
      const detail = el("span", { className: "sdetail" });
      const fill = el("div");
      const mini = el("div", { className: "smini" }, fill);
      const li = el("li", { className: "step waiting" }, ico,
        el("div", { className: "sbody" }, el("span", { className: "stitle", textContent: st.title }), detail, mini));
      $p("psteps").append(li);
      return { li, ico, detail, mini, fill, state: "" };
    });
  }

  function setState(i, state, detail, p) {
    const r = rows[i];
    if (r.state !== state) {
      r.state = state;
      r.li.className = "step " + state;
      r.ico.replaceChildren(state === "done" ? ic("check") : state === "now" ? el("span", { className: "spin" }) : el("span", { className: "ring" }));
    }
    const show = state === "now" || state === "paused";
    r.detail.textContent = show ? detail || "" : "";
    r.mini.hidden = !show;
    r.mini.classList.toggle("indeterminate", show && p == null);
    if (show && p != null) r.fill.style.width = pct(p) + "%";
  }

  function buttons(kind, id) {
    const box = $p("pbtns");
    const sig = kind + (busy || "");
    if (box.dataset.kind === sig) return;
    box.dataset.kind = sig;
    const mk = (text, cls, icon, fn) => {
      const b = el("button", { type: "button", className: "pbtn " + cls }, icText(icon, text));
      b.onclick = fn;
      return b;
    };
    const cancel = () => mk("İptal", "pcancel", "x", async () => {
      if (!confirm("Bu işlem iptal edilsin mi? Yapılan kısım silinir.")) return;
      busy = "cancel";
      try { await call("cancel_job", id); } catch (e) { busy = null; return alert(e.message || e); }
      watching = null; busy = null;
      $p("progress").hidden = true;
      [0, 1500, 4000, 9000].forEach((ms) => setTimeout(loadJobs, ms)); // the job disappears once its current step notices
    });
    if (kind === "run") {
      const pause = mk(busy === "pause" ? "Duraklatılıyor…" : "Duraklat", "ppause", "pause", async () => {
        busy = "pause";
        buttons("run", id);
        try { await call("pause_job", id); } catch (e) { busy = null; buttons("run", id); alert(e.message || e); }
      });
      pause.disabled = busy === "pause";
      box.replaceChildren(pause, cancel());
    } else if (kind === "paused") {
      box.replaceChildren(mk("Devam et", "presume", "play", async () => {
        busy = null;
        try { onJobStarted(await call("resume_job", id)); loadJobs(); } catch (e) { alert(e.message || e); }
      }), cancel());
    } else {
      box.replaceChildren();
    }
  }

  window.progressStart = (id, name) => {
    t0 = Date.now(); busy = null;
    if (!rows) build();
    $p("pname").textContent = name;
    $p("pbtns").dataset.kind = "";
    $p("progress").className = "";
  };

  window.showProgressError = (msg) => {
    if (!rows) build();
    $p("progress").className = "failed";
    $p("pstage").hidden = false;
    $p("pstage").textContent = msg;
    $p("psteps").hidden = true;
    $p("pinfo").textContent = "";
    $p("palive").hidden = true;
    $p("pbtns").replaceChildren();
    $p("pbtns").dataset.kind = "";
  };

  window.renderProgress = (j, name) => {
    if (!rows) build();
    $p("psteps").hidden = false;
    const stage = j.stage, st = j.status;
    const order = { queued: -1, converting: 0, loading_model: 1, transcribing: 2, diarizing: 3 };
    const paused = st === "paused", failed = st === "error" || st === "interrupted", waiting = st === "queued";
    $p("progress").className = paused ? "paused" : failed ? "failed" : "";
    const dev = { cuda: "NVIDIA GPU", vulkan: "GPU", cpu: "işlemci" }[j.device];
    $p("pname").textContent = dev && st === "running" ? `${name}  ·  ${dev}` : name;

    const asr = j.progress || 0, dia = j.dprogress || 0, conv = j.cprogress || 0;
    // the current step; when paused or failed the stage name is gone, so work it out from what was saved
    let cur = order[stage];
    if (cur === undefined || cur < 0) cur = dia > 0 ? 3 : asr > 0 ? 2 : j.audio_ready ? 1 : 0;
    const nParts = (j.parts || []).length;
    const partTxt = nParts > 1 ? `bölüm ${Math.min(j.part || 1, nParts)} / ${nParts}` : "";
    const stateOf = (i) => (waiting ? "waiting" : i < cur ? "done" : i === cur ? (paused ? "paused" : "now") : "waiting");

    setState(0, stateOf(0), conv > 0 ? `%${pct(conv)}` : "Ses okunuyor, bu birkaç dakika sürebilir", conv > 0 ? conv : null);
    setState(1, stateOf(1), j.stage_note === "selftest"
      ? "Bu bilgisayar için en hızlı ayar deneniyor. Bu sadece ilk seferde olur, yaklaşık 1 dakika sürer"
      : "İlk seferde 1-2 dakika sürebilir", null);
    setState(2, stateOf(2), (asr > 0 ? `%${pct(asr)}` : "Başlıyor") + (partTxt ? `  ·  ${partTxt}` : ""), asr > 0 ? asr : null);
    // with a graphics card the speakers are separated at the same time as the text is written
    const diaNow = !waiting && !paused && (cur === 3 || (cur === 2 && dia > 0));
    setState(3, diaNow ? "now" : stateOf(3) === "done" ? "done" : paused && cur === 3 ? "paused" : "waiting",
      dia > 0 ? `%${pct(dia)}` : "Kimin konuştuğu belirleniyor", dia > 0 ? dia : null);
    setState(4, "waiting", "", 0);

    const secs = Math.max(0, Math.round((Date.now() - (j.run_started ? j.run_started * 1000 : t0)) / 1000));
    const overall = Math.min(0.99, 0.05 * conv + (cur >= 1 ? 0.04 : 0) + 0.56 * asr + 0.35 * dia);
    $p("pfill").style.width = pct(overall) + "%";
    $p("pfill").classList.remove("indeterminate");

    let banner = "";
    if (waiting && j.waiting_for) banner = `Sırada bekliyor: önce şu kayıt bitecek: ${j.waiting_for}`;
    else if (waiting) banner = "Başlatılıyor…";
    else if (paused) banner = "Duraklatıldı. Kaldığı yerden sürdürmek için \"Devam et\"e bas.";
    else if (st === "error") banner = "Bir sorun oldu: " + (j.error || "");
    else if (st === "interrupted") banner = "İşlem yarıda kaldı. \"Devam et\"e basarsan kaldığı yerden sürer.";
    else if (busy === "pause") banner = "Duraklatılıyor… bu adım biter bitmez duracak, biraz bekle.";
    $p("pstage").textContent = banner;
    $p("pstage").hidden = !banner;

    const eta = st === "running" && !busy ? window.etaText?.(j, secs, overall) || "" : "";
    $p("pinfo").textContent = paused || failed ? "" : `Geçen süre: ${secsText(secs)}` + (eta ? `  ·  ${eta}` : "");
    const stale = !!j.heartbeat && Date.now() / 1000 - j.heartbeat > 25;
    $p("palive").hidden = paused || failed;
    $p("palive").classList.toggle("stale", stale);
    $p("paliveText").textContent = waiting ? "Sıra gelince kendiliğinden başlayacak"
      : stale ? "Bilgisayar çok meşgul olabilir, biraz daha bekle. Yine de ilerlemezse programı kapatıp aç; kayıt kaldığı yerden sürer."
      : "Çalışıyor, bilgisayarı kapatmayın";
    buttons(failed ? "none" : paused ? "paused" : "run", j.id);
  };
})();
