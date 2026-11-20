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
Object.assign(I18N.tr, {
  options: "Seçenekler", opts_on: "açık: {list}", opts_dn: "gürültü temizleme", opts_watch: "klasör izleme",
  save_word: "Word olarak kaydet", save_word_title: "Düzenlenmiş metni tek adımda Word dosyası olarak kaydet",
  only_who: "Sadece bir kişinin söyledikleri", only_who_hint: "Satırlarını istediğin kişileri işaretle. Kimse işaretli değilse herkes alınır.",
  only_export: "Sadece bunu dışa aktar", only_export_set: "Dışa aktarılacak: sadece {s} adlı kişinin satırları. Biçimi seçip kaydet.",
  watch_title: "Klasörü izle", watch_on: "Klasörü izle", watch_hint: "Bu klasöre gelen yeni ses ve video dosyaları kendiliğinden sıraya eklenir. Varsayılan olarak kapalıdır.",
  watch_choose: "Klasör seç", watch_none: "Henüz klasör seçilmedi.", watch_pick_first: "Önce bir klasör seç.",
  watch_active: "İzleniyor: {d}", watch_missing: "Klasöre şu an ulaşılamıyor (USB bellek veya ağ sürücüsü?). Klasör geri gelince izleme devam eder.",
  watch_waiting: "{n} dosya hâlâ yazılıyor…", watch_added: "Klasör izleme ile eklenen: {n} (son: {f})",
  watch_failed: "Klasör izleme başarısız: ",
  denoise_label: "Gürültü temizleme", dn_auto: "Otomatik (gürültülü kayıtlarda sorar)", dn_always: "Her zaman", dn_off: "Kapalı",
  denoise_hint: "Yazıya dökmeden önce arka plan gürültüsünü azaltır. Otomatik modda gürültülü görünen kayıt için kısa bir bölümü iki şekilde dinleyip sen seçersin. Cevapların sınırı öğretir. Dinleme sesi özgün kalır. Her şey bu bilgisayarda olur.",
  dn_ask: "Gürültülü kaydı temizlemeden önce bana sor", dn_reset: "Sıfırla",
  dn_thr: "Öğrenilen gürültü sınırı: {v} dB ({n} cevaptan)", dn_thr_default: "Gürültü sınırı: {v} dB (varsayılan, henüz öğrenme yok)",
  ab_title: "Bu kayıtta arka plan gürültüsü var", ab_desc: "{name}: aynı {s} saniyelik bölümü iki şekilde dinle, sonra yazıya dökmede hangi sesin kullanılacağını seç.",
  ab_orig: "Orijinal ses", ab_clean: "Temizlenmiş ses", ab_use_clean: "Temizlenmiş sesi kullan", ab_use_orig: "Orijinal sesi kullan",
  ab_dont: "Bunu bir daha sorma", ab_info: "Tahmini konuşma/gürültü oranı: {snr} dB (sınır {thr} dB).",
  ab_timer: "{s} sn içinde seçmezsen otomatik karar uygulanır: {choice}.",
  ab_choice_clean: "temizlenmiş ses", ab_choice_orig: "orijinal ses",
});
Object.assign(I18N.en, {
  options: "Options", opts_on: "on: {list}", opts_dn: "noise cleanup", opts_watch: "folder watch",
  save_word: "Save as Word", save_word_title: "Save the edited transcript as a Word file in one step",
  only_who: "Only one person's words", only_who_hint: "Tick the people whose lines you want. Nobody ticked = everyone.",
  only_export: "Export only this person", only_export_set: "Only the lines of {s} will be exported. Pick a format and save.",
  watch_title: "Watch a folder", watch_on: "Watch folder", watch_hint: "New audio and video files in this folder are added to the line by themselves. Off by default.",
  watch_choose: "Choose folder", watch_none: "No folder chosen yet.", watch_pick_first: "Choose a folder first.",
  watch_active: "Watching: {d}", watch_missing: "The folder is not available right now. Watching continues when it is back.",
  watch_waiting: "{n} file(s) still being written…", watch_added: "Added by the folder watch: {n} (last: {f})",
  watch_failed: "Folder watch failed: ",
  denoise_label: "Noise cleanup", dn_auto: "Automatic (asks about noisy recordings)", dn_always: "Always", dn_off: "Off",
  denoise_hint: "Reduces background noise before transcription. In Automatic mode you hear a short excerpt both ways and choose. The playback keeps the original sound. Runs on this PC only.",
  dn_ask: "Ask me before cleaning a noisy recording", dn_reset: "Reset",
  dn_thr: "Learned noise limit: {v} dB (from {n} answers)", dn_thr_default: "Noise limit: {v} dB (default, nothing learned yet)",
  ab_title: "This recording has background noise", ab_desc: "{name}: listen to the same {s} seconds both ways, then choose which sound is used.",
  ab_orig: "Original sound", ab_clean: "Cleaned sound", ab_use_clean: "Use cleaned sound", ab_use_orig: "Use original sound",
  ab_dont: "Do not ask again", ab_info: "Estimated speech-to-noise ratio: {snr} dB (limit {thr} dB).",
  ab_timer: "If you do not choose within {s} s, the automatic decision is used: {choice}.",
  ab_choice_clean: "cleaned sound", ab_choice_orig: "original sound",
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
