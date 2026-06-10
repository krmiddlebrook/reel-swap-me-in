# Reel Replicate Me — Design Spec

**Date:** 2026-06-10
**Status:** Approved (user pre-approved build in initial request)

## What it is

A dead-simple local app: paste an Instagram Reel URL, and it produces a replica of
that Reel with **you** (from a stored photo) swapped in as the main subject. One
input, one output, minimal knobs.

## How it works (high level)

Claude (via the Claude Agent SDK) orchestrates the **Higgsfield MCP server**
(`https://mcp.higgsfield.ai/mcp`). Higgsfield's character-swap capability
(Recast / WAN 2.2 Animate "Replace" mode) re-renders the person in a source
video with a character taken from a reference image, preserving the original
motion, pacing, and framing. Constraint: source clips must be **5–15 seconds**.

## Stack decision (driven by this machine's environment)

- System Node is v14 (Agent SDK needs 18+), but the **native `claude` CLI 2.1.170
  is installed** and shares the user's Claude login and MCP OAuth token store.
  → The swap step shells out to **headless `claude -p`** instead of the Agent SDK.
- No ffmpeg/yt-dlp installed, and the build sandbox can only reach
  github.com/npm/pypi. → `setup.sh` vendors **static binaries** of `yt-dlp`
  (yt-dlp/yt-dlp releases) and `ffmpeg` (eugeneware/ffmpeg-static releases) into
  `bin/`. Reel duration comes from yt-dlp metadata, so ffprobe isn't needed.
- Installed Python is 3.8 (anaconda). → The server uses **Python stdlib only**
  (`http.server.ThreadingHTTPServer`), zero pip dependencies.

## Architecture

```
Browser — public/index.html (paste URL → progress → result video)
   │ POST /api/replicate {reelUrl} → {jobId}
   │ GET  /api/jobs/<jobId>         (poll progress)
   ▼
app/server.py — stdlib HTTP server, in-memory job store, serves /output videos
   ▼
app/pipeline.py — orchestrates steps in a worker thread, reports progress
   ├─ 1. download   bin/yt-dlp: reel URL → work/<job>/reel.mp4 (+ duration)
   ├─ 2. prepare    bin/ffmpeg: validate ≥5s, trim to ≤15s
   ├─ 3. swap       app/claude_swap.py: headless `claude -p` with the
   │                Higgsfield MCP server (user-scope, OAuth done once) —
   │                agent uploads reel + assets/me.jpg, runs the character-swap
   │                generation (Recast / WAN Animate Replace), polls until done,
   │                returns strict JSON {"videoUrl": ...}
   └─ 4. save       download result URL → output/<job>.mp4
```

Also runnable headless: `python3 replicate.py <reel-url>` (same pipeline, no server).

## Components

- **`app/server.py`** — stdlib HTTP server. `POST /api/replicate` validates input
  and starts a job thread; `GET /api/jobs/<id>` returns
  `{status, step, detail, resultUrl?, error?}`. Serves `public/` and `output/`.
- **`app/pipeline.py`** — URL validation (pure function), yt-dlp download wrapper,
  duration check (<5s rejected, >15s trimmed via ffmpeg), step sequencing with
  progress callback, friendly error mapping.
- **`app/claude_swap.py`** — builds the agent prompt, runs
  `claude -p --output-format json --allowedTools "mcp__higgsfield,mcp__higgsfield__*"`,
  parses the strict-JSON result (`{"videoUrl"}` or `{"error"}`), 20-minute cap.
- **`public/index.html`** — single page, no build step: URL input, Go button,
  step-by-step progress, result `<video>` player.
- **`assets/me.jpg`** — the stored photo of the user (drop-in, gitignored).
- **`setup.sh`** — fetches the static binaries, registers the Higgsfield MCP
  server at user scope, prints the one remaining manual step (OAuth via `/mcp`).

## Auth & prerequisites (one-time, in README)

1. `./setup.sh` — vendors `bin/yt-dlp` + `bin/ffmpeg`, runs
   `claude mcp add --transport http --scope user higgsfield https://mcp.higgsfield.ai/mcp`.
2. Authorize once: run `claude`, type `/mcp`, complete the Higgsfield OAuth
   browser login. The token lands in the Claude Code credential store and is
   reused by headless `claude -p` runs. Requires a Higgsfield account with credits.
3. Claude Code login — already present on this machine.
4. A clear, front-facing photo saved as `assets/me.jpg`.

## Error handling

Every failure surfaces as a one-line human message in the UI:
- Bad/unsupported URL → "That doesn't look like an Instagram reel URL."
- yt-dlp failure → "Couldn't download this reel — it must be public."
- Reel shorter than 5s → "Reel too short — Higgsfield needs at least 5 seconds."
- Longer than 15s → not an error; trimmed to first 15s and noted in progress.
- Missing `assets/me.jpg` → setup instructions message.
- Higgsfield MCP unauthorized / out of credits / generation failure → the agent's
  error text passed through, prefixed with a pointer to the setup steps.
- Generation timeout (15 min cap) → fail the job with a retry suggestion.

## Testing

- Unit tests (stdlib `unittest`): URL validation, trim/duration decision logic,
  claude output JSON parsing (pure functions, no network).
- Integration (manual, scripted): download+prepare against a real public reel.
- End-to-end: requires the user's Higgsfield OAuth + credits; run once after
  setup via `python3 replicate.py <url>`.

## Consent & content notes

- Only swap in **your own** photo (or someone who has consented).
- The original reel is someone's content — keep outputs for personal use and
  respect creators' rights and Higgsfield/Instagram terms.

## Out of scope (YAGNI)

- Multiple stored identities, auth/multi-user, queueing, audio voice clone,
  Instagram posting, mobile packaging, private-reel cookies.
