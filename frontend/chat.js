/* Assistant page: ask about the recordings in plain words ("What did Ahmet say about the app last week?").
   Answers come from the local model (backend/chat.py); every answer lists its sources, a click opens the recording
   at that moment. Conversations are saved (backend/chats.py) and listed in a panel on the right, like ChatGPT. */
(() => {
  Object.assign(I18N.en, {
    assistant: "Assistant", ast_title: "Ask about your meetings",
    ast_intro: "Ask in your own words. The answer comes only from your recordings, made on this computer. Each answer shows where it was said: click to listen.",
    ast_ph: "e.g. What did Ahmet say about the app last week?", ast_send: "Ask", ast_new: "New conversation",
    ast_thinking: "Thinking… (the local model needs a few seconds)", ast_cancel: "Stop",
    ast_ex1: "Which decisions were made last week?", ast_ex2: "What tasks does Ahmet have?",
    ast_ex3: "What did we say about the budget this month?", ast_ex4: "Who made this app?",
    ast_empty_title: "Ask about your recordings",
    ast_no_model: "The assistant uses the meeting-mode language model. Download it once on the System page; after that it works offline.",
    ast_open_system: "Open the System page", ast_busy: "A recording is being transcribed right now. Ask again when it is done.",
    ast_failed: "Something went wrong: {e}", ast_sources: "Sources", ast_range: "Searched: {r}",
    ast_kind_summary: "summary", ast_kind_decision: "decision", ast_kind_task: "task", ast_kind_question: "open question",
    ast_note: "A small local model can misread: check important answers in the sources.",
    ast_new_chat: "New chat", ast_chats: "Chats", ast_nochats: "No conversations yet",
    ast_rename: "Rename", ast_delete: "Delete", ast_delete_confirm: "Delete this conversation?",
    ast_more: "More actions",
  });
  Object.assign(I18N.tr, {
    assistant: "Asistan", ast_title: "Toplantılarınıza soru sorun",
    ast_intro: "Kendi cümlelerinizle sorun. Cevap yalnızca kayıtlarınızdan, bu bilgisayarda hazırlanır. Her cevabın altında nerede söylendiği yazar: tıklayıp dinleyebilirsiniz.",
    ast_ph: "ör. Geçen hafta Ahmet uygulama için ne demişti?", ast_send: "Sor", ast_new: "Yeni sohbet",
    ast_thinking: "Düşünüyor… (yerel model birkaç saniye sürer)", ast_cancel: "Durdur",
    ast_ex1: "Geçen hafta hangi kararlar alındı?", ast_ex2: "Ahmet'in görevleri neler?",
    ast_ex3: "Bu ay bütçe hakkında ne konuştuk?", ast_ex4: "Bu uygulamayı kim yaptı?",
    ast_empty_title: "Kayıtlarınız hakkında sorun",
    ast_no_model: "Asistan, toplantı modunun dil modelini kullanır. Sistem sayfasından bir kez indirin; sonra internetsiz çalışır.",
    ast_open_system: "Sistem sayfasını aç", ast_busy: "Şu an bir kayıt metne çevriliyor. Bitince tekrar sorun.",
    ast_failed: "Bir sorun oldu: {e}", ast_sources: "Kaynaklar", ast_range: "Aranan tarih: {r}",
    ast_kind_summary: "özet", ast_kind_decision: "karar", ast_kind_task: "görev", ast_kind_question: "açık soru",
    ast_note: "Küçük yerel model yanılabilir: önemli cevapları kaynaklardan kontrol edin.",
    ast_new_chat: "Yeni sohbet", ast_chats: "Sohbetler", ast_nochats: "Henüz sohbet yok",
    ast_rename: "Yeniden adlandır", ast_delete: "Sil", ast_delete_confirm: "Bu sohbet silinsin mi?",
    ast_more: "Diğer işlemler",
  });

  const root = $("assistant");
  const S = { id: null, msgs: [], history: [], chats: [], busy: false, ready: null,
    session: {}, menuId: null, editId: null, panelOpen: false };
  let saveChain = Promise.resolve(); // saves run one after another, so the second one always knows the first id
  const msg = (e) => (e && e.message) || String(e);

  /* ---------------- page ---------------- */

  async function open() {
    if (job) await save();
    audio.pause();
    showPage("assistant");
    S.menuId = null; S.editId = null; S.panelOpen = false;
    const first = S.ready === null;
    if (first) { skeleton(root, "chat"); try { S.ready = (await call("chat_info")).llm_ready; } catch { S.ready = false; } }
    await loadChats();
    draw();
    if (first) fadeIn(root);
    $("astIn")?.focus();
  }
  $("assistantBtn").onclick = open;
  $("homeBtn").addEventListener("click", () => { root.hidden = true; });
  window.addEventListener("langchange", () => { if (!root.hidden) draw(); });

  /* ---------------- saved conversations ---------------- */

  async function loadChats() {
    try { const list = await call("chat_list"); if (Array.isArray(list)) S.chats = list; } catch { /* keep the old list */ }
  }
  async function refreshChats() {
    await loadChats();
    if (!root.hidden) draw();
  }

  function newChat() {
    S.id = null; S.msgs = []; S.history = []; S.session = {};
    S.menuId = null; S.editId = null; S.panelOpen = false;
    draw();
    $("astIn")?.focus();
  }

  async function loadChat(id) {
    if (!id || S.busy) return;
    S.menuId = null; S.editId = null;
    if (id === S.id) { draw(); return; }
    let c;
    try { c = await call("chat_get", id); } catch { return; }
    if (!c || c.error) { await refreshChats(); return; }
    S.id = c.id || id;
    S.msgs = Array.isArray(c.msgs) ? c.msgs : [];
    S.history = Array.isArray(c.history) ? c.history : [];
    S.session = {};
    S.panelOpen = false;
    draw();
    $("astIn")?.focus();
  }

  async function commitRename(id, title) {
    S.editId = null;
    title = (title || "").trim();
    if (!title) { draw(); return; }
    try {
      const r = await call("chat_rename", id, title);
      if (r && !r.error) { const c = S.chats.find((x) => x.id === id); if (c) c.title = r.title || title; }
    } catch { /* the refresh below puts the list back in step */ }
    await refreshChats();
  }

  async function deleteChat(c) {
    S.menuId = null;
    if (!confirm(t("ast_delete_confirm"))) { draw(); return; }
    try { await call("chat_delete", c.id); } catch { /* refresh anyway */ }
    if (S.id === c.id) { S.id = null; S.msgs = []; S.history = []; S.session = {}; }
    await refreshChats();
  }

  function chatMenu(c) {
    return el("div", { className: "astmenu", role: "menu" },
      el("button", { type: "button", role: "menuitem", textContent: t("ast_rename"),
        onclick: () => { S.menuId = null; S.editId = c.id; draw(); } }),
      el("button", { type: "button", role: "menuitem", textContent: t("ast_delete"),
        onclick: () => deleteChat(c) }));
  }

  function chatRow(c) {
    const row = el("div", { className: "astchat" + (c.id === S.id ? " on" : "") });
    if (S.editId === c.id) {
      const inp = el("input", { type: "text", className: "astrename", value: c.title || "", maxLength: 80 });
      inp.setAttribute("aria-label", t("ast_rename"));
      inp.onkeydown = (e) => {
        if (e.key === "Enter") { e.preventDefault(); commitRename(c.id, inp.value); }
        else if (e.key === "Escape") { e.preventDefault(); S.editId = null; draw(); }
      };
      row.append(inp);
      return row;
    }
    const b = el("button", { type: "button", className: "astchatbtn", textContent: c.title || "", title: c.title || "",
      onclick: () => loadChat(c.id) });
    b.disabled = S.busy;
    const more = el("button", { type: "button", className: "astmore", title: t("ast_more"),
      onclick: (e) => { e.stopPropagation(); S.menuId = S.menuId === c.id ? null : c.id; draw(); } });
    more.dataset.icon = "more-vertical";
    more.disabled = S.busy;
    row.append(b, more);
    if (S.menuId === c.id) row.append(chatMenu(c));
    return row;
  }

  function panel() {
    const nb = el("button", { type: "button", className: "primary astnew", textContent: t("ast_new_chat"), onclick: newChat });
    nb.dataset.icon = "plus";
    nb.disabled = S.busy;
    const list = el("div", { className: "astchats" });
    if (!S.chats.length) list.append(el("p", { className: "hint astnochats", textContent: t("ast_nochats") }));
    for (const c of S.chats) list.append(chatRow(c));
    const p = el("aside", { className: "astpanel" + (S.panelOpen ? " open" : "") }, nb, list);
    p.setAttribute("aria-label", t("ast_chats"));
    return p;
  }

  /* ---------------- messages ---------------- */

  function sourceChip(s) {
    const date = new Date((s.created || 0) * 1000).toLocaleDateString(LANG === "tr" ? "tr-TR" : "en-GB", { day: "numeric", month: "short" });
    const bits = [s.filename.replace(/\.[^.]+$/, ""), date];
    if (s.kind !== "summary" && s.start != null) bits.push(fmt(s.start));
    if (s.speaker) bits.push(s.speaker);
    if (s.kind !== "line") bits.push(t("ast_kind_" + s.kind));
    const b = el("button", { type: "button", className: "srcchip", title: s.text });
    b.append(el("span", { className: "srcn", textContent: s.n }), " " + bits.join(" · "));
    b.onclick = () => openJob(s.job_id).then(() => { if (s.seg != null) jumpToSeg(s.seg); });
    return b;
  }

  function bubble(m) {
    if (m.role === "user") return el("div", { className: "astmsg user" }, el("p", { textContent: m.text }));
    const kids = [el("p", { textContent: m.text })];
    if (m.sources?.length) kids.push(el("div", { className: "srcs" }, el("span", { className: "hint", textContent: t("ast_sources") + ":" }), ...m.sources.map(sourceChip)));
    if (m.range) kids.push(el("p", { className: "hint", textContent: t("ast_range", { r: m.range }) }));
    if (m.action) kids.push(m.action);
    return el("div", { className: "astmsg bot" + (m.error ? " err" : "") }, ...kids);
  }

  function draw() {
    const old = $("astIn");
    const draft = old?.value || "";
    const hadFocus = document.activeElement === old;
    const toggle = el("button", { type: "button", className: "small astchattoggle", textContent: t("ast_chats"),
      onclick: () => { S.panelOpen = !S.panelOpen; draw(); } });
    toggle.dataset.icon = "message-circle";
    toggle.setAttribute("aria-expanded", S.panelOpen ? "true" : "false");
    const main = el("div", { className: "astmain" },
      el("div", { className: "asthead" }, el("h2", { textContent: t("ast_title") }), el("span", { className: "spacer" }), toggle));
    if (!S.ready) {
      const go = el("button", { type: "button", className: "primary", textContent: t("ast_open_system"), onclick: () => $("sysBtn").click() });
      main.append(el("div", { className: "verdict warn" }, t("ast_no_model")), el("p", {}, go));
      root.replaceChildren(main, panel());
      hydrateIcons(root);
      return;
    }
    const input = el("textarea", { id: "astIn", rows: 2, placeholder: t("ast_ph"), maxLength: 500, disabled: S.busy, value: draft });
    const log = el("div", { className: "astlog", id: "astLog" });
    if (!S.msgs.length) {
      const chips = el("div", { className: "exchips" });
      for (const k of ["ast_ex1", "ast_ex2", "ast_ex3"]) {
        const b = el("button", { type: "button", className: "small", textContent: t(k) });
        b.onclick = () => { input.value = t(k); input.focus(); };
        chips.append(b);
      }
      log.append(emptyState("message-circle", t("ast_empty_title"), t("ast_intro"), chips));
    }
    S.msgs.forEach((m) => log.append(bubble(m)));
    if (S.busy) {
      const stop = el("button", { type: "button", className: "small", textContent: t("ast_cancel"), onclick: () => call("chat_cancel") });
      log.append(el("div", { className: "astmsg bot thinking" }, el("span", { className: "astdots" }), " " + t("ast_thinking"), " ", stop));
    }
    input.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input.value); } };
    const send = el("button", { type: "button", className: "primary", textContent: t("ast_send"), disabled: S.busy, onclick: () => ask(input.value) });
    main.append(log, el("div", { className: "astin" }, input, send), el("p", { className: "hint astnote", textContent: t("ast_note") }));
    root.replaceChildren(main, panel());
    hydrateIcons(root);
    if (S.editId) { const inp = root.querySelector(".astrename"); inp?.focus(); inp?.select(); }
    else if (hadFocus) input.focus();
    // after layout (icons, wrapped text): the newest message at the bottom of the log, and the log in view
    const down = () => { log.scrollTop = log.scrollHeight; log.lastElementChild?.scrollIntoView({ block: "nearest" }); };
    down(); requestAnimationFrame(down);
  }

  /* ---------------- asking ---------------- */

  function firstQuestion() {
    const u = S.msgs.find((m) => m.role === "user");
    return u ? u.text : "";
  }

  async function saveAnswer(question, answer) {
    const session = S.session;
    const wasNew = !S.id;
    let saved;
    try { saved = await call("chat_save", S.id, S.msgs, S.history, firstQuestion()); } catch { return; }
    if (!saved || saved.error || !saved.id) return;
    if (S.session === session) S.id = saved.id; // the user may have started another chat while this was saving
    await refreshChats();
    if (wasNew) {
      call("chat_autotitle", saved.id, question, answer, LANG).then((r) => {
        if (!r || !r.title) return;
        const c = S.chats.find((x) => x.id === saved.id);
        if (c) c.title = r.title;
        if (S.session === session && !root.hidden) draw();
      }).catch(() => {});
    }
    if (S.session === session && !root.hidden) $("astIn")?.focus();
  }

  function queueSave(question, answer) {
    saveChain = saveChain.then(() => saveAnswer(question, answer)).catch(() => {});
    return saveChain;
  }

  async function ask(q) {
    q = (q || "").trim();
    if (!q || S.busy) return;
    const box = $("astIn");
    if (box) box.value = "";
    S.msgs.push({ role: "user", text: q });
    S.busy = true; draw();
    let r;
    try { r = await call("chat_ask", q, S.history, LANG); } catch (e) { r = { error: "failed", detail: msg(e) }; }
    S.busy = false;
    let answered = false;
    if (r.cancelled) { S.msgs.pop(); }
    else if (r.error === "no_model") { S.ready = false; }
    else if (r.error === "busy") S.msgs.push({ role: "bot", text: t("ast_busy"), error: true });
    else if (r.error) S.msgs.push({ role: "bot", text: t("ast_failed", { e: r.detail || r.error }), error: true });
    else {
      S.msgs.push({ role: "bot", text: r.answer, sources: r.sources, range: r.range });
      S.history.push({ q, range: r.range, range_ts: r.range_ts });
      S.history = S.history.slice(-3);
      answered = true;
    }
    draw();
    $("astIn")?.focus();
    if (answered) queueSave(q, r.answer);
  }

  /* ---------------- menus and the narrow-screen overlay ---------------- */

  document.addEventListener("click", (e) => {
    if (root.hidden) return;
    const inside = (sel) => e.target.closest?.(sel);
    let changed = false;
    if (S.menuId && !inside(".astmenu") && !inside(".astmore")) { S.menuId = null; changed = true; }
    if (S.panelOpen && !inside(".astpanel") && !inside(".astchattoggle")) { S.panelOpen = false; changed = true; }
    if (changed) draw();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || root.hidden) return;
    if (S.menuId) { S.menuId = null; draw(); }
    else if (S.editId) { S.editId = null; draw(); }
    else if (S.panelOpen) { S.panelOpen = false; draw(); }
  });
})();
