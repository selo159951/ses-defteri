/* Record a meeting inside the app: computer sound (Teams / Meet / Zoom) + microphone.
   A red bar under the header stays on every page while recording: time, two level meters, Pause, Stop and
   process, Cancel, and (main edition) the Live text switch with the text panel. Recordings cut off by a crash are
   offered again at start. Uses helpers from app.js ($, el, t, call, toast, loadJobs). */
(() => {
  Object.assign(I18N.en, {
    rec_start: "Record a meeting", rec_start_title: "Records the computer's sound (Teams, Meet, Zoom…) and your microphone",
    rec_on: "Recording", rec_paused: "Paused", rec_pause: "Pause", rec_resume: "Continue",
    rec_stop: "Stop and transcribe", rec_cancel: "Discard", rec_cancel_q: "Discard this recording? It cannot be undone.",
    rec_mic: "Microphone", rec_system: "Computer sound",
    rec_live: "Live text", rec_live_title: "Writes the meeting as text while it is recorded, a few seconds behind. Turn it off if the computer slows down.",
    rec_live_wait: "The text appears here a few seconds after people speak…",
    rec_live_slow: "The computer is busy, so live text was turned off. The recording goes on; the full text is made after Stop.",
    rec_live_busy: "Live text is not available while another recording is being transcribed. The recording itself works.",
    rec_live_error: "Live text stopped: {e}. The recording goes on.",
    rec_live_note: "Preview only: speakers and names are added after Stop.",
    rec_notice: "Before recording, let the other participants know that the meeting is being recorded.\n\nThe recording stays on this computer; nothing is sent anywhere.",
    rec_queued: "Recording saved. It is being transcribed now.",
    rec_failed: "Recording could not start: {e}",
    rec_none: "No microphone or speaker was found.",
    rec_dev_lost: "{d} stopped: {e}",
    rec_leftover: "An unfinished recording was found: {t} ({d}).",
    rec_recover: "Transcribe it", rec_discard: "Delete",
    rec_disk_full: "Recording could not start: only {free} is free. Free some space and try again.",
    meet_detected: "A meeting was detected ({app}). Shall I record it?",
    meet_record: "Record", meet_not_now: "Not this time",
  });
  Object.assign(I18N.tr, {
    rec_start: "Toplantıyı kaydet", rec_start_title: "Bilgisayardan gelen sesi (Teams, Meet, Zoom…) ve mikrofonunuzu birlikte kaydeder",
    rec_on: "Kaydediliyor", rec_paused: "Duraklatıldı", rec_pause: "Duraklat", rec_resume: "Devam et",
    rec_stop: "Durdur ve metne çevir", rec_cancel: "Sil", rec_cancel_q: "Bu kayıt silinsin mi? Geri alınamaz.",
    rec_mic: "Mikrofon", rec_system: "Bilgisayar sesi",
    rec_live: "Canlı yazı", rec_live_title: "Toplantıyı kaydederken birkaç saniye geriden yazıya döker. Bilgisayar yavaşlarsa kapatın.",
    rec_live_wait: "Konuşulanlar birkaç saniye sonra burada yazı olarak çıkar…",
    rec_live_slow: "Bilgisayar zorlandığı için canlı yazı kapatıldı. Kayıt sürüyor; tam metin durdurunca hazırlanır.",
    rec_live_busy: "Başka bir kayıt metne çevrilirken canlı yazı kullanılamaz. Kayıt normal devam eder.",
    rec_live_error: "Canlı yazı durdu: {e}. Kayıt sürüyor.",
    rec_live_note: "Önizlemedir: konuşmacılar ve isimler durdurduktan sonra eklenir.",
    rec_notice: "Kayda başlamadan önce toplantıdaki diğer kişilere kayıt yapıldığını haber verin.\n\nKayıt bu bilgisayarda kalır, hiçbir yere gönderilmez.",
    rec_queued: "Kayıt alındı, şimdi metne çevriliyor.",
    rec_failed: "Kayıt başlatılamadı: {e}",
    rec_none: "Mikrofon ya da hoparlör bulunamadı.",
    rec_dev_lost: "{d} durdu: {e}",
    rec_leftover: "Yarım kalmış bir kayıt bulundu: {t} ({d}).",
    rec_recover: "Metne çevir", rec_discard: "Sil",
    rec_disk_full: "Kayıt başlatılamadı: yalnızca {free} boş. Yer açıp yeniden deneyin.",
    meet_detected: "Toplantı algılandı ({app}). Kaydedeyim mi?",
    meet_record: "Kaydet", meet_not_now: "Bu sefer değil",
  });

  const bar = $("recBar");
  let st = null, timer = null, liveOn = false, lastLiveState = null, shownErr = {};
  const msg = (e) => (e && e.message) || String(e);
  const clock = (s) => { s = Math.floor(s); const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, x = s % 60;
    return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(x).padStart(2, "0"); };
  const dur = (s) => (s >= 3600 ? t("dur_h", { h: Math.floor(s / 3600), m: Math.floor(s / 60) % 60 })
    : s >= 60 ? t("dur_m", { n: Math.round(s / 60) }) : t("dur_s", { n: Math.round(s) }));
  const btn = (key, icon, onclick, cls = "small") => {
    const b = el("button", { type: "button", className: cls, textContent: t(key), onclick });
    b.dataset.icon = icon;
    return b;
  };

  async function start() {
    try {
      const dev = await call("rec_devices");
      if (!dev.settings.rec_notice_done) {
        if (!confirm(t("rec_notice"))) return;
        call("set_settings", { rec_notice_done: true }).catch(() => {});
      }
      st = await call("start_meeting", null);
      if (st && st.error === "disk_full") { toast(t("rec_disk_full", { free: gbText(st.free || 0) })); return; }
      if (st && st.warning) diskWarning(st.warning);  // it started, but a long meeting may not fit
      $("meetBar").hidden = true;  // no need to offer recording while it records
      liveOn = !!(st.live && st.live.state === "running");
      poll();
    } catch (e) { toast(t("rec_failed", { e: msg(e) })); }
  }

  async function poll() {
    clearTimeout(timer);
    try { st = await call("rec_status"); } catch { st = null; }
    render();
    if (st && st.active) timer = setTimeout(poll, 500);
  }
  window.onTrayRecord = () => poll();  // started from the tray icon: show the recording bar

  function meter(name) {
    const lvl = st.levels[name] ?? 0;
    const pct = Math.min(100, Math.round(Math.sqrt(lvl) * 220)); // perceived loudness
    return el("span", { className: "recmeter", title: t(name === "mic" ? "rec_mic" : "rec_system") },
      el("span", { className: "recmeterlbl", textContent: t(name === "mic" ? "rec_mic" : "rec_system") }),
      el("span", { className: "recmeterbar" }, el("span", { style: `width:${pct}%` })));
  }

  function render() {
    document.title = st && st.active ? `● ${t("rec_on")} – ${t("app")}` : t("app");
    $("recBtn").disabled = !!(st && st.active);
    if (!st || !st.active) { if (!bar.dataset.leftover) bar.hidden = true; return; }
    bar.hidden = false; delete bar.dataset.leftover;
    for (const [d, e] of Object.entries(st.errors || {})) {
      if (!shownErr[d]) { shownErr[d] = 1; toast(t("rec_dev_lost", { d: t(d === "mic" ? "rec_mic" : "rec_system"), e })); }
    }
    const live = st.live;
    if (live && live.state !== lastLiveState) {
      if (live.state === "slow") toast(t("rec_live_slow"));
      if (live.state === "error") toast(t("rec_live_error", { e: live.error }));
      lastLiveState = live.state;
    }
    liveOn = !!(live && live.state === "running");
    const head = el("div", { className: "rechead" },
      el("span", { className: "recdot" + (st.paused ? " paused" : "") }),
      el("strong", { textContent: (st.paused ? t("rec_paused") : t("rec_on")) + " " + clock(st.seconds) }),
      ...st.sources.map(meter),
      el("span", { className: "spacer" }));
    if (window.REC_LIVE !== false) {
      const sw = el("input", { type: "checkbox", checked: liveOn });
      sw.onchange = async () => { st = await call("set_live", sw.checked); if (st.live_blocked) toast(t("rec_live_busy")); render(); };
      head.append(el("label", { className: "recswitch", title: t("rec_live_title") }, sw, " " + t("rec_live")));
    }
    head.append(
      btn(st.paused ? "rec_resume" : "rec_pause", st.paused ? "play" : "pause", async () => { st = await call("pause_meeting", !st.paused); render(); }),
      btn("rec_stop", "check", stop, "small primary"),
      btn("rec_cancel", "trash", async () => { if (confirm(t("rec_cancel_q"))) { await call("cancel_meeting"); poll(); } }));
    const kids = [head];
    if (live && (liveOn || live.lines.length)) {
      const box = el("div", { className: "livebox" });
      if (!live.lines.length) box.append(el("p", { className: "hint", textContent: t("rec_live_wait") }));
      for (const l of live.lines.slice(-40)) box.append(el("p", {}, el("span", { className: "jtime", textContent: fmt(l.start) + "  " }), l.text));
      kids.push(box, el("p", { className: "hint livenote", textContent: t("rec_live_note") }));
      requestAnimationFrame(() => (box.scrollTop = box.scrollHeight));
    }
    bar.replaceChildren(...kids);
    hydrateIcons(bar);
  }

  async function stop() {
    try {
      await call("stop_meeting");
      toast(t("rec_queued"));
      shownErr = {}; lastLiveState = null;
      if (!$("home").hidden) loadJobs();
    } catch (e) { toast(t("rec_failed", { e: msg(e) })); }
    poll();
  }

  async function leftovers() {
    let list = [];
    try { list = await call("rec_leftovers"); } catch { return; }
    if (!list.length || (st && st.active)) return;
    const l = list[0];
    bar.hidden = false; bar.dataset.leftover = "1";
    bar.replaceChildren(el("div", { className: "rechead" },
      el("span", { className: "recdot paused" }),
      el("span", { textContent: t("rec_leftover", { t: l.title, d: dur(l.seconds) }) }), el("span", { className: "spacer" }),
      btn("rec_recover", "check", async (e) => {
        bar.querySelectorAll("button").forEach((b) => { b.disabled = true; }); // one click queues it once
        try { await call("recover_recording", l.folder); toast(t("rec_queued")); loadJobs(); } catch (e) { toast(msg(e)); }
        delete bar.dataset.leftover; bar.hidden = true; leftovers();
      }, "small primary"),
      btn("rec_discard", "trash", async () => {
        if (!confirm(t("rec_cancel_q"))) return;
        await call("discard_recording", l.folder); delete bar.dataset.leftover; bar.hidden = true; leftovers();
      })));
    hydrateIcons(bar);
  }

  /* "A meeting has started" suggestion (Settings > Recording): the backend watches whether Teams,
     Zoom, Meet in a browser… has the microphone open. A dismissal is kept until that app lets go. */
  let meetApp = null, meetDismissed = null, meetTimer = null;
  async function pollMeeting() {
    clearTimeout(meetTimer);
    const bar = $("meetBar");
    let d;
    try { d = await call("meeting_detect_status"); }
    catch { meetTimer = setTimeout(pollMeeting, 15000); return; }
    const busy = !d || !d.enabled || !d.active || d.recording || (st && st.active);
    if (busy) {
      meetApp = null;
      if (!d || !d.active || !d.enabled) meetDismissed = null;  // the meeting ended (or the option is off)
      bar.hidden = true; bar.replaceChildren();
      meetTimer = setTimeout(pollMeeting, 5000);
      return;
    }
    if (meetDismissed && meetDismissed !== d.app) meetDismissed = null; // that app stopped: ask for the next meeting again
    if (meetDismissed === d.app) { bar.hidden = true; meetTimer = setTimeout(pollMeeting, 5000); return; }
    if (meetApp !== d.app || !bar.childElementCount) {
      meetApp = d.app;
      bar.replaceChildren(el("div", { className: "rechead" },
        el("span", { className: "recdot" }),
        el("span", { textContent: t("meet_detected", { app: d.app }) }),
        el("span", { className: "spacer" }),
        btn("meet_record", "mic", () => { bar.hidden = true; $("recBtn").click(); }, "small primary"),
        btn("meet_not_now", "x", () => { meetDismissed = d.app; bar.hidden = true; })));
      hydrateIcons(bar);
    }
    bar.hidden = false;
    meetTimer = setTimeout(pollMeeting, 5000);
  }

  $("recBtn").onclick = (e) => { e.preventDefault(); e.stopPropagation(); start(); };
  window.addEventListener("langchange", () => {
    if (st && st.active) render();
    meetApp = null;  // the banner is written in the new language at the next poll
    if (!$("meetBar").hidden) pollMeeting();
  });
  bridgeReady.then(() => { poll(); setTimeout(leftovers, 1500); pollMeeting(); });
})();
