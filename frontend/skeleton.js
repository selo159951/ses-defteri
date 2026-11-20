/* Loading placeholders, as on social apps: empty boxes in the shape of the page that is coming, with a light band
   sweeping across them (row by row, top to bottom) while the data loads; then the real content fades in.
   skeleton(container, "system" | "people" | "lines") fills a container; fadeIn(container) animates what replaced it. */
(function () {
  let n = 0; // running index: each box starts its sweep a little later, so the light moves down the page
  const box = (cls) => { const d = document.createElement("div"); d.className = "sk " + cls; d.style.setProperty("--d", (n++ * 0.06).toFixed(2) + "s"); return d; };
  const wrap = (cls, ...kids) => { const d = document.createElement("div"); d.className = cls; d.append(...kids); return d; };
  const rep = (k, f) => Array.from({ length: k }, f);
  const LAYOUTS = {
    system: () => [box("sk-h2"), box("sk-banner"),
      wrap("sk-grid", ...rep(4, () => wrap("sk-card", box("sk-l s"), box("sk-l"), box("sk-l m")))),
      wrap("sk-card", box("sk-l s"), box("sk-l"), box("sk-btn"))],
    people: () => [box("sk-h2"), ...rep(4, () => wrap("sk-card sk-row", box("sk-av"), wrap("sk-col", box("sk-l m"), box("sk-l s"))))],
    lines: () => rep(7, () => wrap("sk-seg", box("sk-time"), box("sk-chip"), wrap("sk-col", box("sk-l"), box("sk-l"), box("sk-l m")))),
  };
  window.skeleton = (container, kind) => {
    n = 0;
    const s = wrap("skeleton", ...LAYOUTS[kind]());
    s.setAttribute("aria-busy", "true");
    container.replaceChildren(s);
  };
  window.hasSkeleton = (container) => !!container.querySelector(":scope > .skeleton");
  window.fadeIn = (container) => {
    container.classList.remove("fadein");
    void container.offsetWidth; // restart the animation
    container.classList.add("fadein");
  };
})();
