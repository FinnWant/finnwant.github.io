#!/usr/bin/env python3
"""
Hill-climbing design loop for a static HTML/CSS site.

Each cycle:  screenshot -> designer proposes ONE change -> builder edits files
             -> hard gates (console/page errors, broken local assets)
             -> judge council compares before/after pairwise (blind, random order)
             -> accept (git commit) or revert -> repeat
Stops when the council's median rubric score is >= TARGET on two independent
scoring passes, after too many rejects in a row, or at MAX_ITERS.

Usage:
    python hillclimb.py ./my-site --pages index.html about.html
Runs every agent through Claude Code headless mode (`claude -p`), so it uses your
Claude subscription login and usage limits, not an API key.
"""
import argparse
import json
import os
import random
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

# ---------------- config ----------------
DESIGNER_MODEL = "opus"     # Claude Code model aliases
BUILDER_MODEL = "opus"
JUDGE_MODEL = "sonnet"

TARGET = 9.0             # median rubric score needed (on two passes) to stop
MAX_ITERS = 40           # hard cap on cycles (cost control)
BOLD_AFTER = 3           # rejects in a row before asking for a bolder change
MAX_REJECTS = 6          # rejects in a row before giving up (local maximum)
CHECKPOINT_EVERY = 5     # pause for a human look after this many accepted changes
VIEWPORTS = {"desktop": (1440, 900), "mobile": (390, 844)}
MAX_SHOT_HEIGHT = 3000   # crop very long pages so images stay legible
EDITABLE = (".html", ".htm", ".css")

JUDGES = {
    "hierarchy": "Visual hierarchy and focus: is it obvious what matters most and where to look next?",
    "typography": "Typography and color: type scale, line length, contrast, palette harmony.",
    "layout": "Layout and spacing: alignment to a grid, consistent spacing rhythm, whitespace, density.",
    "mobile": "Mobile experience: readability, tap-target size, nothing cramped or overflowing at narrow widths.",
    "polish": "Overall polish and coherence: does it feel finished, consistent and intentional rather than templated?",
}

SHOT_DIR = Path(tempfile.mkdtemp(prefix="hillclimb_shots_"))
# Drop any API key so Claude Code falls back to your subscription login.
CLAUDE_ENV = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}


class UsageLimitError(RuntimeError):
    pass


# ---------------- helpers ----------------
def ask(model, content, max_tokens=2000, cwd=None, tools="Read"):
    """Run one headless Claude Code call. Image blocks are written to disk and
    passed as paths that Claude opens with its Read tool."""
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    parts = []
    for b in content:
        if b["type"] == "text":
            parts.append(b["text"])
        else:
            p = SHOT_DIR / f"{uuid.uuid4().hex}.png"
            p.write_bytes(b["data"])
            parts.append(f"[IMAGE: {p}]")
    if any(b["type"] == "image" for b in content):
        parts.insert(0, "Images are given as [IMAGE: path]. Open EVERY image with the Read "
                        "tool before answering; refer to them by their labels.")
    r = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "json",
         "--allowedTools", tools, "--add-dir", str(SHOT_DIR)],
        input="\n".join(parts), cwd=cwd or SHOT_DIR, env=CLAUDE_ENV,
        capture_output=True, text=True, timeout=900,
    )
    out = r.stdout.strip()
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        data = {"is_error": True, "result": out or r.stderr}
    if r.returncode or data.get("is_error"):
        msg = str(data.get("result", r.stderr))[-500:]
        if re.search(r"limit|quota|rate", msg, re.I):
            raise UsageLimitError(msg)
        raise RuntimeError(f"claude -p failed: {msg}")
    return data["result"]


def extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON in reply: {text[:200]}")
    return json.loads(m.group(0))


def img(png_bytes):
    return {"type": "image", "data": png_bytes}


def shots_content(shots, prefix=""):
    blocks = []
    for name, png in shots.items():
        blocks.append({"type": "text", "text": f"{prefix}{name}"})
        blocks.append(img(png))
    return blocks


class Git:
    def __init__(self, repo):
        self.repo = repo

    def __call__(self, *args):
        for attempt in range(10):
            r = subprocess.run(
                ["git", "-c", "user.name=hillclimb", "-c", "user.email=hillclimb@local",
                 "-c", "commit.gpgsign=false", *args],
                cwd=self.repo, capture_output=True, text=True,
            )
            if r.returncode == 0:
                return r.stdout
            # another program (VS Code, GitHub Desktop, OneDrive) briefly holds the lock
            if "index.lock" in r.stderr and attempt < 9:
                time.sleep(1)
                continue
            raise RuntimeError(f"git {' '.join(args[:2])} failed:\n{(r.stderr or r.stdout).strip()}")

    def setup(self):
        if not (self.repo / ".git").exists():
            self("init")
        self("checkout", "-B", "hillclimb")
        self("add", "-A")
        self("commit", "--allow-empty", "-m", "hillclimb: baseline")

    def commit(self, msg):
        self("add", "-A")
        self("commit", "-m", msg)

    def revert(self):
        self("reset", "--hard", "HEAD")
        self("clean", "-fd")

    def diff(self):
        self("add", "-A")
        return self("diff", "--cached")


