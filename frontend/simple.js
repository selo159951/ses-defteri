/* Ses Defteri Basit: plain Turkish wording, a big "choose file" button and the remaining-time text.
   Loaded after i18n.js and before app.js, so the texts below replace the full app's ones. */
Object.assign(I18N.tr, {
  app: "Ses Defteri",
  drop: "Videoyu ya da ses kaydını buraya sürükleyip bırak",
  browse: "dosya seç", jq_ph: "Kayıtlarda ara",
  eta_total: "yaklaşık {d} sürecek", eta_left: "yaklaşık {d} kaldı",
  dur_s: "{n} saniye", dur_m: "{n} dakika", dur_h: "{h} saat {m} dakika",
  st_paused: "Duraklatıldı", st_queued: "Sırada", resume: "Devam et",
});
Object.assign(I18N.en, {
  app: "Ses Defteri",
  drop: "Drag a video or a sound recording here",
  eta_total: "about {d}", eta_left: "about {d} left",
  dur_s: "{n} sec", dur_m: "{n} min", dur_h: "{h} h {m} min",
});
const SIMPLE_TEXT = {
  tr: { pick: "Dosya seç", hint: "Bitince konuşmalar kişilere ayrılmış olarak burada görünür. Kaydetmek için kaydı açıp \"Dışa aktar\"a bas." },
  en: { pick: "Choose a file", hint: "When it is done, the conversation appears here split by speaker. Open it and press \"Export\" to save it." },
};

/* remaining time while a recording is processed (watch() in app.js asks for it) */
(() => {
  function dur(s) {
    s = Math.max(0, Math.round(s));
    if (s < 60) return t("dur_s", { n: Math.max(5, Math.round(s / 5) * 5) });
    const m = Math.round(s / 60);
    return m < 60 ? t("dur_m", { n: m }) : t("dur_h", { h: Math.floor(m / 60), m: m % 60 });
  }
  const est = {};
  window.etaText = (j, secs, overall) => {
    if (!j.duration || j.status !== "running") return "";
    if (!(j.id in est)) {
      est[j.id] = null;
      call("estimate", j.duration).then((e) => (est[j.id] = e)).catch(() => {});
    }
    const e = est[j.id];
    if (!e) return "";
    if (overall < 0.12) return t("eta_total", { d: dur(Math.max(e.seconds - secs, e.seconds * 0.3)) });
    return t("eta_left", { d: dur((secs * (1 - overall)) / overall) });
  };
})();

/* a real button instead of the small "choose" link, plus one line of explanation */
document.addEventListener("DOMContentLoaded", () => {
  const drop = document.getElementById("drop");
  const link = document.getElementById("browseBtn");
  const pick = Object.assign(document.createElement("button"), { type: "button", className: "pickbtn", textContent: SIMPLE_TEXT.tr.pick });
  const hint = Object.assign(document.createElement("p"), { className: "simplehint", textContent: SIMPLE_TEXT.tr.hint });
  pick.onclick = (e) => { e.preventDefault(); e.stopPropagation(); link.click(); };
  link.closest("p").hidden = true;
  drop.querySelector(".big").after(pick, hint);
  // very first start: the two bundled sample recordings are processed by themselves (test + example result)
  (window.firstRunGate || Promise.resolve())
    .then(() => call("start_samples_once"))
    .then((r) => { if (r && r.length) window.onJobsStarted(r); })
    .catch(() => {});
});
