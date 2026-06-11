# Reel Swap Me In

Paste an Instagram Reel URL — get the reel back **starring you**.

The app downloads the reel, trims it to Higgsfield's 5–15 second window, then
has **Claude** (running headless via the `claude` CLI) drive the **Higgsfield
MCP server** to upload the clip plus your stored photo and run a
character-swap generation (Recast / WAN 2.2 Animate "replace" mode). The
result — the original reel's motion, framing, and pacing with *you* as the
subject — lands in `output/` and plays right in the page.

## One-time setup

1. **Run the setup script** (vendors `yt-dlp` + `ffmpeg` into `bin/` and
   registers the Higgsfield MCP server with Claude Code at user scope):

   ```sh
   ./setup.sh
   ```

2. **Authorize Higgsfield once.** Run `claude`, type `/mcp`, choose
   `higgsfield`, and complete the browser login. You need a
   [Higgsfield](https://higgsfield.ai) account **with generation credits** —
   each swap consumes credits. The OAuth token is stored by Claude Code and
   reused automatically by the app's headless runs.

3. **Add your photo.** Save a clear, front-facing photo of yourself as
   `assets/me.jpg`. It's gitignored.

(You also need to be logged in to Claude Code itself, which you already are if
`claude` works in your terminal.)

## Run it

```sh
python3 -m app.server
```

Open <http://localhost:8787>, paste a reel URL, hit **Replicate**, and wait —
generation typically takes a few minutes; the page narrates each stage
(uploading → submitted → rendering) with a live elapsed timer. The finished
video appears in the page and is saved under `output/`.

**Reels longer than 15 seconds:** the page pauses and shows the downloaded
reel with two sliders — pick the start point and the clip length (5–15s,
Higgsfield's limits). The preview loops just the selected window. Hit
**Use this part** to continue.

**Character reference:** on your first run (and again whenever you change
`assets/me.jpg`), the app has Higgsfield generate a clean character
reference from your photo — a single front-facing, full-body studio shot
(neutral expression, even lighting, empty hands, 9:16 framing) — caches it
as `assets/character-sheet.*`, and uses *that* as the swap reference.
That's the input shape WAN-Animate's replace mode responds to best, and it
gives far more identity signal than a casual photo. Costs credits once per
photo, not per reel. Delete `assets/character-sheet.*` any time to force a
regeneration.

Headless one-shot mode (optional args: clip start, clip length in seconds):

```sh
python3 replicate.py https://www.instagram.com/reel/XXXXXXXX/ 12.5 8
```

## How it works

```
reel URL → bin/yt-dlp (download, public reels only)
         → pick start + length (5–15s) if the reel runs long (page sliders)
         → bin/ffmpeg (reject <5s, cut the chosen window frame-accurately)
         → character sheet (generated once from assets/me.jpg via
           Higgsfield, cached as assets/character-sheet.*)
         → claude -p + Higgsfield MCP (upload clip + character sheet,
           run character-swap generation, poll to completion)
         → output/<job>.mp4 (served back to the page)
```

No frameworks, no pip installs — the server is Python stdlib only.

## Picking reels that swap well

Character-swap models have strong preferences. For the most convincing
results, pick reels where:

- there's **one person** in frame (with multiple people, the model swaps
  whoever is closest to the camera);
- the subject mostly **faces the camera** — fast head turns and long
  profile shots cause identity drift;
- the face isn't covered for long stretches (microphones, hands, props);
- lighting and exposure are **stable** across the clip;
- the subject's **build roughly matches yours** — drastic body-type
  mismatches map poorly;
- motion is continuous rather than fast and jerky.

A clear, evenly lit `assets/me.jpg` with your face unobstructed does the
rest.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "Couldn't download this reel" | The reel must be public. Some reels are age/region-gated and can't be fetched anonymously — try another reel. |
| "Reel too short" | Higgsfield needs at least 5 seconds of source video. |
| Errors mentioning auth / MCP | Run `claude`, type `/mcp`, re-authenticate `higgsfield`. Check `claude mcp list` shows it. |
| "No photo found" | Save your photo as `assets/me.jpg`. |
| Generation fails mid-run | Check your Higgsfield credit balance at higgsfield.ai. |
| `bin/yt-dlp` or `bin/ffmpeg` missing | Re-run `./setup.sh`. |

## Consent & content

- Swap in **your own** photo (or someone who has explicitly consented).
  Don't put other people into videos without their permission.
- The reels you replicate are other creators' content — keep results for
  personal use and respect creators' rights, Instagram's terms, and
  [Higgsfield's terms](https://higgsfield.ai).
