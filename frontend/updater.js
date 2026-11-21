/* Update banner: a few seconds after start the backend reads the author's version file (backend/updater.py).
   A newer version shows a banner under the header: Update downloads the setup of this edition, checks it, and
   installs it after the app closes; the new version opens by itself. Recordings and settings are kept.
   Also fills the version line in the About box. window.updater is used by the Settings page. */
(() => {
  Object.assign(I18N.en, {
    upd_available: "Ses Defteri {v} is available (you have {cur}).",
    upd_whats_new: "What's new",
    upd_update: "Update",
    upd_later: "Later",
    upd_downloading: "Downloading the update… {p}%",
    upd_ready: "The update is ready. Ses Defteri will close, install it and open again. Your recordings and settings are kept.",
    upd_install: "Install and restart",
    upd_busy: "A recording is being processed. It stops now; after the update, Resume continues it where it stopped. Install now?",
    upd_error: "The update could not be downloaded or did not pass the safety check. Nothing was changed.",
    upd_retry: "Try again",
    upd_none: "You have the latest version ({cur}).",
    upd_check_failed: "Could not reach the update server. Check the internet connection.",
    upd_dev: "Running from source: updates are installed only in the installed app.",
    upd_installing: "Closing to install the update…",
    ver_line: "Version {v} · {ed}",
    ed_standart: "Standard", ed_nvidia: "NVIDIA", ed_basit: "Simple", ed_dev: "development",
  });
  Object.assign(I18N.tr, {
    upd_available: "Ses Defteri {v} çıktı (sizdeki {cur}).",
    upd_whats_new: "Neler yeni",
    upd_update: "Güncelle",
    upd_later: "Sonra",
    upd_downloading: "Güncelleme indiriliyor… %{p}",
    upd_ready: "Güncelleme hazır. Ses Defteri kapanıp güncellemeyi kuracak ve yeniden açılacak. Kayıtlarınız ve ayarlarınız korunur.",
    upd_install: "Kur ve yeniden başlat",
    upd_busy: "Şu an bir kayıt işleniyor. Şimdi durur; güncellemeden sonra \"Devam et\" ile kaldığı yerden sürer. Şimdi kurulsun mu?",
    upd_error: "Güncelleme indirilemedi ya da güvenlik kontrolünden geçmedi. Hiçbir şey değiştirilmedi.",
    upd_retry: "Tekrar dene",
    upd_none: "En son sürümü kullanıyorsunuz ({cur}).",
    upd_check_failed: "Güncelleme sunucusuna ulaşılamadı. İnternet bağlantısını kontrol edin.",
    upd_dev: "Kaynak koddan çalışıyor: güncelleme yalnızca kurulu uygulamada yapılır.",
    upd_installing: "Güncellemeyi kurmak için kapanıyor…",
    ver_line: "Sürüm {v} · {ed}",
    ed_standart: "Standart", ed_nvidia: "NVIDIA", ed_basit: "Basit", ed_dev: "geliştirme",
  });

  const bar = $("updBar");
  let pollTimer = null, last = null;

  const btn = (key, icon, onclick, primary = false) => {
    const b = el("button", { type: "button", className: "small" + (primary ? " primary" : ""), onclick });
    b.dataset.icon = icon; b.dataset.i18n = key; b.textContent = t(key);
    return b;
  };

  function render(s) {
    last = s;
    clearTimeout(pollTimer);
    const show = ["available", "downloading", "ready", "installing"].includes(s.state) ||
      (s.state === "error" && s.latest);
    bar.hidden = !show;
    if (!show) return;
    const msg = el("span", { className: "updmsg" });
    const kids = [msg];
    if (s.state === "available") {
      msg.textContent = t("upd_available", { v: s.latest, cur: s.current });
      if (s.notes) {
        const d = el("details", { className: "updnotes" }, el("summary", { textContent: t("upd_whats_new") }),
          el("div", { textContent: s.notes }));
        kids.push(d);
      }
      kids.push(s.can_install ? btn("upd_update", "download", download, true) : el("span", { className: "hint", textContent: t("upd_dev") }),
        btn("upd_later", "x", later));
    } else if (s.state === "downloading") {
      msg.textContent = t("upd_downloading", { p: s.progress || 0 });
      kids.push(el("div", { className: "bar updbarfill" }, el("div", { className: "updfill", style: `width:${s.progress || 0}%` })));
      pollTimer = setTimeout(poll, 600);
    } else if (s.state === "ready") {
      msg.textContent = t("upd_ready");
      kids.push(btn("upd_install", "refresh", install, true), btn("upd_later", "x", () => (bar.hidden = true)));
    } else if (s.state === "installing") {
      msg.textContent = t("upd_installing");
    } else {
      msg.textContent = t("upd_error");
      kids.push(btn("upd_retry", "refresh", download), btn("upd_later", "x", later));
    }
    bar.replaceChildren(el("span", { className: "updic" }), ...kids);
    bar.querySelector(".updic").dataset.icon = "download";
    hydrateIcons(bar);
  }

  async function poll() { render(await call("update_status", LANG)); }
  async function check(force = false) {
    const s = await call("check_update", force, LANG);
    render(s);
    return s;
  }
  async function download() { render(await call("download_update", LANG)); }
  async function later() { await call("snooze_update"); bar.hidden = true; }
  async function install() {
    const q = await call("get_queue").catch(() => null);
    const busy = q && (q.running || (q.queued && q.queued.length));
    if (busy && !confirm(t("upd_busy"))) return;
    render(await call("install_update"));
  }

  async function aboutVersion() {
    const i = await call("get_app_info");
    $("aboutVer").textContent = t("ver_line", { v: i.version, ed: t("ed_" + i.edition) });
  }

  window.updater = { check, poll, render, aboutVersion, last: () => last };
  bridgeReady.then(() => {
    aboutVersion();
    setTimeout(() => check(false).catch(() => {}), 5000);
  });
  window.addEventListener("langchange", () => { aboutVersion(); if (last) render(last); });
})();