def serve(site_dir):
    handler = partial(SimpleHTTPRequestHandler, directory=str(site_dir))
    handler.log_message = lambda *a, **k: None
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}"


# ---------------- rendering + gates ----------------
def render(browser, base_url, pages):
    """Screenshot every page at every viewport and collect errors."""
    shots, errors = {}, set()
    for vp_name, (w, h) in VIEWPORTS.items():
        page = browser.new_page(viewport={"width": w, "height": h})
        page.on("console", lambda m: m.type == "error" and errors.add(f"console: {m.text}"))
        page.on("pageerror", lambda e: errors.add(f"pageerror: {e}"))
        page.on("response", lambda r: r.status >= 400 and r.url.startswith(base_url)
                and errors.add(f"{r.status}: {r.url[len(base_url):]}"))
        for p in pages:
            page.goto(f"{base_url}/{p}", wait_until="networkidle")
            full_h = page.evaluate("document.documentElement.scrollHeight")
            shots[f"{p} [{vp_name}]"] = page.screenshot(
                full_page=True,
                clip={"x": 0, "y": 0, "width": w, "height": min(full_h, MAX_SHOT_HEIGHT)},
            )
        page.close()
    return shots, errors


# ---------------- agents ----------------
def designer(shots, rubric, feedback, history, bold):
    recent = "\n".join(f"- [{h['result']}] {h['change']}" for h in history[-8:]) or "(none yet)"
    size = ("Previous small changes have been rejected repeatedly. Propose a BOLDER, "
            "higher-impact change this time." if bold else
            "Propose ONE focused, well-scoped change.")
    prompt = f"""You are a senior web designer improving a static HTML/CSS website step by step.

Rubric the site is judged on:
{rubric}

Latest critiques from the judging council:
{feedback or '(none yet)'}

Recent attempts (don't repeat rejected ideas verbatim):
{recent}

{size} It must be implementable by editing HTML/CSS only (no JS frameworks or build tools).
Reply with JSON only: {{"change": "<specific, concrete instruction for a developer>", "why": "<one sentence>"}}"""
    return extract_json(ask(DESIGNER_MODEL, [*shots_content(shots), {"type": "text", "text": prompt}]))


def builder(site_dir, change, git):
    """Claude Code edits the site files directly (no shell access)."""
    prompt = f"""You are editing the static HTML/CSS website in the current directory.
Implement exactly this change, nothing more:

{change}

Only edit .html, .htm and .css files. Don't add JavaScript, build tools or new dependencies.
When done, reply with one line summarizing what you changed."""
    ask(BUILDER_MODEL, prompt, cwd=site_dir, tools="Read,Edit,Write,Glob,Grep")
    changed = [line[3:] for line in git("status", "--porcelain").splitlines()]
    if not changed:
        raise ValueError("builder made no changes")
    bad = [f for f in changed if not f.endswith(EDITABLE)]
    if bad:
        raise ValueError(f"builder touched non-HTML/CSS files: {bad}")
    return len(changed)


def pairwise(old, new):
    """Each judge sees both versions in random order. Returns list of 'new'/'old'/'tie'."""
    verdicts = []
    for name, lens in JUDGES.items():
        new_is_a = random.random() < 0.5
        a, b = (new, old) if new_is_a else (old, new)
        prompt = f"""Two versions (A and B) of the same website are shown above.
Judge ONLY on this criterion: {lens}
Small differences matter. Answer "tie" only if they are genuinely equal on this criterion.
Reply with JSON only: {{"winner": "A" | "B" | "tie", "reason": "<one sentence>"}}"""
        content = [*shots_content(a, "Version A - "), *shots_content(b, "Version B - "),
                   {"type": "text", "text": prompt}]
        r = extract_json(ask(JUDGE_MODEL, content, 500))
        w = r.get("winner", "tie")
        result = "tie" if w == "tie" else ("new" if (w == "A") == new_is_a else "old")
        verdicts.append({"judge": name, "result": result, "reason": r.get("reason", "")})
    return verdicts


