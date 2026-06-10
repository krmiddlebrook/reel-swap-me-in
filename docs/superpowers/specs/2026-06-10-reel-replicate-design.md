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

## Architecture

```
Browser — public/index.html (paste URL → progress → result video)
   │ POST /api/replicate {reelUrl} → {jobId}
   │ GET  /api/jobs/:jobId          (poll progress)
   ▼
server.js — Express, in-memory job store, serves /output videos
   ▼
pipeline/run.js — orchestrates steps, reports progress
   ├─ 1. download.js  yt-dlp: reel URL → work/<job>/reel.mp4
   ├─ 2. prepare.js   ffprobe/ffmpeg: validate ≥5s, trim to ≤15s
   ├─ 3. swap.js      Claude Agent SDK + Higgsfield MCP:
   │                  upload reel + assets/me.jpg, run character-swap
   │                  generation, poll until done → result URL
   └─ 4. save         download result → output/<job>.mp4
```

Also runnable headless: `node replicate.js <reel-url>` (same pipeline, no server).

## Components

- **`server.js`** — Express app. `POST /api/replicate` validates input and starts a
  job; `GET /api/jobs/:id` returns `{status, step, detail, resultUrl?, error?}`.
  Serves `public/` and `output/`.
- **`pipeline/download.js`** — validates the URL is an Instagram reel/post URL,
  shells out to `yt-dlp` to fetch the MP4. Public reels only.
- **`pipeline/prepare.js`** — `ffprobe` for duration; reject <5s with a clear
  message; trim to first 15s when longer (`ffmpeg -t 15`, stream copy fallback to
  re-encode).
- **`pipeline/swap.js`** — runs a Claude agent (Agent SDK `query()`) connected to
  the Higgsfield MCP server. The agent's job: upload the prepared video and the
  user photo via Higgsfield tools, pick the character-swap model from the live
  catalog (WAN Animate Replace / Recast), submit the generation, wait for
  completion, and return strict JSON `{"videoUrl": "..."}`. Tool access is
  restricted to Higgsfield MCP tools (+ `higgsfield` CLI via Bash as fallback if
  the MCP upload path requires it).
- **`pipeline/run.js`** — sequences the steps, maps low-level failures to
  user-friendly errors, emits progress callbacks.
- **`public/index.html`** — single page, no build step: URL input, Go button,
  step-by-step progress, side-by-side original vs. result `<video>` players.
- **`assets/me.jpg`** — the stored photo of the user (drop-in, gitignored).

## Auth & prerequisites (one-time, in README)

1. `npm install` (Express + `@anthropic-ai/claude-agent-sdk`).
2. `yt-dlp` and `ffmpeg` installed (`brew install yt-dlp ffmpeg`).
3. Higgsfield MCP connected & authorized once:
   `claude mcp add --transport http higgsfield https://mcp.higgsfield.ai/mcp`,
   then run `/mcp` inside `claude` to complete the OAuth login. The Agent SDK
   reuses this stored auth. Requires a Higgsfield account with credits.
4. Claude Code auth (the Agent SDK uses it) — already present on this machine.
5. A clear, front-facing photo saved as `assets/me.jpg`.

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

- Unit tests (node:test): URL validation and trim/duration decision logic (pure
  functions, no network).
- Integration (manual, scripted): download+prepare against a real public reel.
- End-to-end: requires the user's Higgsfield OAuth + credits; run once after
  setup via `node replicate.js <url>`.

## Consent & content notes

- Only swap in **your own** photo (or someone who has consented).
- The original reel is someone's content — keep outputs for personal use and
  respect creators' rights and Higgsfield/Instagram terms.

## Out of scope (YAGNI)

- Multiple stored identities, auth/multi-user, queueing, audio voice clone,
  Instagram posting, mobile packaging, private-reel cookies.
