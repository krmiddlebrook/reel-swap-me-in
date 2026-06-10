# Reel Replicate Me — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local app that takes an Instagram Reel URL and produces a replica with the user (from `assets/me.jpg`) swapped in as the main subject, via Claude + the Higgsfield MCP server.

**Architecture:** Python-stdlib HTTP server + one-page UI. A worker thread runs the pipeline: vendored `yt-dlp` downloads the reel, vendored `ffmpeg` trims it to Higgsfield's 5–15s window, then headless `claude -p` (connected to the Higgsfield MCP at user scope, OAuth done once interactively) uploads the clip + photo and runs the Recast/WAN-Animate character-swap generation, returning a video URL the pipeline saves to `output/`.

**Tech Stack:** Python 3.8 stdlib only (server, pipeline, tests via `unittest`); static `yt-dlp` and `ffmpeg` binaries from GitHub releases; native `claude` CLI 2.1.170 (already installed) for the agent step; plain HTML/JS page, no build step.

**Why not Node/Agent SDK:** system Node is v14 (SDK needs 18+); the native claude CLI provides the same agent + MCP capability headlessly.

---

### Task 1: Scaffold — directories, .gitignore, setup.sh

**Files:**
- Create: `.gitignore`
- Create: `setup.sh`
- Create: `assets/README.md`

- [ ] **Step 1: Create `.gitignore`**

```gitignore
bin/
work/
output/
assets/me.jpg
__pycache__/
*.pyc
```

- [ ] **Step 2: Create `setup.sh`**

```bash
#!/bin/bash
# One-time setup: vendor static binaries + register the Higgsfield MCP server.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p bin assets work output

if [ ! -x bin/yt-dlp ]; then
  echo "Fetching yt-dlp…"
  curl -fL -o bin/yt-dlp \
    "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"
  chmod +x bin/yt-dlp
fi

if [ ! -x bin/ffmpeg ]; then
  ARCH=$(uname -m)
  if [ "$ARCH" = "arm64" ]; then F="ffmpeg-darwin-arm64"; else F="ffmpeg-darwin-x64"; fi
  echo "Fetching ffmpeg ($F)…"
  curl -fL -o bin/ffmpeg \
    "https://github.com/eugeneware/ffmpeg-static/releases/latest/download/$F"
  chmod +x bin/ffmpeg
fi

if ! claude mcp list 2>/dev/null | grep -q "^higgsfield:"; then
  echo "Registering Higgsfield MCP server (user scope)…"
  claude mcp add --transport http --scope user higgsfield https://mcp.higgsfield.ai/mcp
fi

echo ""
echo "Setup complete. Two manual steps remain:"
echo "  1. Authorize Higgsfield once: run 'claude', type '/mcp', pick higgsfield, log in."
echo "  2. Save a clear front-facing photo of yourself as assets/me.jpg"
```

- [ ] **Step 3: Create `assets/README.md`**

```markdown
Drop a clear, front-facing photo of yourself here named `me.jpg`.
It is gitignored — your photo never leaves this machine except to
Higgsfield when you run a swap.
```

- [ ] **Step 4: Run setup and verify binaries**

Run: `chmod +x setup.sh && ./setup.sh && bin/yt-dlp --version && bin/ffmpeg -version | head -1`
Expected: yt-dlp version date + "ffmpeg version …" line. (MCP registration may print the manual-auth note.)

- [ ] **Step 5: Commit**

```bash
git add .gitignore setup.sh assets/README.md
git commit -m "feat: scaffold with setup script for binaries and Higgsfield MCP"
```

---

### Task 2: Pipeline pure functions (TDD)

**Files:**
- Create: `app/__init__.py` (empty)
- Create: `app/pipeline.py` (pure functions only in this task)
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pipeline.py
import unittest

from app.pipeline import PipelineError, plan_trim, validate_reel_url
from app.claude_swap import parse_agent_output


