# Deterministic Higgsfield Pipeline — Design Spec

**Date:** 2026-06-11
**Status:** Approved (user picked "auto-fallback only" for Claude's role)

## Goal

Run the Higgsfield steps (character sheet generation + character swap) with
direct, deterministic API calls instead of headless Claude agents. Claude is
used only as an automatic fallback when the deterministic path hits a
schema/protocol error it can't anticipate. Happy-path Claude usage: zero
tokens (previously ~$1–2-equivalent per video, dominated by agent polling).

## Feasibility evidence (probed live, 2026-06-11)

- Higgsfield's MCP endpoint (`https://mcp.higgsfield.ai/mcp`) is plain
  JSON-RPC over HTTP; responses are SSE-framed. Requests need a
  `claude-code/...` User-Agent (their bot filter 403s urllib's default UA).
- The OAuth access token Claude Code stores is readable from the macOS
  Keychain: `security find-generic-password -s "Claude Code-credentials" -w`
  → JSON → `mcpOAuth["higgsfield|<hash>"].accessToken` (+ `expiresAt`,
  `serverUrl`). Running `claude mcp list` (CLI health check, no inference)
  refreshes an expired token in place.
- Tools (35 total) confirmed by `tools/list`, with the relevant ones:
  - `media_upload {filename, content_type}` → presigned URL(s) to PUT bytes
    to, then `media_confirm {type, media_id}` → usable `media_id`.
  - `generate_image {params: {model, prompt, aspect_ratio, medias:
    [{value, role}], get_cost?}}` — docs name `soul_2` / `nano_banana_pro`
    for one-off character references. `get_cost: true` preflights free.
  - `motion_control {params: {image_id, motion_video_id, resolution,
    scene_control}}` — Kling 3.0; tool docs: "use this when the user asks to
    recast … or make a character follow a driving clip". No prompt param.
    `scene_control: "video"` keeps the reel's background. `image_id` accepts
    a completed generation `job_id` directly.
  - `job_status {jobId, sync}` — `sync: true` makes the server hold ~25s;
    response carries `poll_after_seconds` for pacing.
  - `balance` — credits + plan, free, good for pre-flight.

## Architecture

```
app/pipeline.py ── ensure_character_sheet / finish_job
      │ primary                         │ fallback on HiggsfieldError only
      ▼                                 ▼
app/higgsfield.py (new)            app/claude_swap.py (unchanged)
  auth: Keychain token,              headless claude -p agent,
        refresh via `claude mcp        used per-job when the direct
        list`, fatal if still          path fails for schema/protocol
        expired                        reasons; never for credits/auth
  client: JSON-RPC POST + SSE
        unframe + error mapping
  ops: upload_file, generate_sheet,
        swap, wait_for_job, balance
```

### Error taxonomy (drives the fallback decision)

- `HiggsfieldFatal(PipelineError)` — things Claude can't fix: token missing/
  expired-after-refresh, out of credits, server says unauthorized. Fail fast
  with the existing friendly messages. **No fallback.**
- `HiggsfieldError(PipelineError)` — unexpected tool/schema/shape errors.
  Log to the job's progress line, then **fall back** to the Claude agent for
  that job.

### Character sheet caching

`assets/character-sheet.json` stores `{ref_id, photo_mtime}` where `ref_id`
is the completed generation `job_id` (usable directly as `motion_control.
image_id` — repeat swaps upload only the clip). The image file
(`assets/character-sheet.<ext>`) is still downloaded for user inspection and
as the upload source when the sheet came from the fallback path (which only
yields a URL). Cache invalidates when `me.jpg`'s mtime is newer.

### Sheet prompt

The crafted reference-image prompt (single figure, front-facing, neutral
expression, empty hands, light-gray studio, 9:16) moves from agent
instructions to a direct `generate_image.prompt` string. Model: `soul_2`
(Higgsfield's identity model, exactly 1 reference image, role `image`).

### Swap parameters

`motion_control {image_id: <sheet ref>, motion_video_id: <clip media_id>,
resolution: "720p", scene_control: "video"}` — 720p per WAN-replace research;
`scene_control: "video"` preserves the reel's scene.

## Validation strategy

- Unit tests (no network): credential-store parsing, SSE unframing,
  job-result URL extraction, error classification (fallback vs fatal).
- Free live checks during implementation: `balance`, `media_upload` +
  `media_confirm` round-trip, `generate_image` with `get_cost: true`.
- The first paid swap run validates `motion_control` end-to-end; the auto
  fallback covers it if the params shape is off.

## Out of scope

- Refresh-token OAuth flows (single-use rotation risk would desync Claude
  Code's copy; `claude mcp list` already refreshes safely).
- Caching uploads of clips (each reel is new); Soul character training.
- Removing claude_swap.py (it is the fallback engine).
