// Shared behaviour for every page. Keep page-specific scripts (e.g. the visit
// counter) inline on their own page rather than adding them here.
(() => {
  // Footer year — any number of elements, no per-page IDs needed.
  const year = new Date().getFullYear();
  document.querySelectorAll(".js-year").forEach((el) => {
    el.textContent = year;
  });

  // Mobile nav.
  const toggle = document.querySelector(".nav-toggle");
  const nav = document.getElementById("site-nav");
  if (!toggle || !nav) return;

  const setOpen = (open) => {
    toggle.setAttribute("aria-expanded", String(open));
    nav.classList.toggle("is-open", open);
  };

  toggle.addEventListener("click", () => {
    setOpen(toggle.getAttribute("aria-expanded") !== "true");
  });

  // Close on Escape so keyboard users aren't trapped in an open menu.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
      setOpen(false);
      toggle.focus();
    }
  });

  // Reset when resizing back to the desktop layout, where the menu is always visible.
  window.matchMedia("(min-width: 761px)").addEventListener("change", (e) => {
    if (e.matches) setOpen(false);
  });
})();