class TestValidateReelUrl(unittest.TestCase):
    def test_accepts_reel_url(self):
        self.assertEqual(
            validate_reel_url("https://www.instagram.com/reel/Cabc123_X-/"),
            "https://www.instagram.com/reel/Cabc123_X-/",
        )

    def test_accepts_reels_p_tv_and_strips_query(self):
        self.assertEqual(
            validate_reel_url("https://instagram.com/p/Cabc123/?igsh=xyz"),
            "https://instagram.com/p/Cabc123/",
        )
        validate_reel_url("https://www.instagram.com/reels/Cabc123/")
        validate_reel_url("https://www.instagram.com/tv/Cabc123/")

    def test_rejects_non_instagram(self):
        for bad in ["", "not a url", "https://youtube.com/watch?v=x",
                    "https://instagram.com/someuser/"]:
            with self.assertRaises(PipelineError):
                validate_reel_url(bad)


class TestPlanTrim(unittest.TestCase):
    def test_too_short_raises(self):
        with self.assertRaises(PipelineError):
            plan_trim(3.2)

    def test_in_range_no_trim(self):
        self.assertIsNone(plan_trim(5.0))
        self.assertIsNone(plan_trim(12.0))
        self.assertIsNone(plan_trim(15.0))

    def test_too_long_trims_to_15(self):
        self.assertEqual(plan_trim(42.0), 15.0)

    def test_unknown_duration_trims_defensively(self):
        self.assertEqual(plan_trim(None), 15.0)


class TestParseAgentOutput(unittest.TestCase):
    def _envelope(self, result_text, is_error=False):
        import json
        return json.dumps({"type": "result", "is_error": is_error,
                           "result": result_text})

    def test_success_json(self):
        out = self._envelope('{"videoUrl": "https://cdn.example/v.mp4"}')
        self.assertEqual(parse_agent_output(out), "https://cdn.example/v.mp4")

    def test_json_embedded_in_prose(self):
        out = self._envelope(
            'Done! Here is the result:\n{"videoUrl": "https://cdn.example/v.mp4"}')
        self.assertEqual(parse_agent_output(out), "https://cdn.example/v.mp4")

    def test_agent_reported_error(self):
        out = self._envelope('{"error": "Out of credits"}')
        with self.assertRaises(PipelineError) as ctx:
            parse_agent_output(out)
        self.assertIn("Out of credits", str(ctx.exception))

    def test_envelope_error(self):
        out = self._envelope("MCP server not authorized", is_error=True)
        with self.assertRaises(PipelineError):
            parse_agent_output(out)

    def test_garbage_raises(self):
        with self.assertRaises(PipelineError):
            parse_agent_output("not json at all")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_pipeline -v` (from repo root)
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Implement the pure functions**

```python
# app/pipeline.py
"""Reel-replication pipeline: download → prepare → swap → save."""
import os
import re
import subprocess
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(ROOT, "bin")
YTDLP = os.path.join(BIN_DIR, "yt-dlp")
FFMPEG = os.path.join(BIN_DIR, "ffmpeg")
USER_PHOTO = os.path.join(ROOT, "assets", "me.jpg")
WORK_DIR = os.path.join(ROOT, "work")
OUTPUT_DIR = os.path.join(ROOT, "output")

MIN_SECONDS = 5.0   # Higgsfield Recast accepts 5–15s clips
MAX_SECONDS = 15.0


class PipelineError(Exception):
    """An error whose message is safe to show to the user."""


_REEL_URL = re.compile(
    r"^https?://(www\.)?instagram\.com/(reel|reels|p|tv)/[A-Za-z0-9_-]+/?(\?.*)?$"
)


def validate_reel_url(url):
    url = (url or "").strip()
    if not _REEL_URL.match(url):
        raise PipelineError("That doesn't look like an Instagram reel URL.")
    return url.split("?")[0]


def plan_trim(duration_seconds):
    """Return the length to trim to, or None when no trim is needed."""
    if duration_seconds is None:
        return MAX_SECONDS
    if duration_seconds < MIN_SECONDS:
        raise PipelineError(
            "Reel too short — Higgsfield needs at least 5 seconds.")
    if duration_seconds > MAX_SECONDS:
        return MAX_SECONDS
    return None
```

Also create empty `app/__init__.py`, empty `tests/__init__.py`, and a stub `app/claude_swap.py` so the import in the test resolves (the real implementation lands in Task 3):

```python
# app/claude_swap.py (stub — fully implemented in Task 3)
from app.pipeline import PipelineError