def score(shots, rubric, anchors):
    """Absolute rubric scores from every judge. Returns (median overall, critiques)."""
    overalls, critiques = [], []
    anchor_blocks = []
    if anchors:
        anchor_blocks.append({"type": "text", "text": "REFERENCE: these sites are what a 9/10 looks like:"})
        anchor_blocks += [img(p.read_bytes()) for p in anchors]
    for name, lens in JUDGES.items():
        prompt = f"""Score the website shown above against this rubric. Be strict: 9 means it
holds up next to the reference sites; most decent sites are 6-7.
{rubric}

Pay particular attention to: {lens}
Reply with JSON only: {{"scores": {{"<criterion>": <1-10>, ...}}, "top_issue": "<the single most impactful thing to fix>"}}"""
        content = [*anchor_blocks, {"type": "text", "text": "SITE UNDER REVIEW:"},
                   *shots_content(shots), {"type": "text", "text": prompt}]
        r = extract_json(ask(JUDGE_MODEL, content, 800))
        vals = [float(v) for v in r["scores"].values()]
        overalls.append(sum(vals) / len(vals))
        critiques.append(f"- ({name}) {r.get('top_issue', '')}")
    return statistics.median(overalls), "\n".join(critiques), overalls


# ---------------- main loop ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("site_dir", type=Path)
    ap.add_argument("--pages", nargs="+", default=["index.html"])
    ap.add_argument("--rubric", type=Path, default=Path(__file__).with_name("rubric.md"))
    ap.add_argument("--anchors", type=Path, help="folder of reference screenshots (PNG) that count as 9/10")
    args = ap.parse_args()

    site = args.site_dir.resolve()
    rubric = args.rubric.read_text()
    anchors = sorted(args.anchors.glob("*.png")) if args.anchors else []
    runs = site.parent / f"{site.name}_hillclimb_runs"
    runs.mkdir(exist_ok=True)

    git = Git(site)
    git.setup()
    base_url = serve(site)
    history, rejects, accepted = [], 0, 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        cur_shots, base_errors = render(browser, base_url, args.pages)
        median, feedback, all_scores = score(cur_shots, rubric, anchors)
        print(f"baseline median {median:.2f}  {['%.1f' % s for s in all_scores]}")
        if base_errors:
            print(f"(baseline already has {len(base_errors)} errors; only NEW errors fail the gate)")

        for it in range(1, MAX_ITERS + 1):
            if median >= TARGET:
                confirm, _, _ = score(cur_shots, rubric, anchors)  # second independent pass
                print(f"confirm pass median {confirm:.2f}")
                if confirm >= TARGET:
                    print(f"STOP: council median >= {TARGET} on two passes.")
                    break

            log_dir = runs / f"iter_{it:03d}"
            log_dir.mkdir(exist_ok=True)
            bold = rejects >= BOLD_AFTER
            prop = designer(cur_shots, rubric, feedback, history, bold)
            print(f"\n[{it}] {'(bold) ' if bold else ''}{prop['change']}")
            record = {"iter": it, "change": prop["change"], "why": prop.get("why", "")}

            try:
                builder(site, prop["change"], git)
                new_shots, errors = render(browser, base_url, args.pages)
                new_errors = errors - base_errors
                if new_errors:
                    raise ValueError(f"gate failed: {sorted(new_errors)[:5]}")
                verdicts = pairwise(cur_shots, new_shots)
                wins = sum(v["result"] == "new" for v in verdicts)
                losses = sum(v["result"] == "old" for v in verdicts)
                record["verdicts"] = verdicts
                # accept: more judges prefer new than old, with at most one dissent
                ok = wins > losses and losses <= 1
                print(f"     judges: {wins} prefer new, {losses} prefer old")
            except UsageLimitError:
                git.revert()
                raise
            except Exception as e:
                ok, record["error"] = False, str(e)
                print(f"     rejected: {e}")

            if ok:
                (log_dir / "diff.patch").write_text(git.diff())
                git.commit(f"hillclimb {it}: {prop['change'][:70]}")
                cur_shots = new_shots
                median, feedback, all_scores = score(cur_shots, rubric, anchors)
                record.update(result="accepted", median=median, scores=all_scores)
                rejects, accepted = 0, accepted + 1
                print(f"     ACCEPTED  median {median:.2f}  {['%.1f' % s for s in all_scores]}")
            else:
                git.revert()
                record["result"] = "rejected"
                rejects += 1

            for name, png in cur_shots.items():
                safe = re.sub(r"[^\w.-]+", "_", name)
                (log_dir / f"current_{safe}.png").write_bytes(png)
            (log_dir / "record.json").write_text(json.dumps(record, indent=2))
            history.append(record)

            if rejects >= MAX_REJECTS:
                print(f"STOP: {MAX_REJECTS} rejects in a row (local maximum).")
                break
            if ok and accepted % CHECKPOINT_EVERY == 0:
                ans = input(f"Checkpoint: {accepted} changes accepted. Screenshots in {runs}. "
                            "Enter to continue, q to quit: ")
                if ans.strip().lower() == "q":
                    break
        else:
            print(f"STOP: reached MAX_ITERS={MAX_ITERS}.")

        browser.close()
    print(f"\nFinal median {median:.2f}. History is on the 'hillclimb' git branch; logs in {runs}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except UsageLimitError as e:
        print(f"\nSTOP: hit your Claude usage limit ({e}).\n"
              "Accepted changes are committed on the 'hillclimb' branch; rerun after your limit resets.")
        sys.exit(1)