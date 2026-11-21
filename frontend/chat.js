/* Assistant page: ask about the recordings in plain words ("What did Ahmet say about the app last week?").
   Answers come from the local model (backend/chat.py); every answer lists its sources, a click opens the recording
   at that moment. The conversation lives only while the app is open. */
(() => {
  Object.assign(I18N.en, {
    assistant: "Assistant", ast_title: "Ask about your meetings",
    ast_intro: "Ask in your own words. The answer comes only from your recordings, made on this computer. Each answer shows where it was said: click to listen.",
    ast_ph: "e.g. What did Ahmet say about the app last week?", ast_send: "Ask", ast_new: "New conversation",
    ast_thinking: "Thinking… (the local model needs a few seconds)", ast_cancel: "Stop",
    ast_ex1: "Which decisions were made last week?", ast_ex2: "What tasks does Ahmet have?",
    ast_ex3: "What did we say about the budget this month?", ast_ex4: "Who made this app?",
    ast_no_model: "The assistant uses the meeting-mode language model. Download it once on the System page; after that it works offline.",
    ast_open_system: "Open the System page", ast_busy: "A recording is being transcribed right now. Ask again when it is done.",
    ast_failed: "Something went wrong: {e}", ast_sources: "Sources", ast_range: "Searched: {r}",
    ast_kind_summary: "summary", ast_kind_decision: "decision", ast_kind_task: "task", ast_kind_question: "open question",
    ast_note: "A small local model can misread: check important answers in the sources.",
  });
  Object.assign(I18N.tr, {
    assistant: "Asistan", ast_title: "Toplantılarınıza soru sorun",
    ast_intro: "Kendi cümlelerinizle sorun. Cevap yalnızca kayıtlarınızdan, bu bilgisayarda hazırlanır. Her cevabın altında nerede söylendiği yazar: tıklayıp dinleyebilirsiniz.",
    ast_ph: "ör. Geçen hafta Ahmet uygulama için ne demişti?", ast_send: "Sor", ast_new: "Yeni sohbet",
    ast_thinking: "Düşünüyor… (yerel model birkaç saniye sürer)", ast_cancel: "Durdur",
    ast_ex1: "Geçen hafta hangi kararlar alındı?", ast_ex2: "Ahmet'in görevleri neler?",
    ast_ex3: "Bu ay bütçe hakkında ne konuştuk?", ast_ex4: "Bu uygulamayı kim yaptı?",
    ast_no_model: "Asistan, toplantı modunun dil modelini kullanır. Sistem sayfasından bir kez indirin; sonra internetsiz çalışır.",
    ast_open_system: "Sistem sayfasını aç", ast_busy: "Şu an bir kayıt metne çevriliyor. Bitince tekrar sorun.",
    ast_failed: "Bir sorun oldu: {e}", ast_sources: "Kaynaklar", ast_range: "Aranan tarih: {r}",
    ast_kind_summary: "özet", ast_kind_decision: "karar", ast_kind_task: "görev", ast_kind_question: "açık soru",
    ast_note: "Küçük yerel model yanılabilir: önemli cevapları kaynaklardan kontrol edin.",
  });

  const root = $("assistant");
  const S = { msgs: [], history: [], busy: false, ready: null };
  const msg = (e) => (e && e.message) || String(e);

  async function open() {
    if (job) await save();
    audio.pause();
    showPage("assistant");
    if (S.ready === null) { skeleton(root, "people"); try { S.ready = (await call("chat_info")).llm_ready; } catch { S.ready = false; } }
    draw();
    $("astIn")?.focus();
  }
  $("assistantBtn").onclick = open;
  $("homeBtn").addEventListener("click", () => { root.hidden = true; });
  window.addEventListener("langchange", () => { if (!root.hidden) draw(); });

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
    const kids = [el("div", { className: "asthead" }, el("h2", { textContent: t("ast_title") }), el("span", { className: "spacer" }))];
    if (S.msgs.length) {
      const nb = el("button", { type: "button", className: "small", textContent: t("ast_new"), onclick: () => { S.msgs = []; S.history = []; draw(); } });
      nb.dataset.icon = "refresh"; kids[0].append(nb);
    }
    if (!S.ready) {
      const go = el("button", { type: "button", className: "primary", textContent: t("ast_open_system"), onclick: () => $("sysBtn").click() });
      kids.push(el("div", { className: "verdict warn" }, t("ast_no_model")), el("p", {}, go));
      root.replaceChildren(...kids); hydrateIcons(root); return;
    }
    const log = el("div", { className: "astlog", id: "astLog" });
    if (!S.msgs.length) {
      log.append(el("p", { className: "hint", textContent: t("ast_intro") }));
      const ex = el("div", { className: "astex" });
      for (const k of ["ast_ex1", "ast_ex2", "ast_ex3", "ast_ex4"]) ex.append(el("button", { type: "button", className: "small", textContent: t(k), onclick: () => ask(t(k)) }));
      log.append(ex);
    }
    S.msgs.forEach((m) => log.append(bubble(m)));
    if (S.busy) {
      const stop = el("button", { type: "button", className: "small", textContent: t("ast_cancel"), onclick: () => call("chat_cancel") });
      log.append(el("div", { className: "astmsg bot thinking" }, el("span", { className: "astdots" }), " " + t("ast_thinking"), " ", stop));
    }
    const input = el("textarea", { id: "astIn", rows: 2, placeholder: t("ast_ph"), maxLength: 500, disabled: S.busy });
    input.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input.value); } };
    const send = el("button", { type: "button", className: "primary", textContent: t("ast_send"), disabled: S.busy, onclick: () => ask(input.value) });
    kids.push(log, el("div", { className: "astin" }, input, send), el("p", { className: "hint astnote", textContent: t("ast_note") }));
    root.replaceChildren(...kids);
    hydrateIcons(root);
    log.scrollTop = log.scrollHeight;
  }

  async function ask(q) {
    q = (q || "").trim();
    if (!q || S.busy) return;
    S.msgs.push({ role: "user", text: q });
    S.busy = true; draw();
    let r;
    try { r = await call("chat_ask", q, S.history, LANG); } catch (e) { r = { error: "failed", detail: msg(e) }; }
    S.busy = false;
    if (r.cancelled) { S.msgs.pop(); }
    else if (r.error === "no_model") { S.ready = false; }
    else if (r.error === "busy") S.msgs.push({ role: "bot", text: t("ast_busy"), error: true });
    else if (r.error) S.msgs.push({ role: "bot", text: t("ast_failed", { e: r.detail || r.error }), error: true });
    else {
      S.msgs.push({ role: "bot", text: r.answer, sources: r.sources, range: r.range });
      S.history.push({ q, range: r.range, range_ts: r.range_ts });
      S.history = S.history.slice(-3);
    }
    draw();
    $("astIn")?.focus();
  }
})();