def parse_agent_output(stdout):
    raise PipelineError("not implemented")
```

- [ ] **Step 4: Run tests — pure-function tests pass, parse tests still fail**

Run: `python3 -m unittest tests.test_pipeline -v`
Expected: URL + trim tests PASS; `TestParseAgentOutput` tests FAIL (stub).

- [ ] **Step 5: Commit**

```bash
git add app/ tests/
git commit -m "feat: pipeline pure functions (URL validation, trim planning) with tests"
```

---

### Task 3: Claude + Higgsfield swap step

**Files:**
- Create: `app/claude_swap.py` (replace stub)
- Test: `tests/test_pipeline.py` (already written — `TestParseAgentOutput`)

- [ ] **Step 1: Implement `app/claude_swap.py`**

```python
# app/claude_swap.py
"""Run the character swap via headless Claude Code + the Higgsfield MCP server.

Prereq (one-time): `claude mcp add --transport http --scope user higgsfield
https://mcp.higgsfield.ai/mcp`, then OAuth via `/mcp` inside `claude`.
Headless `claude -p` reuses the stored token.
"""
import json
import subprocess

from app.pipeline import PipelineError

SWAP_TIMEOUT_SECONDS = 30 * 60  # video generation can take many minutes

PROMPT = """You are connected to the Higgsfield MCP server (tools prefixed mcp__higgsfield__).

Goal: create a character-swapped version of a video.
- Source video (local file): {video}
- Reference image of the replacement person (local file): {photo}

Steps:
1. Look at the Higgsfield tools you have available.
2. Upload the source video and the reference image using the appropriate Higgsfield upload tool(s).
3. Find the character-swap model in the model catalog. It is the one that replaces the person in an existing video with a character from a reference image while keeping the original motion — called Recast, or WAN 2.2 Animate in "replace" mode.
4. Submit the generation with the uploaded video as the source/motion input and the uploaded image as the character reference. Use sensible defaults for other parameters.
5. Wait and poll until the generation completes. It can take several minutes — keep polling.
6. Reply with ONLY one JSON object as the final line, no markdown fences:
   - success: {{"videoUrl": "<direct URL of the generated video file>"}}
   - failure: {{"error": "<one short sentence saying what failed>"}}

Rules:
- Use only Higgsfield MCP tools.
- If a tool fails for auth or credit reasons, stop and report it via the error JSON.
- Generate only the requested character swap, nothing else."""


