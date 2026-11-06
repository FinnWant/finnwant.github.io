// Shared behaviour for every page. Keep page-specific scripts (e.g. the visit
// counter) inline on their own page rather than adding them here.
(() => {
  // Footer year — any number of elements, no per-page IDs needed.
  const year = new Date().getFullYear();
  document.querySelectorAll(".js-year").forEach((el) => {
    el.textContent = year;
  });

  // Scroll fade-in and card tilt. JS adds .reveal itself, so content stays visible
  // if this script never runs. Skipped entirely for reduced-motion users.
  if (matchMedia("(prefers-reduced-motion: no-preference)").matches) {
    const io = new IntersectionObserver(
      (entries) => {
        // Items entering together (a row of cards) appear one after another.
        entries
          .filter((e) => e.isIntersecting)
          .forEach((e, i) => {
            e.target.style.setProperty("--reveal-delay", `${i * 70}ms`);
            e.target.classList.add("is-visible");
            io.unobserve(e.target);
          });
      },
      { rootMargin: "0px 0px -10% 0px" }
    );
    document
      .querySelectorAll(
        ".Recent-Projects > h2, .highlights > h2, .card, .highlight, .about-section, .contact, .post-list li"
      )
      .forEach((el) => {
        el.classList.add("reveal");
        io.observe(el);
      });

    // Mouse only: touch has no hover position to tilt towards.
    if (matchMedia("(hover: hover) and (pointer: fine)").matches) {
      const MAX_TILT = 3; // degrees
      document.querySelectorAll(".card").forEach((card) => {
        card.addEventListener("pointermove", (e) => {
          const r = card.getBoundingClientRect();
          const x = (e.clientX - r.left) / r.width - 0.5;
          const y = (e.clientY - r.top) / r.height - 0.5;
          card.style.setProperty("--tilt-x", `${(-y * 2 * MAX_TILT).toFixed(2)}deg`);
          card.style.setProperty("--tilt-y", `${(x * 2 * MAX_TILT).toFixed(2)}deg`);
        });
        card.addEventListener("pointerleave", () => {
          card.style.removeProperty("--tilt-x");
          card.style.removeProperty("--tilt-y");
        });
      });
    }
  }

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
