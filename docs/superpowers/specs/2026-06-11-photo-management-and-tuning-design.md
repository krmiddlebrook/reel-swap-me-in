# Photo Management & Face-Restore Tuning — Design

**Date:** 2026-06-11
**Status:** Approved by Kai (brainstorming session)

## Goal

Let the user see, add, remove, and promote the photos that drive both
identity systems (the Higgsfield character sheet and the local FaceFusion
face restore), and tune the face-restore quality knobs — all from one
collapsed card on the main page, with settings that persist.

## Decisions made during brainstorming

1. **Tuning depth:** simple dials by default + an "Advanced" expander
   (option C).
2. **Persistence:** settings save to a local JSON and apply to every
   future swap until changed (option A). Controls auto-save on change —
   no Save button.
3. **Layout:** one collapsed "Photos & tuning" card under the engine row;
   main page stays minimal (option B of three mockups).
4. **Main photo:** managed in the same gallery — badged MAIN, replaceable,
   and any extra can be promoted to main (option A). Promotion warns that
   the character sheet regenerates on the next run (1 credit).
5. **API shape:** unified photos resource replacing the split
   `/api/photo` + `/api/faces` endpoints (approach 1, clean break — no
   compatibility burden for a single-user local app).

## Architecture

### New module: `app/photos.py`

All photo file management, pure stdlib:

- `list_photos()` → `[{"name": str, "role": "main"|"extra"}]`, main first.
- `photo_path(name)` → safe absolute path or `None`. Single anti-traversal
  choke point: basename-only; must be the current main photo (`assets/me.*`)
  or a file inside `assets/faces/`.
- `save_main(data, ext)` / `save_extra(data, ext)` — byte-writing moved out
  of `server.py` handlers (magic-byte validation stays in the server, which
  owns HTTP concerns).
- `delete_extra(name)` — extras only. The main photo cannot be deleted
  (only replaced or promoted over); deleting it would silently re-trigger
  the setup banner.
- `promote(name)` — swap an extra with the main photo:
  1. move current main into `assets/faces/`,
  2. move the chosen extra to `assets/me.<ext>`,
  3. `os.utime` the new main to now.
  Step 3 is load-bearing: `os.replace` preserves mtime and the
  character-sheet cache is keyed on the main photo's mtime — without the
  bump, a stale sheet would survive the swap. If step 2 fails, step 1 is
  rolled back so a main photo always exists.

### `app/face_restore.py` additions

- `SETTINGS_PATH = assets/face-restore-settings.json` (needs its own
  `.gitignore` line — `assets/` is ignored per-pattern, not wholesale).
- `load_settings()` → dict with defaults merged; missing/corrupt file
  silently returns defaults (read path never raises).
- `save_settings(dict)` → validate against allowlists, write JSON.
- `build_command(...)` consumes settings instead of hardcoded values.

### Settings schema

| JSON key | FaceFusion flag | Default | Allowed |
|---|---|---|---|
| `enhancer_blend` | `--face-enhancer-blend` | `80` | int 0–100 |
| `pixel_boost` | `--face-swapper-pixel-boost` | `"512x512"` | `256x256`, `512x512`, `768x768`, `1024x1024` |
| `swapper_model` | `--face-swapper-model` | `"hyperswap_1a_256"` | `hyperswap_1a_256`, `hyperswap_1b_256`, `hyperswap_1c_256`, `inswapper_128_fp16`, `inswapper_128`, `ghost_2_256`, `simswap_256` |
| `enhancer_model` | `--face-enhancer-model` | `"gfpgan_1.4"` | `gfpgan_1.4`, `codeformer`, `restoreformer_plus_plus`, `gpen_bfr_512` |

Choices verified against the vendored FaceFusion 3.6.1 source
(`facefusion/processors/modules/face_swapper/choices.py`,
`face_enhancer/types.py`). All curated swapper models accept the four
pixel-boost values. Unknown keys in a POST are ignored; invalid values →
400 naming the offending key. Changing swapper/enhancer model triggers a
one-time model download on the next run (~250–700 MB) — noted in UI helper
text.