def _extract_json(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            pass
    return None


def parse_agent_output(stdout):
    envelope = _extract_json(stdout or "")
    if envelope is None:
        raise PipelineError(
            "Claude returned unparseable output — try again, and check "
            "'claude mcp list' shows higgsfield as connected.")
    if envelope.get("is_error"):
        raise PipelineError(
            "Claude run failed: %s — if this mentions auth, redo the /mcp "
            "login in claude." % str(envelope.get("result"))[:300])
    payload = _extract_json(envelope.get("result") or "")
    if payload and payload.get("videoUrl"):
        return payload["videoUrl"]
    if payload and payload.get("error"):
        raise PipelineError("Higgsfield step failed: %s" % payload["error"])
    raise PipelineError(
        "The agent finished without producing a video URL. Raw reply: %s"
        % str(envelope.get("result"))[:300])


def swap(video_path, photo_path):
    """Returns the URL of the generated (character-swapped) video."""
    cmd = [
        "claude", "-p", PROMPT.format(video=video_path, photo=photo_path),
        "--output-format", "json",
        "--allowedTools", "mcp__higgsfield,mcp__higgsfield__*",
        "--max-turns", "80",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=SWAP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise PipelineError("Generation timed out after 30 minutes — try again.")
    except FileNotFoundError:
        raise PipelineError("The 'claude' CLI was not found on PATH.")
    if proc.returncode != 0 and not proc.stdout.strip():
        raise PipelineError(
            "Claude exited with an error: %s" % (proc.stderr or "")[:300])
    return parse_agent_output(proc.stdout)
```

- [ ] **Step 2: Run all tests — everything passes**

Run: `python3 -m unittest tests.test_pipeline -v`
Expected: all tests PASS (URL, trim, and all 5 parse tests).

- [ ] **Step 3: Commit**

```bash
git add app/claude_swap.py
git commit -m "feat: headless claude -p swap step against Higgsfield MCP"
```

---

### Task 4: Download, prepare, and job orchestration

**Files:**
- Modify: `app/pipeline.py` (append below the pure functions)

- [ ] **Step 1: Append the subprocess + orchestration functions to `app/pipeline.py`**

```python
def _require_setup():
    missing = []
    if not os.path.exists(YTDLP):
        missing.append("bin/yt-dlp")
    if not os.path.exists(FFMPEG):
        missing.append("bin/ffmpeg")
    if missing:
        raise PipelineError(
            "Missing %s — run ./setup.sh first." % " and ".join(missing))
    if not os.path.exists(USER_PHOTO):
        raise PipelineError(
            "No photo found — save a clear front-facing photo of yourself "
            "as assets/me.jpg.")


def download_reel(url, job_dir):
    """Download the reel; returns (mp4_path, duration_seconds_or_None)."""
    os.makedirs(job_dir, exist_ok=True)
    out_path = os.path.join(job_dir, "reel.mp4")
    cmd = [
        YTDLP, "--no-playlist", "-f", "mp4/best",
        "--no-simulate", "--print", "%(duration)s",
        "-o", out_path, url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 or not os.path.exists(out_path):
        raise PipelineError(
            "Couldn't download this reel — make sure the URL is right and "
            "the reel is public.")
    duration = None
    try:
        duration = float(proc.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        pass
    return out_path, duration


def prepare_clip(path, duration, job_dir):
    """Trim to Higgsfield's window when needed; returns path to use."""
    trim_to = plan_trim(duration)
    if trim_to is None:
        return path
    trimmed = os.path.join(job_dir, "reel-trimmed.mp4")
    copy_cmd = [FFMPEG, "-y", "-i", path, "-t", str(trim_to), "-c", "copy", trimmed]
    proc = subprocess.run(copy_cmd, capture_output=True, timeout=120)
    if proc.returncode != 0 or not os.path.exists(trimmed):
        # stream-copy can fail on some keyframe layouts — re-encode instead
        reencode = [FFMPEG, "-y", "-i", path, "-t", str(trim_to), trimmed]
        proc = subprocess.run(reencode, capture_output=True, timeout=300)
        if proc.returncode != 0:
            raise PipelineError("Couldn't trim the reel to 15 seconds.")
    return trimmed


def save_result(video_url, job_id):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, "%s.mp4" % job_id)
    try:
        urllib.request.urlretrieve(video_url, out)
    except Exception:
        raise PipelineError(
            "Generation succeeded but downloading the result failed. "
            "URL: %s" % video_url)
    return out


def run_job(job_id, url, progress):
    """Full pipeline. progress(step, detail) is called before each step.
    Returns the path of the final video under output/."""
    from app import claude_swap  # late import: keeps pure functions test-light

    _require_setup()
    url = validate_reel_url(url)
    job_dir = os.path.join(WORK_DIR, job_id)

    progress("downloading", "Downloading the reel…")
    path, duration = download_reel(url, job_dir)

    progress("preparing", "Checking length (Higgsfield needs 5–15s)…")
    clip = prepare_clip(path, duration, job_dir)
    if clip != path:
        progress("preparing", "Reel was longer than 15s — using the first 15s.")

    progress("swapping",
             "Claude + Higgsfield are re-casting you into the reel "
             "(this can take several minutes)…")
    video_url = claude_swap.swap(clip, USER_PHOTO)

    progress("saving", "Downloading your generated video…")
    return save_result(video_url, job_id)
```

- [ ] **Step 2: Run the test suite (regression check)**

Run: `python3 -m unittest tests.test_pipeline -v`
Expected: all PASS.

- [ ] **Step 3: Integration-check download+prepare against a real public reel**

Run: `python3 -c "from app.pipeline import download_reel, prepare_clip; p,d = download_reel('https://www.instagram.com/reel/<KNOWN_PUBLIC_REEL>/', 'work/smoke'); print(p,d); print(prepare_clip(p,d,'work/smoke'))"`
Expected: prints the mp4 path + duration, then the (possibly trimmed) path. *Requires network; if Instagram blocks the datacenter/sandbox, note it and rely on the user's run.*

- [ ] **Step 4: Commit**

```bash
git add app/pipeline.py
git commit -m "feat: download, trim, and job orchestration"
```

---

### Task 5: Server + one-page UI + CLI

**Files:**
- Create: `app/server.py`
- Create: `public/index.html`
- Create: `replicate.py`

- [ ] **Step 1: Create `app/server.py`**

```python
# app/server.py
"""Tiny stdlib web server for the reel-replicate app. No dependencies."""
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app import pipeline

PORT = 8787
PUBLIC_DIR = os.path.join(pipeline.ROOT, "public")

_jobs = {}
_jobs_lock = threading.Lock()


def _set_job(job_id, **fields):
    with _jobs_lock:
        _jobs.setdefault(job_id, {}).update(fields)


def _run(job_id, url):
    def progress(step, detail):
        _set_job(job_id, status="running", step=step, detail=detail)
    try:
        out_path = pipeline.run_job(job_id, url, progress)
        _set_job(job_id, status="done", step="done",
                 detail="Your reel is ready!",
                 resultUrl="/output/%s" % os.path.basename(out_path))
    except pipeline.PipelineError as exc:
        _set_job(job_id, status="error", error=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface anything to the UI
        _set_job(job_id, status="error",
                 error="Unexpected error: %s" % exc)


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, content_type):
        try:
            with open(path, "rb") as fh:
                body = fh.read()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._file(os.path.join(PUBLIC_DIR, "index.html"),
                       "text/html; charset=utf-8")
        elif self.path.startswith("/api/jobs/"):
            job_id = self.path.rsplit("/", 1)[-1]
            with _jobs_lock:
                job = dict(_jobs.get(job_id) or {})
            if job:
                self._json(200, job)
            else:
                self._json(404, {"error": "unknown job"})
        elif self.path.startswith("/output/"):
            name = os.path.basename(self.path)  # no traversal
            self._file(os.path.join(pipeline.OUTPUT_DIR, name), "video/mp4")
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/api/replicate":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
            url = pipeline.validate_reel_url(data.get("reelUrl"))
        except pipeline.PipelineError as exc:
            self._json(400, {"error": str(exc)})
            return
        except ValueError:
            self._json(400, {"error": "Invalid request body."})
            return
        job_id = uuid.uuid4().hex[:12]
        _set_job(job_id, status="running", step="starting", detail="Starting…")
        threading.Thread(target=_run, args=(job_id, url), daemon=True).start()
        self._json(202, {"jobId": job_id})

    def log_message(self, fmt, *args):  # quieter console
        if "/api/jobs/" not in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Reel Replicate Me → http://localhost:%d" % PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create `public/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reel Replicate Me</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:#0e0d12; color:#f3f1ec; font:16px/1.5 -apple-system, "Segoe UI", sans-serif; }
  main { width:min(560px, 92vw); padding:40px 0; text-align:center; }
  h1 { font-size:1.7rem; margin:0 0 4px; letter-spacing:-.02em; }
  p.sub { color:#9a96a8; margin:0 0 28px; }
  form { display:flex; gap:8px; }
  input { flex:1; padding:13px 16px; border-radius:12px; border:1px solid #2c2a36;
          background:#17151e; color:inherit; font-size:15px; outline:none; }
  input:focus { border-color:#7c6cf2; }
  button { padding:13px 22px; border:0; border-radius:12px; background:#7c6cf2; color:#fff;
           font-size:15px; font-weight:600; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
  #status { margin-top:26px; min-height:24px; color:#c9c5d8; }
  #status.error { color:#ff7b7b; }
  .spinner { display:inline-block; width:14px; height:14px; margin-right:8px; vertical-align:-2px;
             border:2px solid #7c6cf2; border-top-color:transparent; border-radius:50%;
             animation:spin .8s linear infinite; }
  @keyframes spin { to { transform:rotate(360deg); } }
  video { margin-top:24px; width:100%; max-height:70vh; border-radius:16px; background:#000; }
  a.dl { display:inline-block; margin-top:12px; color:#a99cff; }
</style>
</head>
<body>
<main>
  <h1>Reel Replicate Me</h1>
  <p class="sub">Paste an Instagram Reel URL — get it back starring you.</p>
  <form id="f">
    <input id="url" type="url" placeholder="https://www.instagram.com/reel/…" required>
    <button id="go" type="submit">Replicate</button>
  </form>
  <div id="status"></div>
  <div id="result"></div>
</main>
<script>
const f = document.getElementById("f"), urlEl = document.getElementById("url"),
      go = document.getElementById("go"), statusEl = document.getElementById("status"),
      resultEl = document.getElementById("result");
let timer = null;

function setStatus(text, { spin = false, error = false } = {}) {
  statusEl.className = error ? "error" : "";
  statusEl.innerHTML = (spin ? '<span class="spinner"></span>' : "") + text;
}

async function poll(jobId) {
  try {
    const r = await fetch(`/api/jobs/${jobId}`);
    const job = await r.json();
    if (job.status === "done") {
      clearInterval(timer); go.disabled = false;
      setStatus("Done — here's you:");
      resultEl.innerHTML =
        `<video controls autoplay loop src="${job.resultUrl}"></video>` +
        `<a class="dl" href="${job.resultUrl}" download>Download video</a>`;
    } else if (job.status === "error") {
      clearInterval(timer); go.disabled = false;
      setStatus(job.error || "Something went wrong.", { error: true });
    } else {
      setStatus(job.detail || "Working…", { spin: true });
    }
  } catch { /* transient — keep polling */ }
}

f.addEventListener("submit", async (e) => {
  e.preventDefault();
  resultEl.innerHTML = ""; go.disabled = true;
  setStatus("Starting…", { spin: true });
  try {
    const r = await fetch("/api/replicate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reelUrl: urlEl.value }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "Request failed");
    timer = setInterval(() => poll(data.jobId), 2000);
  } catch (err) {
    go.disabled = false;
    setStatus(err.message, { error: true });
  }
});
</script>
</body>
</html>
```

- [ ] **Step 3: Create `replicate.py` (CLI mode)**

```python
#!/usr/bin/env python3
"""Headless mode: python3 replicate.py <instagram-reel-url>"""
import sys
import uuid

from app import pipeline


def main():
    if len(sys.argv) != 2:
        print("usage: python3 replicate.py <instagram-reel-url>")
        return 2
    job_id = uuid.uuid4().hex[:12]
    try:
        out = pipeline.run_job(job_id, sys.argv[1],
                               lambda step, detail: print("[%s] %s" % (step, detail)))
    except pipeline.PipelineError as exc:
        print("error: %s" % exc)
        return 1
    print("done: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Smoke-test the server**

Run: `python3 -m app.server & sleep 1; curl -s http://localhost:8787/ | head -3; curl -s -X POST http://localhost:8787/api/replicate -H 'Content-Type: application/json' -d '{"reelUrl":"junk"}'; kill %1`
Expected: HTML doctype lines, then `{"error": "That doesn't look like an Instagram reel URL."}`

- [ ] **Step 5: Commit**

```bash
git add app/server.py public/index.html replicate.py
git commit -m "feat: stdlib web server, one-page UI, and CLI mode"
```

---

### Task 6: README, final verification, commit

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`** — cover: what it is; one-time setup (`./setup.sh`, `/mcp` OAuth in claude, `assets/me.jpg`, Higgsfield account + credits); run (`python3 -m app.server` → http://localhost:8787, or CLI); how it works (4 pipeline steps); troubleshooting (private reels, <5s reels, `claude mcp list` shows higgsfield ✓, credits); consent & content note (own photo only, respect original creators' rights and Higgsfield/Instagram ToS).

- [ ] **Step 2: Full verification pass**

Run: `python3 -m unittest discover -s tests -v` — all PASS.
Run: server smoke test from Task 5 Step 4 — passes.
Run (only if Higgsfield OAuth already completed): `python3 replicate.py <public-reel-url>` — produces `output/<job>.mp4`. Otherwise document as the user's first-run step.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/
git commit -m "docs: README with setup, usage, and consent notes"
```
