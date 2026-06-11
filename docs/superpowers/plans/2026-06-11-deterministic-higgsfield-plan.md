# Deterministic Higgsfield Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Claude-agent-driven Higgsfield steps with direct MCP JSON-RPC calls; keep the agent only as auto-fallback on schema errors.

**Architecture:** New `app/higgsfield.py` (auth via Keychain + `claude mcp list` refresh, JSON-RPC client with SSE unframing, ops: upload/sheet/swap/wait/balance). `app/pipeline.py` calls it first, falls back to `app/claude_swap.py` on `HiggsfieldError` only. Sheet ref id cached in `assets/character-sheet.json`.

**Tech stack:** Python 3.8 stdlib only. See the spec (`docs/superpowers/specs/2026-06-11-deterministic-higgsfield-design.md`) for probed tool schemas.

---

### Task 1: Pure helpers in app/higgsfield.py (TDD)

**Files:** Create `app/higgsfield.py`; Modify `tests/test_pipeline.py`

- [ ] Write failing tests for: `parse_credentials(raw_json)` (picks higgsfield mcpOAuth entry; HiggsfieldFatal when absent), `unframe(raw)` (SSE `data:` lines → last JSON payload; plain JSON passthrough), `find_media_url(obj, kinds)` (recursive scan of job-status payload for an https URL with video/image extension), `classify_tool_error(text)` (credit/auth/unauthorized → fatal, else retryable).
- [ ] Run: `python3 -m unittest tests.test_pipeline` → new tests FAIL (import error).
- [ ] Implement the pure helpers + `HiggsfieldError` / `HiggsfieldFatal` (subclass `PipelineError`).
- [ ] Run tests → PASS. Commit.

### Task 2: Auth + MCP client + live free checks

**Files:** Modify `app/higgsfield.py`

- [ ] Implement `_read_credentials()` (`security find-generic-password -s "Claude Code-credentials" -w`), `get_token()` (expiry check → `claude mcp list` refresh → re-read → fatal), `Client` (initialize on construct; `call(tool, args)` → `(structuredContent, content)`; JSON-RPC error / `isError` → classified exceptions; 401/403 → fatal).
- [ ] Live check (free): `python3 -c "from app.higgsfield import Client; c=Client(); print(c.call('balance', {}))"` → prints credits/plan.
- [ ] Commit.

### Task 3: Ops — upload, sheet, swap, wait

**Files:** Modify `app/higgsfield.py`

- [ ] `upload_file(client, path)` — `media_upload {filename, content_type}`; **probe the response shape live with a tiny PNG first** (free) and code field names to reality; PUT bytes via urllib; `media_confirm`; return media_id.
- [ ] `generate_sheet(client, photo_media_id)` — `generate_image {params: {model: "soul_2", prompt: SHEET_PROMPT, aspect_ratio: "9:16", medias: [{value, role: "image"}]}}` → job id. Validate params first via `get_cost: true` (free).
- [ ] `swap(client, image_ref, video_media_id)` — `motion_control {params: {image_id, motion_video_id, resolution: "720p", scene_control: "video"}}` → job id.
- [ ] `wait_for_job(client, job_id, progress)` — loop `job_status {jobId, sync: true}`; honor `poll_after_seconds`; surface progress %, 30-min cap; completed → `find_media_url`; failed → classified error.
- [ ] Live check: upload round-trip of a small file + `generate_image get_cost` → both succeed. Commit.

### Task 4: Pipeline wiring + fallback + cache

**Files:** Modify `app/pipeline.py`, `README.md`; tests for cache/fallback decision helpers as practical.

- [ ] `ensure_character_sheet(progress)` → deterministic: upload photo → generate_sheet → wait → download image + write `assets/character-sheet.json` `{ref_id, photo_mtime}`; returns `{"path":…, "ref_id":…}`. Cache hit: mtime check against json. Fallback on `HiggsfieldError` → claude_swap.create_character_sheet (ref_id absent → swap path uploads the image file).
- [ ] `finish_job` → balance pre-flight (0 credits → fatal message); upload clip; image ref = cached ref_id or upload sheet file; deterministic swap+wait; on `HiggsfieldError` → progress note + claude_swap.swap fallback; save result.
- [ ] Run full unit suite; server smoke test (selection flow unchanged).
- [ ] README: how-it-works + troubleshooting rows (token refresh, fallback note). Commit, push, restart server.
