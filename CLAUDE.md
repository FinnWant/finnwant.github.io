# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout — read this first

This repo (`github.com/FinnWant/finnwant.github.io`, branch `main`) is usually opened from its **parent directory** `personalWebsite/`, which is itself an unrelated empty git repo with no commits:

```
personalWebsite/            <- outer repo, empty, not the site
└── finnwant.github.io/     <- this repo — all site content and history
```

Run every git command from inside `finnwant.github.io/`. Committing from the outer directory will not touch the site.

## Build / test / deploy

There is no build step, package manager, test suite, or linter. It is hand-written static HTML + CSS.

- **Preview locally:** `python3 -m http.server 8000` from this directory, then open `http://localhost:8000`. Use a server rather than `file://` so relative paths and `fetch` behave like production.
- **Deploy:** the site is served from a self-hosted web server at home, reached through the Cloudflare-managed domain `https://finnwantland.dev`. It is **not** on GitHub Pages any more — GitHub is only the source repo, and pushing to `main` does not publish anything. The server must serve only the site files: never expose `.git/`, `worker/`, or `CLAUDE.md` from the web root.

## Architecture

Three top-level pages share `styles.css` and each carry a duplicated copy of the site chrome:

- `index.html` — hero, Highlights, "Recent Projects" cards (duplicated from `projects.html`), About Me, `#contact`
- `projects.html` — full project card list; cards are anchor targets (`#project-1`…`#project-4`), linked from the index
- `blog.html` — index of posts under `posts/`
- `styles.css` / `site.js` / `favicon.svg` — shared by all three

## The résumé

Every page links to **`Finnagin-Wantland-Resume.pdf` at the repo root** — nav item, hero button, and the contact section. The file is user-supplied and is intentionally not in the repo, so **the link 404s until it is added**. If the filename ever changes it must be updated in all three pages plus the `download` copy in the hero.

**The header/nav block is copy-pasted into all three pages.** Any nav change (new link, logo swap, `aria-current`) must be applied in `index.html`, `projects.html`, and `blog.html`. The same goes for project cards, which exist in both `index.html` and `projects.html`. This is the main maintenance cost of the site — there is no templating.

**All CSS lives in `styles.css`.** There are deliberately **no inline `<style>` blocks and no hardcoded hex colors in the HTML** — the pages previously had `<style>` tags scattered mid-body (inside `<nav>`, inside `.hero-image`) whose specificity silently overrode the stylesheet. Keep it that way.

**Everything is themed through custom properties.** `:root` defines the tokens; a `prefers-color-scheme: dark` block overrides them. Any new rule must use `var(--…)` for color — a literal hex will look correct in light mode and break in dark. Note that dark mode **cannot** reuse the brand red `#b10202` (it fails contrast on a dark background), so it swaps in a lightened `--accent` and flips button text to a dark `--accent-on`. The brand red appears exactly twice in the codebase, both as token declarations.

**`site.js` is shared by all pages** and handles the footer year (any `.js-year` element — no per-page IDs) and the mobile nav toggle. Page-specific scripts stay inline on their own page (the visit counter and contact form, both on `index.html`).

**Responsive breakpoint is 760px**, defined in both `styles.css` and the `matchMedia` reset in `site.js`. Changing one requires changing the other.

**Heading rule: exactly one `<h1>` per page**, and it is the page's own subject — not the site title, which is a `<span class="brand-name">` inside the header link. Project card headings are `<h3>` on the index (subordinate to the "Recent Projects" `<h2>`) and `<h2>` on the projects page where each card is a top-level entry; `styles.css` styles both identically.

**Visit counter** (`index.html` only) calls the public CounterAPI v2 service — no key or account needed, and it sends `Access-Control-Allow-Origin: *` so browser `fetch` works. `WORKSPACE`/`COUNTER` constants and the `visited_v1` localStorage key control it. A browser's first visit calls `/up`; later visits only read. Both endpoints return the same `{data:{up_count}}` shape, so `/up` doubles as the read — never pair an `/up` with a separate `GET`, since a `GET` issued before the increment returns a stale count.

When testing the counter by hand, use the plain read URL. Hitting `/up` from curl or a script permanently inflates the real public count.

**Contact form** (`index.html` only): clicking the email link opens a `<dialog>` form (the `mailto:` href is the no-JS fallback). It posts JSON to a Cloudflare Worker in `worker/`, which verifies the Turnstile token with `TURNSTILE_SECRET` (a Wrangler secret, never committed) and emails `TO_ADDRESS` via the `send_email` binding. The Worker runs on Cloudflare, not the home server, and is deployed separately with `npx wrangler deploy` from `worker/`. The page-side `CONTACT_ENDPOINT` and Turnstile `data-sitekey` must match the deployed Worker and widget; if the site's origin changes, update `ALLOWED_ORIGINS` in `worker/wrangler.toml` and the widget's hostname list in Cloudflare.

## Blog posts

`posts/*.html` are **generated files, not hand-written pages**:

- `Py_Learning_Notebook.html` — `jupyter nbconvert` output from a Python notebook
- `Blog_Post_2.html` — `pdf2htmlEX` output from a PDF

They are fully self-contained (own CSS, own `<head>`) and deliberately do not use `styles.css` or the site header. Do not hand-edit them to fix content — regenerate from the source notebook/PDF and replace the file. They are safe to reformat only if you are prepared to lose the change on the next regeneration.

Adding a post means appending an `<li>` to `.post-list` in `blog.html` with the title, date, and a one-line italic summary.

## Mistakes previously fixed here — don't reintroduce

- **Backslash paths.** `blog.html` once linked posts as `posts\Py_Learning_Notebook.html`. Backslashes are not path separators in URLs and 404 on a real web server. Always forward slashes.
- **Cross-page anchors without targets.** `index.html` project cards link to `projects.html#project-1`…`#project-4`; those `id`s must exist on the `<article>` elements in `projects.html`.
- **`<div>` inside `<p>`.** The browser auto-closes the paragraph, silently restructuring the hero.
- **Unclosed `<main>`** in `index.html`, which pulled the footer and scripts inside the content column.
- **Hardcoded colors and inline `<style>` blocks**, which broke dark mode and overrode the stylesheet.
- **Stale-read visit counter** — see the CounterAPI note above.

After editing markup, re-check structure and links — there is no linter or CI to catch this:

```bash
python3 -c "
from html.parser import HTMLParser
VOID={'area','base','br','col','embed','hr','img','input','link','meta','source','track','wbr'}
class P(HTMLParser):
    st=[]
    def handle_starttag(s,t,a):
        if t not in VOID: s.st.append((t,s.getpos()[0]))
    def handle_endtag(s,t):
        if t not in VOID and s.st: s.st.pop()
for f in ['index.html','projects.html','blog.html']:
    p=P(); p.st=[]; p.feed(open(f).read()); print(f, p.st or 'ok')"
```

## Content conventions

The site is a personal portfolio; content is first-person as Finnagin Wantland. Project cards follow a fixed shape: screenshot in `Images/`, `<h4>` title, description paragraph, `<i>Link to Repo:</i>` followed by the bare GitHub URL as both link text and href. In-progress projects add a `<strong>WORK IN PROGRESS</strong>` line plus a `<progress>` element.
