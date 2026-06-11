# Shareability (App-Owned OAuth) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anyone can clone the repo, run `./setup.sh`, start the server, click "Connect Higgsfield," drop a photo in the page, and swap reels — no Claude Code, no Anthropic account, no macOS requirement.

**Architecture:** New `app/oauth.py` implements the full OAuth client against `mcp.higgsfield.ai` (RFC 8414 discovery, RFC 7591 dynamic client registration — both live-verified: registration returned 201 with `http://localhost:8787/oauth/callback` accepted — plus authorization-code + PKCE S256 and refresh-token renewal). Tokens live in a gitignored, chmod-600 `.higgsfield-credentials.json`. `higgsfield.get_token()` prefers the app-owned token, falls back to the Claude Code Keychain (preserves the current working setup), then errors with a pointer to the Connect button. The server gains `/api/status`, `/api/auth/start`, `/oauth/callback`, and `/api/photo` (raw-bytes upload, magic-byte validation); the page gains a setup banner. `setup.sh` detects OS/arch (macOS + Linux, x64 + arm64); the Claude MCP registration becomes optional. The Claude agent fallback is skipped when no `claude` CLI exists.

**Tech Stack:** Python 3.8 stdlib only (urllib, hashlib, base64, secrets-equivalent via os.urandom). Endpoints (probed live): authorize `https://mcp.higgsfield.ai/oauth2/authorize`, token `…/oauth2/token`, register `…/oauth2/register`; scopes `openid email offline_access`; PKCE S256; grants `authorization_code` + `refresh_token`.

---

### Task 1: OAuth pure helpers (TDD)

**Files:** Create `app/oauth.py`; Test `tests/test_oauth.py`; Modify `tests/test_pipeline.py`, `.gitignore`

- [ ] Failing tests: `make_pkce` (challenge == b64url(sha256(verifier)), no `=` padding), `token_state` ("absent" without token; "valid" when `expires_at` > now+60; "refreshable" when expired with refresh_token; "absent" when expired without), `save_credentials`/`load_credentials` round-trip to a tmp path with mode 0600, `load_credentials` returns `{}` on missing/garbage files, and `detect_image_ext` in pipeline (JPEG `\xff\xd8\xff` → ".jpg", PNG `\x89PNG` → ".png", garbage → None).
- [ ] Implement the helpers; `.gitignore` gains `.higgsfield-credentials.json`.
- [ ] Run `python3 -m unittest discover -s tests` → PASS. Commit.

### Task 2: OAuth network flow + token priority

**Files:** Modify `app/oauth.py`, `app/higgsfield.py`

- [ ] `oauth.py`: `_endpoints()` (cached RFC 8414 discovery), `ensure_client(port)` (reuse stored client_id else DCR with `token_endpoint_auth_method: "none"` and both localhost/127.0.0.1 redirects), `begin_login(port)` (PKCE pair + state into module `_pending`, returns authorize URL with `resource` param), `handle_callback(code, state, port)` (state check → code exchange with verifier → `_store_tokens`), `get_app_token()` (valid → return; refreshable → refresh grant, rotation-safe; else None), `connected()`.
- [ ] `higgsfield.get_token()`: try `oauth.get_app_token()` first (returns `(token, MCP_URL)` with `MCP_URL = "https://mcp.higgsfield.ai/mcp"`); else existing Keychain path (wrap `security` invocation so a missing binary on Linux raises the friendly fatal); final fatal message points at the Connect button.
- [ ] Tests still pass (network paths exercised live in Task 5). Commit.

### Task 3: Server routes + setup banner UI

**Files:** Modify `app/server.py`, `public/index.html`

- [ ] Routes: `GET /api/status` → `{connected, source: "app"|"claude"|null, photo: bool}`; `POST /api/auth/start` → `{authUrl}`; `GET /oauth/callback` → exchanges and returns a tiny "Connected — close this tab" HTML page (error param → error page); `POST /api/photo` → raw body ≤ 20MB, `pipeline.detect_image_ext` gate, saves `assets/me.<ext>`, removes the other variant.
- [ ] UI: setup banner with two cards (Connect button → opens `authUrl` in a new tab, polls status; photo file input → POSTs bytes); Replicate button disabled until status is ready.
- [ ] Smoke: `/api/status` returns sane JSON; bad photo bytes → 400. Commit.

### Task 4: Photo-path flexibility, optional fallback, cross-OS setup.sh

**Files:** Modify `app/pipeline.py`, `app/claude_swap.py` (none needed — paths passed in), `setup.sh`

- [ ] `pipeline.user_photo()` returns the first existing `assets/me.{jpg,jpeg,png}` or None; `_require_setup`, `_sheet_cache`, `ensure_character_sheet` use it.
- [ ] Fallback gating: in both `ensure_character_sheet` and `finish_job`, fall back to the Claude agent only when `shutil.which("claude")` exists; otherwise re-raise with "(Claude fallback unavailable — claude CLI not installed)".
- [ ] `setup.sh`: `uname -s`/`-m` matrix — Darwin→`yt-dlp_macos` + `ffmpeg-darwin-{arm64,x64}`; Linux→`yt-dlp_linux{,_aarch64}` + `ffmpeg-linux-{x64,arm64}`; the `claude mcp add` block runs only if `claude` is installed and is labeled optional.
- [ ] Tests pass. Commit.

### Task 5: Live verification, README rewrite, ship

- [ ] Live: `/api/auth/start` returns a real authorize URL (discovery + DCR against production); photo upload round-trip with a generated PNG; `get_token()` still resolves via Keychain (Kai's setup unbroken).
- [ ] README: recipient-first quick start (clone → setup.sh → run → Connect → photo → reel), requirements (any Mac/Linux, Python 3.8+, Higgsfield account with credits), Claude Code listed as optional fallback.
- [ ] Full suite, commit, push, restart server.