### Server routes

Replace `POST /api/photo`, `POST /api/faces`, `POST /api/faces/clear` with:

| Route | Method | Behavior |
|---|---|---|
| `/api/photos` | GET | photo list with roles |
| `/api/photos?role=main\|extra` | POST | upload (binary body; magic-byte validated; 20 MB cap; 9-extras cap; default role extra; `role=main` replaces the current main photo) |
| `/api/photos/<name>` | GET | image bytes (content-type from extension) for thumbnails |
| `/api/photos/<name>/promote` | POST | extra ↔ main swap |
| `/api/photos/<name>/delete` | POST | remove an extra |
| `/api/settings` | GET | current settings (defaults merged) |
| `/api/settings` | POST | validate + persist |

All POST routes (and `/api/*` GETs) stay behind the existing Origin check.
`/api/status` keeps its current fields (`photo` still gates setup).

### UI (`public/index.html`)

- "▸ Photos & tuning (N photos)" toggle under the engine/restore rows;
  collapsed by default; only shown once setup is complete. The tuning
  sub-section appears only when the server reports `faceRestore: true`;
  the photo strip (including add/remove/promote) works regardless — the
  main photo drives the character sheet either way, and extras simply
  have no effect until face restore is installed (the hint line says so).
- Expanded card:
  - **Photo strip:** thumbnails from `GET /api/photos/<name>`; MAIN badge
    on the main photo; ★ on extras = promote (confirm dialog mentioning
    the 1-credit sheet regeneration); × on extras = remove; + tile = add
    (multi-file input, posts sequentially). Hint line explains
    main-vs-extras roles.
  - **Simple dials:** "Face enhancement" slider (0–100, live % label) and
    "Detail quality" segmented control (Fast 256 / Standard 512 /
    High 768 / Max 1024), each with a one-line plain-English explanation.
  - **Advanced expander:** swapper model + enhancer model dropdowns with
    helper text; "Reset to defaults" link.
  - Auto-save: every change POSTs `/api/settings` immediately; a transient
    "✓ saved — applies to your next swap" line confirms.
- The old setup-card photo button uploads via `POST /api/photos?role=main`;
  the "Change photo" / "Add face photos" / "clear extras" status-line links
  are removed (absorbed by the gallery).
- Gallery re-renders from `GET /api/photos` after every mutation — server
  state is the only truth.

### Pipeline

Unchanged. `face_restore.restore` picks up settings via `build_command`;
`pipeline.restore_faces` already catches all exceptions, so a bad persisted
setting at worst yields a FaceFusion non-zero exit → existing
keep-raw-video-and-warn path.

## Error handling

- Settings: corrupt file → defaults; invalid POST value → 400 with key
  name; unknown keys ignored.
- Photos: unknown name on delete/promote → 404; delete main → 400
  ("promote another photo first"); upload guards unchanged.
- Promote: rollback to a consistent state if the second move fails.
- UI: fetch errors surface in the existing status line.

## Testing (TDD)

Write tests first for each unit (red → green):

- `tests/test_photos.py` (new): `list_photos` ordering/roles; `photo_path`
  traversal rejection (`../`, absolute paths, unknown names); `delete_extra`
  refuses main; `promote` swaps roles, bumps the new main's mtime, rolls
  back when the second move fails (mock `os.replace`).
- `tests/test_face_restore.py` (extend): `load_settings` defaults on
  missing/corrupt file; save/load round-trip; validation allowlists;
  `build_command` reflects non-default settings.
- `tests/test_server.py` (extend): settings POST validation responses;
  photos endpoint request parsing at the pure-helper level.
- Manual checklist: gallery add/remove/promote in the browser; settings
  persist across a server restart; one real swap with non-default settings.

## Out of scope

- Face-selector / multi-person tracking controls (reels are single-subject;
  would triple the advanced panel for a hypothetical).
- Per-run (non-persisted) setting overrides.
- Backward compatibility for the removed endpoints.
- Reordering extras (FaceFusion averages embeddings; order is irrelevant).
