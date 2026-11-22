/* Settings page: company details and meeting minutes (logo, name, colour, sections, own Word template) and updates.
   Uses helpers from app.js ($, el, t, call, toast, showPage) and window.updater (updater.js). */
(() => {
  Object.assign(I18N.en, {
    settings: "Settings", set_title: "Settings",
    set_company: "Company", set_company_name: "Company name", set_company_ph: "Shown at the top of the minutes",
    set_color: "Heading colour", set_logo: "Logo", set_logo_pick: "Choose logo…", set_logo_remove: "Remove logo",
    set_logo_none: "No logo yet (PNG or JPG, up to 2 MB).",
    set_minutes: "Meeting minutes", set_minutes_desc: "The \"Minutes\" button on a recording makes a Word file with these parts, in this order.",
    sec_participants: "Participants", sec_summary: "Summary", sec_chapters: "Agenda and chapters", sec_decisions: "Decisions",
    sec_tasks: "Tasks (table)", sec_questions: "Open questions", sec_transcript: "Full transcript",
    set_up: "Move up", set_down: "Move down",
    set_template: "Own Word template",
    set_template_on: "Your own template is used. The settings above do not apply to it.",
    set_template_off: "The built-in layout is used. Load your own Word file to use your company's layout.",
    set_template_help: "Write placeholders in curly brackets in your Word file, e.g. {date} as {tarih}, {summary} as {özet}, a paragraph with only {kararlar} for the decisions, and a table row with {görev.kim} {görev.ne} {görev.tarih} for the tasks. The sample template lists them all.",
    set_template_pick: "Load template…", set_template_sample: "Download sample template", set_template_remove: "Use built-in layout",
    set_tab_view: "Appearance", set_tab_record: "Recording", set_tab_minutes: "Minutes", set_tab_updates: "Updates",
    set_tab_backup: "Backup",
    set_backup: "Backup", set_backup_take: "Make backup…", set_backup_restore: "Restore from backup…",
    set_backup_note: "A .zip of your recordings, transcripts, people and settings. Models are not included; they are downloaded again when needed. Runs on this PC only.",
    backup_started: "Making the backup…", backup_working: "Making the backup…", restore_working: "Restoring the backup…",
    backup_done: "Backup saved: {p}", backup_failed: "Backup failed: {e}",
    restore_confirm: "Restore this backup ({v}, made {d})? Everything in the data folder is replaced by it. Your current data is saved first, next to the backup file.",
    restore_started: "Restoring…",
    restore_done: "Restore finished. Close and open the app again to see the restored data.",
    set_view: "View", set_zoom: "Interface size", set_zoom_default: "normal", set_zoom_note: "Makes text, buttons and boxes bigger or smaller. Ctrl + mouse wheel changes it too; the size is remembered.",
    set_updates: "Updates", set_update_auto: "Check for a new version when the app starts",
    set_update_note: "The only internet use of the app: it reads a small version file. No recording or text is ever sent.",
    set_update_now: "Check now", set_checking: "Checking…",
    set_saved: "Saved", set_failed: "Could not save: {e}",
    set_record: "Meeting recording", set_rec_system: "Record the computer's sound (Teams, Meet, Zoom, videos…)",
    set_rec_mic: "Record the microphone", set_mic_which: "Microphone", set_mic_default: "Windows default microphone",
    set_live_default: "Start live text with every recording (uses the computer more; can be switched during recording)",
    set_rec_note: "The recording stays on this computer. If the app crashes, nothing is lost: it is offered at the next start.",
    minutes_btn: "Minutes", minutes_btn_title: "Meeting minutes as Word: logo, participants, summary, decisions, tasks (Settings page)",
    minutes_no_analysis: "Saved without summary, decisions and tasks: run the meeting analysis first for those.",
  });
  Object.assign(I18N.tr, {
    settings: "Ayarlar", set_title: "Ayarlar",
    set_company: "Şirket", set_company_name: "Şirket adı", set_company_ph: "Tutanağın üstünde görünür",
    set_color: "Başlık rengi", set_logo: "Logo", set_logo_pick: "Logo seç…", set_logo_remove: "Logoyu kaldır",
    set_logo_none: "Henüz logo yok (PNG ya da JPG, en fazla 2 MB).",
    set_minutes: "Toplantı tutanağı", set_minutes_desc: "Kayıt sayfasındaki \"Tutanak\" düğmesi bu bölümleri bu sırayla içeren bir Word dosyası hazırlar.",
    sec_participants: "Katılımcılar", sec_summary: "Özet", sec_chapters: "Gündem ve bölümler", sec_decisions: "Alınan kararlar",
    sec_tasks: "Görevler (tablo)", sec_questions: "Açık sorular", sec_transcript: "Tam konuşma metni",
    set_up: "Yukarı taşı", set_down: "Aşağı taşı",
    set_template: "Kendi Word şablonunuz",
    set_template_on: "Kendi şablonunuz kullanılıyor. Yukarıdaki bölüm ayarları ona uygulanmaz.",
    set_template_off: "Yerleşik düzen kullanılıyor. Şirketinizin düzenini kullanmak için kendi Word dosyanızı yükleyin.",
    set_template_help: "Word dosyanıza süslü parantez içinde yer tutucular yazın: {tarih}, {özet}, {katılımcılar}; kararlar için tek başına {kararlar} yazılı bir paragraf; görevler için {görev.kim} {görev.ne} {görev.tarih} yazılı bir tablo satırı. Örnek şablonda hepsi listeli.",
    set_template_pick: "Şablon yükle…", set_template_sample: "Örnek şablonu indir", set_template_remove: "Yerleşik düzeni kullan",
    set_tab_view: "Görünüm", set_tab_record: "Kayıt", set_tab_minutes: "Tutanak", set_tab_updates: "Güncelleme",
    set_tab_backup: "Yedek",
    set_backup: "Yedek", set_backup_take: "Yedek al…", set_backup_restore: "Yedekten geri yükle…",
    set_backup_note: "Kayıtlarınızın, metinlerinin, kişilerin ve ayarların .zip yedeği. Modeller dahil değildir; gerektiğinde yeniden indirilir. Yalnızca bu bilgisayarda çalışır.",
    backup_started: "Yedek hazırlanıyor…", backup_working: "Yedek hazırlanıyor…", restore_working: "Yedek geri yükleniyor…",
    backup_done: "Yedek kaydedildi: {p}", backup_failed: "Yedek alınamadı: {e}",
    restore_confirm: "Bu yedek geri yüklensin mi ({v}, {d})? Veri klasöründeki her şey onunla değişir. Mevcut verileriniz önce, yedek dosyasının yanına kaydedilir.",
    restore_started: "Geri yükleniyor…",
    restore_done: "Geri yükleme tamamlandı. Geri yüklenenleri görmek için programı kapatıp yeniden açın.",
    set_view: "Görünüm", set_zoom: "Arayüz boyutu", set_zoom_default: "normal", set_zoom_note: "Yazıları, düğmeleri ve kutuları büyütür ya da küçültür. Ctrl + fare tekerleğiyle de değişir; seçilen boyut hatırlanır.",
    set_updates: "Güncellemeler", set_update_auto: "Program açılırken yeni sürüm var mı diye bak",
    set_update_note: "Programın tek internet kullanımı budur: küçük bir sürüm dosyası okunur. Hiçbir kayıt ya da metin gönderilmez.",
    set_update_now: "Şimdi denetle", set_checking: "Bakılıyor…",
    set_saved: "Kaydedildi", set_failed: "Kaydedilemedi: {e}",
    set_record: "Toplantı kaydı", set_rec_system: "Bilgisayardan gelen sesi kaydet (Teams, Meet, Zoom, video…)",
    set_rec_mic: "Mikrofonu kaydet", set_mic_which: "Mikrofon", set_mic_default: "Windows'un varsayılan mikrofonu",
    set_live_default: "Kayda başlarken canlı yazıyı da aç (bilgisayarı yorar; kayıt sırasında da açılıp kapatılabilir)",
    set_rec_note: "Kayıt bu bilgisayarda kalır. Program çökerse kayıt kaybolmaz, bir sonraki açılışta sorulur.",
    minutes_btn: "Tutanak", minutes_btn_title: "Word toplantı tutanağı: logo, katılımcılar, özet, kararlar, görevler (Ayarlar sayfası)",
    minutes_no_analysis: "Özet, kararlar ve görevler olmadan kaydedildi: bunlar için önce toplantı analizini çalıştırın.",
  });

  /* "Minutes" button on a recording */
  $("minutesBtn").onclick = async () => {
    await save();
    try {
      const r = await call("save_minutes", job.id, LANG);
      reportSaved(r);
      if (r.paths && !r.analysis && !window.SIMPLE_EDITION) setTimeout(() => toast(t("minutes_no_analysis"), false,
        { label: t("show_folder"), run: () => call("reveal", r.paths[0]) }), 3600);
    } catch (e) { toast(t("export_failed") + msg(e)); }
  };

  const root = $("settings");
  const ALL = ["participants", "summary", "chapters", "decisions", "tasks", "questions", "transcript"];
  const S = { cfg: null, settings: null, info: null, upd: "", bk: "", bkBusy: false };
  const msg = (e) => (e && e.message) || String(e);

  async function load() {
    let dev;
    [S.cfg, S.settings, S.info, dev] = await Promise.all([call("get_minutes_settings"), call("get_settings"), call("get_app_info"),
      call("rec_devices").catch(() => ({ mics: [] }))]);
    S.mics = dev.mics;
  }
  async function open() {
    if (job) await save();
    audio.pause();
    showPage("settings");
    if (!S.cfg) skeleton(root, "settings");
    try { await load(); } catch (e) { toast(t("set_failed", { e: msg(e) })); }
    draw();
    fadeIn(root);
  }
  $("settingsBtn").onclick = open;
  $("homeBtn").addEventListener("click", () => { root.hidden = true; });
  $("langSel").addEventListener("change", () => { if (!root.hidden && S.cfg) draw(); });

  const card = (title, ...kids) => el("section", { className: "scard" }, el("h3", { textContent: title }), ...kids);
  const button = (key, icon, onclick, cls = "") => {
    const b = el("button", { type: "button", className: cls, textContent: t(key), onclick });
    b.dataset.icon = icon;
    return b;
  };
  async function apply(p) {
    try { S.cfg = await p; draw(); } catch (e) { toast(t("set_failed", { e: msg(e) })); }
  }
  const saveMinutes = (values) => apply(call("set_minutes_settings", values));

  function companyCard() {
    const name = el("input", { id: "setCompany", value: S.cfg.company_name, placeholder: t("set_company_ph"), maxLength: 120 });
    name.onchange = () => saveMinutes({ company_name: name.value });
    const color = el("input", { id: "setColor", type: "color", value: S.cfg.company_color });
    color.onchange = () => saveMinutes({ company_color: color.value });
    const logoBox = el("div", { className: "logobox" });
    if (S.cfg.logo_data) logoBox.append(el("img", { src: S.cfg.logo_data, alt: "" }));
    else logoBox.append(el("span", { className: "sline dim", textContent: t("set_logo_none") }));
    const logoBtns = el("div", { className: "btnrow" }, button("set_logo_pick", "folder", () => apply(call("pick_logo"))));
    if (S.cfg.logo) logoBtns.append(button("set_logo_remove", "trash", () => apply(call("remove_logo"))));
    return card(t("set_company"),
      el("label", { className: "frow" }, el("span", { textContent: t("set_company_name") }), name),
      el("label", { className: "frow" }, el("span", { textContent: t("set_color") }), color),
      el("div", { className: "frow" }, el("span", { textContent: t("set_logo") }), el("div", {}, logoBox, logoBtns)));
  }

  function minutesCard() {
    const chosen = S.cfg.sections.slice();
    const order = chosen.concat(ALL.filter((s) => !chosen.includes(s)));
    const list = el("ol", { className: "seclist" });
    order.forEach((s, i) => {
      const on = chosen.includes(s);
      const cb = el("input", { type: "checkbox", checked: on });
      cb.onchange = () => saveMinutes({ sections: cb.checked ? [...chosen, s] : chosen.filter((x) => x !== s) });
      const move = (d) => {
        const j = chosen.indexOf(s), k = j + d;
        if (j < 0 || k < 0 || k >= chosen.length) return;
        const next = chosen.slice(); [next[j], next[k]] = [next[k], next[j]];
        saveMinutes({ sections: next });
      };
      const up = button("", "arrow-up", () => move(-1), "small icon"); up.title = t("set_up");
      const down = button("", "arrow-down", () => move(1), "small icon"); down.title = t("set_down");
      const idx = chosen.indexOf(s);
      up.disabled = !on || idx === 0; down.disabled = !on || idx === chosen.length - 1;
      list.append(el("li", { className: on ? "" : "off" },
        el("label", {}, cb, " " + t("sec_" + s)), el("span", { className: "spacer" }), up, down));
    });
    return card(t("set_minutes"), el("p", { className: "sline dim", textContent: t("set_minutes_desc") }), list);
  }

  function templateCard() {
    const btns = el("div", { className: "btnrow" },
      button("set_template_pick", "folder", () => apply(call("pick_template"))),
      button("set_template_sample", "download", async () => {
        try { reportSaved(await call("save_sample_template", LANG)); } catch (e) { toast(t("set_failed", { e: msg(e) })); }
      }));
    if (S.cfg.template) btns.append(button("set_template_remove", "x", () => apply(call("remove_template"))));
    return card(t("set_template"),
      el("div", { className: "verdict " + (S.cfg.template ? "ok" : "plain") }, t(S.cfg.template ? "set_template_on" : "set_template_off")),
      // t() fills {name} from its vars: give the placeholder names back to themselves so they stay visible
      el("p", { className: "sline dim", textContent: t("set_template_help",
        Object.fromEntries(["tarih", "kararlar", "date", "summary"].map((k) => [k, `{${k}}`]))) }), btns);
  }

  function recordCard() {
    const r = S.settings;
    const setBool = (key) => async (e) => {
      try { S.settings = await call("set_settings", { [key]: e.target.checked }); toast(t("set_saved")); }
      catch (err) { toast(t("set_failed", { e: msg(err) })); }
    };
    const box = (key, label) => el("label", { className: "frow check" },
      el("input", { type: "checkbox", checked: r[key] !== false && r[key] !== undefined ? !!r[key] : false, onchange: setBool(key) }),
      el("span", { textContent: t(label) }));
    const mic = el("select", { id: "setMic" }, el("option", { value: "", textContent: t("set_mic_default") }),
      ...(S.mics || []).map((m) => el("option", { value: m.id, textContent: m.name, selected: m.id === r.rec_mic_id })));
    mic.onchange = async () => {
      try { S.settings = await call("set_settings", { rec_mic_id: mic.value }); toast(t("set_saved")); }
      catch (err) { toast(t("set_failed", { e: msg(err) })); }
    };
    const kids = [box("rec_system", "set_rec_system"), box("rec_mic", "set_rec_mic"),
      el("label", { className: "frow" }, el("span", { textContent: t("set_mic_which") }), mic)];
    if (window.REC_LIVE !== false) kids.push(box("live_default", "set_live_default"));
    kids.push(el("p", { className: "sline dim", textContent: t("set_rec_note") }));
    return card(t("set_record"), ...kids);
  }

  function viewCard() {
    const cur = Number(S.settings.ui_zoom) || 1;
    const sizes = [0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75];
    if (!sizes.some((z) => Math.abs(z - cur) < 0.01)) sizes.push(cur);  // set with Ctrl + mouse wheel
    const sel = el("select", { id: "setZoom" }, ...sizes.sort((a, b) => a - b).map((z) =>
      el("option", { value: String(z), textContent: `%${Math.round(z * 100)}` + (z === 1 ? ` (${t("set_zoom_default")})` : ""), selected: Math.abs(z - cur) < 0.01 })));
    sel.onchange = async () => {
      try { S.settings = await call("set_settings", { ui_zoom: Number(sel.value) }); toast(t("set_saved")); }
      catch (e) { toast(t("set_failed", { e: msg(e) })); }
    };
    return card(t("set_view"),
      el("label", { className: "frow" }, el("span", { textContent: t("set_zoom") }), sel),
      el("p", { className: "sline dim", textContent: t("set_zoom_note") }));
  }

  /* ---- backup / restore: the zip work runs in the backend thread, this polls its status ---- */
  function backupText(st) {
    if (!st || (!st.busy && !st.done && !st.error)) return "";
    if (st.busy) return st.kind === "restore" ? t("restore_working") : t("backup_working");
    if (st.error) return t("backup_failed", { e: st.error });
    return st.kind === "restore" ? t("restore_done") : t("backup_done", { p: st.result?.path || st.path });
  }

  function backupCard() {
    const busy = !!S.bkBusy;
    const take = button("set_backup_take", "download", async () => {
      try {
        const r = await call("backup_create"); // native Save dialog, then the thread starts
        if (!r.cancelled) toast(t("backup_started"));
      } catch (e) { toast(t("set_failed", { e: msg(e) })); }
    });
    take.id = "backupTake";
    const restore = button("set_backup_restore", "archive", async () => {
      try {
        const r = await call("backup_restore_pick"); // opens the zip and checks its manifest
        if (r.cancelled) return;
        const m = r.manifest || {};
        if (!confirm(t("restore_confirm", { v: m.version || "?", d: String(m.created || "").replace("T", " ") }))) return;
        await call("backup_restore", r.path);
        toast(t("restore_started"));
      } catch (e) { toast(t("set_failed", { e: msg(e) })); }
    });
    restore.id = "backupRestore";
    take.disabled = restore.disabled = busy;
    return card(t("set_backup"),
      el("p", { className: "sline dim", textContent: t("set_backup_note") }),
      el("div", { className: "btnrow" }, take, restore),
      el("div", { className: "sline", id: "backupMsg", textContent: S.bk || "" }));
  }

  let bkSig = "";
  setInterval(() => { // cheap while another tab or page is showing: only the Yedek tab has the elements
    if (root.hidden || S.tab !== "backup") return;
    call("backup_status").then((st) => {
      const sig = JSON.stringify(st);
      if (sig === bkSig) return;
      const wasDone = bkSig && JSON.parse(bkSig).done;
      bkSig = sig;
      S.bk = backupText(st); S.bkBusy = !!st.busy;
      const m = $("backupMsg"); if (m) m.textContent = S.bk;
      for (const id of ["backupTake", "backupRestore"]) { const b = $(id); if (b) b.disabled = !!st.busy; }
      if (st.done && !wasDone && st.kind === "restore") toast(t("restore_done"));
    }).catch(() => { /* shown again next second */ });
  }, 1000);

  function updateCard() {
    const auto = el("input", { type: "checkbox", id: "setUpdAuto", checked: S.settings.update_check !== false });
    auto.onchange = async () => {
      try { S.settings = await call("set_settings", { update_check: auto.checked }); toast(t("set_saved")); }
      catch (e) { toast(t("set_failed", { e: msg(e) })); }
    };
    const result = el("div", { className: "sline", id: "setUpdMsg", textContent: S.upd });
    const now = button("set_update_now", "refresh", async () => {
      now.disabled = true; result.textContent = t("set_checking");
      try {
        const s = await window.updater.check(true);
        S.upd = s.state === "available" ? t("upd_available", { v: s.latest, cur: s.current })
          : s.state === "none" ? t("upd_none", { cur: s.current }) : t("upd_check_failed");
      } catch (e) { S.upd = t("upd_check_failed"); }
      result.textContent = S.upd; now.disabled = false;
    });
    return card(t("set_updates"),
      el("div", { className: "sline strong", textContent: t("ver_line", { v: S.info.version, ed: t("ed_" + S.info.edition) }) }),
      el("label", { className: "frow check" }, auto, el("span", { textContent: t("set_update_auto") })),
      el("p", { className: "sline dim", textContent: t("set_update_note") }),
      el("div", { className: "btnrow" }, now), result);
  }

  function draw() {
    // the simple edition keeps it short: recording, company name / logo, updates
    // tabs on the left, one topic at a time on the right
    const tabs = [
      ["view", "eye", "set_tab_view", () => [viewCard()]],
      ["record", "mic", "set_tab_record", () => [recordCard()]],
      ["minutes", "file-text", "set_tab_minutes", () => window.SIMPLE_EDITION ? [companyCard()] : [companyCard(), minutesCard(), templateCard()]],
      ["backup", "archive", "set_tab_backup", () => [backupCard()]],
      ["updates", "refresh", "set_tab_updates", () => [updateCard()]],
    ];
    if (!tabs.some(([id]) => id === S.tab)) S.tab = "view";
    const nav = el("nav", { className: "stabs", role: "tablist" }, ...tabs.map(([id, icon, key]) => {
      const b = el("button", { type: "button", role: "tab", className: "stab" + (id === S.tab ? " on" : ""), textContent: t(key),
        onclick: () => { S.tab = id; draw(); } });
      b.setAttribute("aria-selected", String(id === S.tab));
      b.dataset.icon = icon;
      return b;
    }));
    const body = el("div", { className: "sbody", role: "tabpanel" }, ...tabs.find(([id]) => id === S.tab)[3]());
    root.replaceChildren(el("h2", { textContent: t("set_title") }), el("div", { className: "slayout" }, nav, body));
    body.scrollTop = 0; // a tab always opens at its top
    hydrateIcons(root);
  }
})();
