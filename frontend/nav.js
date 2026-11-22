/* Left side menu: the hamburger button folds it to icons (remembered on this PC); the open page is highlighted. */
(() => {
  const body = document.body;
  const KEY = "sd_nav_folded";
  const narrow = () => window.innerWidth < 900;
  let folded = false;
  try { folded = localStorage.getItem(KEY) === "1"; } catch (e) { /* private storage off: start open */ }
  const apply = () => body.classList.toggle("navfolded", folded || narrow());
  apply();
  window.addEventListener("resize", apply);
  $("navToggle").onclick = () => {
    if (narrow()) { body.classList.toggle("navpeek"); return; }  // small window: the menu opens over the page
    folded = !folded;
    try { localStorage.setItem(KEY, folded ? "1" : "0"); } catch (e) { /* not remembered */ }
    apply();
  };

  // which page is open -> which menu item is lit
  const ITEMS = [["assistant", "assistantBtn"], ["people", "peopleBtn"], ["settings", "settingsBtn"], ["system", "sysBtn"]];
  function mark() {
    const open = ITEMS.find(([page]) => { const e = $(page); return e && !e.hidden; });
    const id = open ? open[1] : "homeBtn";
    for (const b of document.querySelectorAll("#sidenav .navitem")) {
      b.classList.toggle("on", b.id === id);
      b.title = b.textContent.trim();  // folded menu: the name on hover
      if (b.classList.contains("on")) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    }
    $("homeBtn").hidden = false;  // the recordings item is always there
  }
  for (const b of document.querySelectorAll("#sidenav .navitem")) {
    b.addEventListener("click", () => { body.classList.remove("navpeek"); setTimeout(mark, 60); });
  }
  window.addEventListener("pageopen", () => setTimeout(mark, 0));
  window.addEventListener("langchange", () => setTimeout(mark, 0));
  // pages also open from elsewhere (a recording, the tour): watch the pages' hidden flag
  const mo = new MutationObserver(() => mark());
  for (const id of ["home", "view", ...ITEMS.map(([p]) => p)]) { const e = $(id); if (e) mo.observe(e, { attributes: true, attributeFilter: ["hidden"] }); }
  mark();
})();
